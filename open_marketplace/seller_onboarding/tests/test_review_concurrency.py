"""Task 13 RED concurrency and idempotency tests.

All new seller review/admission operations are missing; every test below
fails until Task 13 implements them.
"""
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

from django.apps import apps
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import ConcurrentConflict, InvalidState
from open_marketplace.common.types import OperationContext

Account = apps.get_model("identity", "Account")
AccountSession = apps.get_model("identity", "AccountSession")
TotpCredential = apps.get_model("identity", "TotpCredential")


class SellerReviewConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def setUp(self):
        self.public = import_module("open_marketplace.seller_onboarding.public")
        self.models = import_module("open_marketplace.seller_onboarding.models")
        self.owner = self.owner_account()
        self.reviewer = self.staff_account("seller_reviewer")
        self.application_id, _ = self.submitted_application(self.owner)

    # --- fixtures -------------------------------------------------------

    def owner_account(self):
        account = Account.objects.create_user(
            email=f"owner-{uuid4().hex}@example.com",
            password=self.password,
            state="active",
            email_verified_at=self.now - timedelta(days=1),
        )
        TotpCredential.objects.create(
            account=account,
            encrypted_secret=b"encrypted-test-secret",
            confirmed_at=self.now - timedelta(days=1),
            last_accepted_counter=1,
        )
        return account

    def staff_account(self, role):
        account = Account.objects.create_service_account(
            email=f"staff-{uuid4().hex}@example.com",
            password=self.password,
            state="active",
            email_verified_at=self.now - timedelta(days=1),
        )
        TotpCredential.objects.create(
            account=account,
            encrypted_secret=b"encrypted-test-secret",
            confirmed_at=self.now - timedelta(days=1),
            last_accepted_counter=1,
        )
        apps.get_model("access", "RoleAssignment").objects.create(
            account_id=account.id,
            role=role,
            state="active",
            assigned_by_id=uuid4(),
            assigned_reason="test fixture",
            active_from=self.now - timedelta(days=1),
        )
        return account

    def django_session(self):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=1),
        )
        return key

    def context(self, account, *, request_id=None, now=None):
        registry = AccountSession.objects.create(
            account=account,
            django_session_key=self.django_session(),
            created_at=self.now - timedelta(hours=1),
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(hours=12),
            reauthenticated_at=self.now - timedelta(minutes=1),
            device_label="Firefox on Linux",
        )
        return OperationContext(
            actor_account_id=account.id,
            session_id=registry.id,
            request_id=request_id or uuid4(),
            source="admin",
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def owner_context(self, *, request_id=None):
        return OperationContext(
            actor_account_id=self.owner.id,
            session_id=None,
            request_id=request_id or uuid4(),
            source="html",
            source_address="192.0.2.10",
            now=self.now,
        )

    def draft(self, name):
        return self.public.SellerDraftData(
            business_form="sole_proprietor",
            display_name=name,
            official_name=f"{name} business",
            registration_identifier=f"ID-{name}",
            contact_email="owner@example.com",
            test_data_attested=True,
        )

    def submitted_application(self, owner):
        context = self.owner_context()
        application_id = self.public.create_seller_application(context=context)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft("shop"),
            context=context,
        )
        self.public.submit_seller_application(
            application_id=application_id,
            context=context,
        )
        return application_id, context

    def run_parallel(self, operation):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        barrier = Barrier(2)

        def invoke(_):
            close_old_connections()
            try:
                barrier.wait()
                return ("ok", operation())
            except Exception as error:
                return ("error", type(error))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return tuple(executor.map(invoke, range(2)))

    # --- tests ----------------------------------------------------------

    def test_simultaneous_start_claims_review_once(self):
        results = self.run_parallel(
            lambda: self.public.start_seller_application_review(
                application_id=self.application_id,
                context=self.context(self.reviewer),
            )
        )
        self.assertEqual(sum(result[0] == "ok" for result in results), 1)
        errors = [result[1] for result in results if result[0] == "error"]
        self.assertTrue(errors)
        self.assertTrue(
            all(error in (InvalidState, ConcurrentConflict) for error in errors)
        )
        application = self.models.SellerApplication.objects.get(pk=self.application_id)
        self.assertEqual(application.state, "under_review")

    def test_simultaneous_approval_creates_one_profile_and_one_event(self):
        self.public.start_seller_application_review(
            application_id=self.application_id,
            context=self.context(self.reviewer),
        )
        results = self.run_parallel(
            lambda: self.public.approve_seller_application(
                application_id=self.application_id,
                reason="All good.",
                context=self.context(self.reviewer),
            )
        )
        self.assertEqual(sum(result[0] == "ok" for result in results), 1)
        errors = [result[1] for result in results if result[0] == "error"]
        self.assertTrue(errors)
        self.assertTrue(
            all(error in (InvalidState, ConcurrentConflict) for error in errors)
        )
        self.assertEqual(self.models.SellerProfile.objects.count(), 1)
        self.assertEqual(
            self.models.SellerReviewDecision.objects.filter(
                application_id=self.application_id
            ).count(),
            1,
        )
        self.assertEqual(
            apps.get_model("outbox", "OutboxMessage")
            .objects.filter(message_type="seller_onboarding.application_decision")
            .count(),
            1,
        )

    def test_request_id_retry_is_idempotent_for_approval(self):
        self.public.start_seller_application_review(
            application_id=self.application_id,
            context=self.context(self.reviewer),
        )
        request_id = uuid4()
        context = self.context(self.reviewer, request_id=request_id)
        seller_id = self.public.approve_seller_application(
            application_id=self.application_id,
            reason="All good.",
            context=context,
        )
        retried_id = self.public.approve_seller_application(
            application_id=self.application_id,
            reason="All good.",
            context=context,
        )
        self.assertEqual(retried_id, seller_id)
        self.assertEqual(self.models.SellerProfile.objects.count(), 1)
        self.assertEqual(
            self.models.SellerReviewDecision.objects.filter(
                application_id=self.application_id
            ).count(),
            1,
        )
        self.assertEqual(
            apps.get_model("outbox", "OutboxMessage")
            .objects.filter(message_type="seller_onboarding.application_decision")
            .count(),
            1,
        )
