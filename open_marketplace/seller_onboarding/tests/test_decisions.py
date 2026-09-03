"""Task 13 RED decision tests: seller application review decisions.

All new review operations are missing; every test below fails until
Task 13 implements them.
"""
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

from django.apps import apps
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import (
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import OperationContext

Account = apps.get_model("identity", "Account")
AccountSession = apps.get_model("identity", "AccountSession")
TotpCredential = apps.get_model("identity", "TotpCredential")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")


class ReviewDecisionTestCase(TestCase):
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def setUp(self):
        self.public = import_module("open_marketplace.seller_onboarding.public")
        self.models = import_module("open_marketplace.seller_onboarding.models")

    # --- fixtures -------------------------------------------------------

    def owner(self, *, totp=True):
        account = Account.objects.create_user(
            email=f"owner-{uuid4().hex}@example.com",
            password=self.password,
            state="active",
            email_verified_at=self.now - timedelta(days=1),
        )
        if totp:
            self.enable_totp(account)
        return account

    def service_account(self, *, roles=("seller_reviewer",)):
        account = Account.objects.create_service_account(
            email=f"staff-{uuid4().hex}@example.com",
            password=self.password,
            state="active",
            email_verified_at=self.now - timedelta(days=1),
        )
        self.enable_totp(account)
        for role in roles:
            apps.get_model("access", "RoleAssignment").objects.create(
                account_id=account.id,
                role=role,
                state="active",
                assigned_by_id=uuid4(),
                assigned_reason="test fixture",
                active_from=self.now - timedelta(days=1),
            )
        registry = self.registry(account)
        return account, registry

    def enable_totp(self, account):
        return TotpCredential.objects.create(
            account=account,
            encrypted_secret=b"encrypted-test-secret",
            confirmed_at=self.now - timedelta(days=1),
            last_accepted_counter=1,
        )

    def django_session(self):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=1),
        )
        return key

    def registry(
        self,
        account,
        *,
        reauthenticated_at=None,
        last_activity_at=None,
        absolute_expires_at=None,
        revoked_at=None,
    ):
        created_at = self.now - timedelta(hours=1)
        return AccountSession.objects.create(
            account=account,
            django_session_key=self.django_session(),
            created_at=created_at,
            last_activity_at=last_activity_at or (self.now - timedelta(minutes=1)),
            absolute_expires_at=absolute_expires_at
            or (self.now + timedelta(hours=12)),
            reauthenticated_at=reauthenticated_at
            if reauthenticated_at is not None
            else (self.now - timedelta(minutes=1)),
            device_label="Firefox on Linux",
            revoked_at=revoked_at,
        )

    def context(self, actor=None, *, registry=None, request_id=None, now=None):
        return OperationContext(
            actor_account_id=actor.id if actor is not None else None,
            session_id=registry.id if registry is not None else None,
            request_id=request_id or uuid4(),
            source="admin",
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def owner_context(self, owner, *, request_id=None):
        registry = self.registry(owner)
        return self.context(owner, registry=registry, request_id=request_id)

    def reviewer_context(self, *, request_id=None, stale=False):
        _, registry = self.service_account(roles=("seller_reviewer",))
        return self.context(
            registry.account,
            registry=registry,
            request_id=request_id,
            now=self.now if not stale else self.now + timedelta(minutes=16),
        )

    def security_context(self, *, request_id=None):
        account, registry = self.service_account(roles=("security_admin",))
        return self.context(account, registry=registry, request_id=request_id)

    def draft(self, **overrides):
        values = {
            "business_form": "sole_proprietor",
            "display_name": "Test shop",
            "official_name": "Test business",
            "registration_identifier": "TEST-123",
            "contact_email": "owner@example.com",
            "test_data_attested": True,
        }
        values.update(overrides)
        return self.public.SellerDraftData(**values)

    def submitted_application(self, owner, *, name="Test shop"):
        context = self.owner_context(owner)
        application_id = self.public.create_seller_application(context=context)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(display_name=name),
            context=context,
        )
        self.public.submit_seller_application(
            application_id=application_id,
            context=context,
        )
        return application_id, context

    def start_review(self, application_id, reviewer_context):
        self.public.start_seller_application_review(
            application_id=application_id,
            context=reviewer_context,
        )

    # --- tests ----------------------------------------------------------

    def test_start_review_requires_reviewer_role_totp_fresh_session_and_submitted_state(self):
        owner = self.owner()
        application_id, _ = self.submitted_application(owner)

        reviewer_context = self.reviewer_context()
        self.public.start_seller_application_review(
            application_id=application_id,
            context=reviewer_context,
        )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "under_review")
        self.assertEqual(application.reviewer_id, reviewer_context.actor_account_id)

        stale = self.reviewer_context(stale=True)
        with self.assertRaises(PermissionDenied):
            self.public.start_seller_application_review(
                application_id=application_id,
                context=stale,
            )

        security_context = self.security_context()
        with self.assertRaises(PermissionDenied):
            self.public.start_seller_application_review(
                application_id=application_id,
                context=security_context,
            )

    def test_start_review_is_denied_for_draft_under_review_and_terminal_states(self):
        owner = self.owner()
        context = self.owner_context(owner)
        reviewer_context = self.reviewer_context()

        application_id = self.public.create_seller_application(context=context)
        with self.assertRaises(InvalidState):
            self.public.start_seller_application_review(
                application_id=application_id,
                context=reviewer_context,
            )

        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(),
            context=context,
        )
        self.public.submit_seller_application(
            application_id=application_id,
            context=context,
        )
        self.public.start_seller_application_review(
            application_id=application_id,
            context=reviewer_context,
        )
        with self.assertRaises(InvalidState):
            self.public.start_seller_application_review(
                application_id=application_id,
                context=reviewer_context,
            )

        for state in ("approved", "rejected", "withdrawn"):
            with self.subTest(state=state):
                fresh_owner = self.owner()
                other, _ = self.submitted_application(fresh_owner)
                self.models.SellerApplication.objects.filter(pk=other).update(
                    state=state
                )
                with self.assertRaises(InvalidState):
                    self.public.start_seller_application_review(
                        application_id=other,
                        context=self.reviewer_context(),
                    )

    def test_request_changes_requires_under_review_reason_and_creates_new_version(self):
        owner = self.owner()
        application_id, owner_context = self.submitted_application(owner)
        reviewer_context = self.reviewer_context()

        # a request for changes is only possible while under review
        with self.assertRaises(InvalidState):
            self.public.request_seller_application_changes(
                application_id=application_id,
                reason="Too early.",
                context=reviewer_context,
            )

        self.start_review(application_id, reviewer_context)

        # the owner cannot edit while the application is under review
        with self.assertRaises(InvalidState):
            self.public.update_seller_application_draft(
                application_id=application_id,
                data=self.draft(display_name="changed"),
                context=owner_context,
            )

        with self.assertRaises(InputRejected):
            self.public.request_seller_application_changes(
                application_id=application_id,
                reason="   ",
                context=reviewer_context,
            )

        self.public.request_seller_application_changes(
            application_id=application_id,
            reason="Fix your display name.",
            context=reviewer_context,
        )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "changes_requested")
        self.assertEqual(application.reason, "Fix your display name.")

        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(display_name="Changed shop"),
            context=owner_context,
        )
        version_id = self.public.submit_seller_application(
            application_id=application_id,
            context=owner_context,
        )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "submitted")
        self.assertEqual(application.current_version, 2)
        self.assertEqual(
            self.models.SellerApplicationVersion.objects.get(pk=version_id).version_number,
            2,
        )

    def test_approve_creates_active_profile_and_decision_for_totp_owner(self):
        owner = self.owner(totp=True)
        application_id, _ = self.submitted_application(owner)
        reviewer_context = self.reviewer_context()
        self.start_review(application_id, reviewer_context)

        seller_id = self.public.approve_seller_application(
            application_id=application_id,
            reason="All test fields are correct.",
            context=reviewer_context,
        )

        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "approved")
        self.assertEqual(application.decision, "approve")
        self.assertEqual(application.reviewer_id, reviewer_context.actor_account_id)

        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.owner_id, owner.id)
        self.assertEqual(profile.application_id, application_id)
        self.assertEqual(profile.approved_version, 1)
        self.assertEqual(profile.state, "active")

        decision = self.models.SellerReviewDecision.objects.get(
            application_id=application_id
        )
        self.assertEqual(decision.decision, "approve")
        self.assertEqual(decision.reason, "All test fields are correct.")
        self.assertEqual(decision.reviewer_id, reviewer_context.actor_account_id)
        self.assertEqual(decision.request_id, reviewer_context.request_id)

        message = OutboxMessage.objects.get(
            message_type="seller_onboarding.application_decision",
            payload__application_id=str(application_id),
        )
        self.assertEqual(message.payload, {"application_id": str(application_id), "decision": "approve"})

        # only one profile even when the same request is retried
        retried_seller_id = self.public.approve_seller_application(
            application_id=application_id,
            reason="All test fields are correct.",
            context=reviewer_context,
        )
        self.assertEqual(retried_seller_id, seller_id)
        self.assertEqual(self.models.SellerProfile.objects.count(), 1)
        self.assertEqual(
            self.models.SellerReviewDecision.objects.filter(
                application_id=application_id
            ).count(),
            1,
        )
        self.assertEqual(
            OutboxMessage.objects.filter(
                message_type="seller_onboarding.application_decision"
            ).count(),
            1,
        )

    def test_different_request_cannot_approve_an_already_decided_version(self):
        owner = self.owner(totp=True)
        application_id, _ = self.submitted_application(owner)
        reviewer_context = self.reviewer_context()
        self.start_review(application_id, reviewer_context)
        self.public.approve_seller_application(
            application_id=application_id,
            reason="Looks good.",
            context=reviewer_context,
        )
        with self.assertRaises(InvalidState):
            self.public.approve_seller_application(
                application_id=application_id,
                reason="Looks good again.",
                context=self.reviewer_context(),
            )
        with self.assertRaises(InvalidState):
            self.public.reject_seller_application(
                application_id=application_id,
                reason="Changed my mind.",
                context=self.reviewer_context(),
            )

    def test_approve_is_denied_without_reason_or_from_wrong_state(self):
        owner = self.owner(totp=True)
        application_id, _ = self.submitted_application(owner)

        with self.assertRaises(InvalidState):
            self.public.approve_seller_application(
                application_id=application_id,
                reason="Too early.",
                context=self.reviewer_context(),
            )

        self.start_review(application_id, self.reviewer_context())
        with self.assertRaises(InputRejected):
            self.public.approve_seller_application(
                application_id=application_id,
                reason="   ",
                context=self.reviewer_context(),
            )

    def test_approve_denies_a_fresh_application_for_an_approved_owner(self):
        owner = self.owner(totp=True)
        application_id, _ = self.submitted_application(owner)
        reviewer_context = self.reviewer_context()
        self.start_review(application_id, reviewer_context)
        self.public.approve_seller_application(
            application_id=application_id,
            reason="Looks good.",
            context=reviewer_context,
        )

        with self.assertRaises(ConcurrentConflict):
            self.public.create_seller_application(context=self.owner_context(owner))

    def test_reject_is_terminal_and_allows_a_fresh_application_with_new_history(self):
        owner = self.owner()
        application_id, _ = self.submitted_application(owner, name="First shop")
        reviewer_context = self.reviewer_context()
        self.start_review(application_id, reviewer_context)
        self.public.reject_seller_application(
            application_id=application_id,
            reason="Not eligible.",
            context=reviewer_context,
        )

        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "rejected")
        self.assertEqual(application.decision, "reject")

        fresh_context = self.owner_context(owner)
        second_id = self.public.create_seller_application(context=fresh_context)
        self.assertNotEqual(second_id, application_id)
        self.public.update_seller_application_draft(
            application_id=second_id,
            data=self.draft(display_name="Second shop"),
            context=fresh_context,
        )
        self.public.submit_seller_application(
            application_id=second_id,
            context=fresh_context,
        )
        self.assertEqual(
            self.models.SellerApplicationVersion.objects.filter(
                application_id=application_id
            ).count(),
            1,
        )

    def test_review_queue_and_review_read_are_reviewer_scoped_and_bounded(self):
        owner = self.owner()
        first_id, _ = self.submitted_application(owner, name="First shop")
        second_owner = self.owner()
        second_id, _ = self.submitted_application(second_owner, name="Second shop")

        reviewer_context = self.reviewer_context()
        queue = self.public.list_seller_review_queue(
            query=self.public.SellerReviewQuery(
                states=("submitted",),
                reviewer_id=None,
                limit=100,
                cursor=None,
            ),
            context=reviewer_context,
        )
        self.assertEqual({application.id for application in queue}, {first_id, second_id})

        view, versions = self.public.get_seller_application_for_review(
            application_id=first_id,
            context=reviewer_context,
        )
        self.assertEqual(view.id, first_id)
        self.assertEqual(versions[0].version_number, 1)

        with self.assertRaises(PermissionDenied):
            self.public.list_seller_review_queue(
                query=self.public.SellerReviewQuery(
                    states=("submitted",),
                    reviewer_id=None,
                    limit=100,
                    cursor=None,
                ),
                context=self.security_context(),
            )

    def test_reviewer_cannot_edit_application_data_or_suspend_seller(self):
        owner = self.owner()
        application_id, _ = self.submitted_application(owner)
        reviewer_context = self.reviewer_context()
        self.start_review(application_id, reviewer_context)

        with self.assertRaises(PermissionDenied):
            self.public.update_seller_application_draft(
                application_id=application_id,
                data=self.draft(display_name="reviewer edited"),
                context=reviewer_context,
            )

        seller_id = self.public.approve_seller_application(
            application_id=application_id,
            reason="Good.",
            context=reviewer_context,
        )
        with self.assertRaises(PermissionDenied):
            self.public.suspend_seller(
                seller_id=seller_id,
                reason="nope",
                context=reviewer_context,
            )
