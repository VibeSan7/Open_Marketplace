from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import get_args
from uuid import uuid4
from unittest.mock import patch

from django.apps import apps
from django.contrib import admin
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
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
TotpRequirement = apps.get_model("identity", "TotpRequirement")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")


_DEFAULT = object()


class AccessTestCase(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public_module(self):
        return import_module("open_marketplace.access.public")

    def application_module(self):
        return import_module("open_marketplace.access.application")

    def assignment_model(self):
        return apps.get_model("access", "RoleAssignment")

    def create_account(
        self,
        *,
        kind=Account.Kind.SERVICE,
        state=Account.State.ACTIVE,
        verified=True,
        email=None,
    ):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        block_metadata = {}
        if state == Account.State.BLOCKED:
            block_metadata = {
                "blocked_at": self.now,
                "blocked_by_id": uuid4(),
                "block_reason": "Test fixture block.",
                "block_audit_id": uuid4(),
            }
        return create(
            email=email or f"person-{uuid4()}@example.com",
            password=self.password,
            state=state,
            email_verified_at=self.now - timedelta(days=1) if verified else None,
            **block_metadata,
        )

    def enable_totp(self, account):
        return TotpCredential.objects.create(
            account=account,
            encrypted_secret=b"encrypted-test-secret",
            confirmed_at=self.now - timedelta(days=1),
            last_accepted_counter=1,
        )

    def create_django_session(self, *, expires_at=None):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=expires_at or self.now + timedelta(days=1),
        )
        return key

    def create_registry(
        self,
        account,
        *,
        django_key=None,
        last_activity_at=None,
        absolute_expires_at=None,
        reauthenticated_at=_DEFAULT,
        revoked_at=None,
        revoked_reason=None,
    ):
        created_at = self.now - timedelta(hours=1)
        if reauthenticated_at is _DEFAULT:
            reauthenticated_at = self.now - timedelta(minutes=1)
        return AccountSession.objects.create(
            account=account,
            django_session_key=django_key or self.create_django_session(),
            created_at=created_at,
            last_activity_at=last_activity_at or self.now - timedelta(minutes=1),
            absolute_expires_at=absolute_expires_at or self.now + timedelta(hours=1),
            reauthenticated_at=reauthenticated_at,
            device_label="Firefox on Linux",
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
        )

    def context(
        self,
        registry=None,
        *,
        actor_id=_DEFAULT,
        session_id=_DEFAULT,
        now=None,
        request_id=None,
    ):
        if actor_id is _DEFAULT:
            actor_id = registry.account_id if registry is not None else None
        if session_id is _DEFAULT:
            session_id = registry.id if registry is not None else None
        return OperationContext(
            actor_account_id=actor_id,
            session_id=session_id,
            request_id=request_id or uuid4(),
            source="admin",
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def seed_assignment(
        self,
        account,
        role,
        *,
        state="active",
        assigned_by_id=None,
        active_from=None,
        revoked_by_id=None,
        revoked_reason=None,
        revoked_at=None,
    ):
        return self.assignment_model().objects.create(
            account_id=account.id,
            role=role,
            state=state,
            assigned_by_id=assigned_by_id,
            assigned_reason="accepted staff invitation",
            active_from=active_from or self.now - timedelta(days=1),
            revoked_by_id=revoked_by_id,
            revoked_reason=revoked_reason,
            revoked_at=revoked_at,
        )

    def prepare_authorized_actor(self, role="security_admin"):
        actor = self.create_account()
        self.enable_totp(actor)
        self.seed_assignment(actor, role)
        registry = self.create_registry(actor)
        return actor, registry, self.context(registry)


class PublicRoleContractTests(AccessTestCase):
    def test_public_surface_is_narrow_and_has_no_generic_role_grant(self):
        public = self.public_module()
        expected = (
            "PermissionCode",
            "StaffRole",
            "RoleAssignmentView",
            "authorize",
            "check_permission",
            "list_active_roles",
            "revoke_staff_role",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(public, name), f"{name} must be public.")

        for forbidden in (
            "grant_role",
            "grant_staff_role",
            "activate_role",
            "activate_staff_role",
            "create_role_assignment",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(hasattr(public, forbidden))

        self.assertEqual(
            set(get_args(public.StaffRole)),
            {"seller_reviewer", "security_admin"},
        )

    def test_role_assignment_model_and_view_preserve_revocable_history(self):
        public = self.public_module()
        RoleAssignment = self.assignment_model()

        self.assertIs(apps.get_model("access", "RoleAssignment"), RoleAssignment)
        self.assertNotIn(RoleAssignment, admin.site._registry)
        self.assertEqual(
            {field.name for field in RoleAssignment._meta.fields},
            {
                "id",
                "account_id",
                "role",
                "state",
                "assigned_by_id",
                "assigned_reason",
                "active_from",
                "revoked_by_id",
                "revoked_reason",
                "revoked_at",
            },
        )
        self.assertEqual(set(RoleAssignment.Role.values), {"seller_reviewer", "security_admin"})
        self.assertEqual(set(RoleAssignment.State.values), {"active", "revoked"})
        constraint_names = {constraint.name for constraint in RoleAssignment._meta.constraints}
        self.assertIn("access_one_active_role_assignment", constraint_names)
        self.assertIn("access_role_assignment_revocation_state", constraint_names)
        self.assertIn("access_role_assignment_revoked_after_start", constraint_names)

        account = self.create_account()
        assignment = self.seed_assignment(account, "seller_reviewer")
        view = public.RoleAssignmentView(
            id=assignment.id,
            account_id=account.id,
            role="seller_reviewer",
            active_from=assignment.active_from,
            revoked_at=None,
        )
        self.assertFalse(hasattr(view, "_state"))
        with self.assertRaises(FrozenInstanceError):
            view.role = "security_admin"

    def test_database_allows_history_but_only_one_active_account_role_pair(self):
        RoleAssignment = self.assignment_model()
        account = self.create_account()
        first = self.seed_assignment(account, "seller_reviewer")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.seed_assignment(account, "seller_reviewer")

        first.state = "revoked"
        first.revoked_by_id = uuid4()
        first.revoked_reason = "access removed"
        first.revoked_at = self.now
        first.save(update_fields={"state", "revoked_by_id", "revoked_reason", "revoked_at"})
        second = self.seed_assignment(account, "seller_reviewer", active_from=self.now)

        self.assertEqual(
            RoleAssignment.objects.filter(account_id=account.id, role="seller_reviewer").count(),
            2,
        )
        self.assertNotEqual(first.id, second.id)

        invalid_rows = (
            {
                "state": "active",
                "revoked_by_id": uuid4(),
                "revoked_reason": "unexpected",
                "revoked_at": self.now,
            },
            {
                "state": "revoked",
                "revoked_by_id": None,
                "revoked_reason": None,
                "revoked_at": None,
            },
            {
                "state": "revoked",
                "revoked_by_id": uuid4(),
                "revoked_reason": "too early",
                "revoked_at": self.now - timedelta(days=2),
            },
        )
        for values in invalid_rows:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    RoleAssignment.objects.create(
                        account_id=uuid4(),
                        role="security_admin",
                        assigned_by_id=None,
                        assigned_reason="bootstrap invitation accepted",
                        active_from=self.now - timedelta(days=1),
                        **values,
                    )


class RoleLifecycleTests(AccessTestCase):
    def test_internal_activation_is_atomic_adds_requirement_and_revokes_sessions(self):
        application = self.application_module()
        actor = self.create_account()
        actor_registry = self.create_registry(actor)
        target = self.create_account()
        self.enable_totp(target)
        target_session = self.create_registry(target)
        context = self.context(actor_registry)

        assignment_id = application._activate_staff_role(
            account_id=target.id,
            role="seller_reviewer",
            assigned_by_id=actor.id,
            reason="accepted invitation",
            context=context,
        )

        assignment = self.assignment_model().objects.get(pk=assignment_id)
        self.assertEqual(assignment.account_id, target.id)
        self.assertEqual(assignment.assigned_by_id, actor.id)
        self.assertEqual(assignment.state, "active")
        requirement = TotpRequirement.objects.get(
            account=target,
            source_type="staff_role",
            source_id=assignment.id,
        )
        self.assertIsNone(requirement.removed_at)
        target_session.refresh_from_db()
        self.assertEqual(target_session.revoked_at, self.now)
        self.assertEqual(target_session.revoked_reason, "role_changed")
        role_audit = AuditEntry.objects.get(action="access.staff_role_assigned")
        self.assertEqual(role_audit.actor_id, actor.id)
        self.assertEqual(role_audit.object_type, "role_assignment")
        self.assertEqual(role_audit.object_id, str(assignment.id))
        self.assertEqual(role_audit.after["role"], "seller_reviewer")
        message = OutboxMessage.objects.get(
            message_type="identity.protected_account_change",
            payload={"account_id": str(target.id), "change": "role_changed"},
        )
        self.assertIsNotNone(message.encrypted_delivery)

        with self.assertRaises(ConcurrentConflict):
            application._activate_staff_role(
                account_id=target.id,
                role="seller_reviewer",
                assigned_by_id=actor.id,
                reason="duplicate invitation",
                context=context,
            )
        self.assertEqual(
            self.assignment_model().objects.filter(
                account_id=target.id,
                role="seller_reviewer",
                state="active",
            ).count(),
            1,
        )

    def test_internal_activation_rejects_ineligible_target_and_invalid_input(self):
        application = self.application_module()
        actor = self.create_account()
        context = self.context(self.create_registry(actor))
        ordinary = self.create_account(kind=Account.Kind.ORDINARY)
        service_without_totp = self.create_account()

        for account in (ordinary, service_without_totp):
            with self.subTest(account=account.id), self.assertRaises(InvalidState):
                application._activate_staff_role(
                    account_id=account.id,
                    role="seller_reviewer",
                    assigned_by_id=actor.id,
                    reason="accepted invitation",
                    context=context,
                )

        for values in (
            {"role": "owner", "reason": "accepted invitation"},
            {"role": "seller_reviewer", "reason": ""},
            {"role": "seller_reviewer", "reason": "x" * 1025},
        ):
            with self.subTest(values=values), self.assertRaises(InputRejected):
                application._activate_staff_role(
                    account_id=service_without_totp.id,
                    assigned_by_id=actor.id,
                    context=context,
                    **values,
                )

    def test_activation_rolls_back_assignment_requirement_sessions_audit_and_outbox(self):
        application = self.application_module()
        actor = self.create_account()
        context = self.context(self.create_registry(actor))
        target = self.create_account()
        self.enable_totp(target)
        target_session = self.create_registry(target)
        before_audit = AuditEntry.objects.count()
        before_outbox = OutboxMessage.objects.count()

        with patch(
            "open_marketplace.access.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            application._activate_staff_role(
                account_id=target.id,
                role="security_admin",
                assigned_by_id=actor.id,
                reason="accepted invitation",
                context=context,
            )

        self.assertFalse(self.assignment_model().objects.filter(account_id=target.id).exists())
        self.assertFalse(TotpRequirement.objects.filter(account=target).exists())
        target_session.refresh_from_db()
        self.assertIsNone(target_session.revoked_at)
        self.assertEqual(AuditEntry.objects.count(), before_audit)
        self.assertEqual(OutboxMessage.objects.count(), before_outbox)

    def test_activation_does_not_misclassify_late_integrity_error(self):
        application = self.application_module()
        actor = self.create_account()
        context = self.context(self.create_registry(actor))
        target = self.create_account()
        self.enable_totp(target)

        with patch(
            "open_marketplace.access.application.enqueue_outbox_message",
            side_effect=IntegrityError("outbox constraint"),
        ), self.assertRaises(IntegrityError):
            application._activate_staff_role(
                account_id=target.id,
                role="seller_reviewer",
                assigned_by_id=actor.id,
                reason="accepted invitation",
                context=context,
            )

        self.assertFalse(self.assignment_model().objects.filter(account_id=target.id).exists())
        self.assertFalse(TotpRequirement.objects.filter(account=target).exists())

    def test_only_security_admin_can_list_active_roles_for_any_account(self):
        public = self.public_module()
        admin_account, admin_registry, admin_context = self.prepare_authorized_actor()
        target = self.create_account()
        active = self.seed_assignment(target, "seller_reviewer")
        revoked = self.seed_assignment(
            target,
            "security_admin",
            state="revoked",
            revoked_by_id=admin_account.id,
            revoked_reason="removed",
            revoked_at=self.now,
        )

        views = public.list_active_roles(account_id=target.id, context=admin_context)

        self.assertEqual(tuple(view.id for view in views), (active.id,))
        self.assertNotIn(revoked.id, {view.id for view in views})

        reviewer, reviewer_registry, reviewer_context = self.prepare_authorized_actor(
            "seller_reviewer"
        )
        with self.assertRaises(PermissionDenied):
            public.list_active_roles(account_id=reviewer.id, context=reviewer_context)

        self.assertTrue(admin_account.is_staff)
        self.assertTrue(reviewer.is_staff)
        self.assertIsNotNone(admin_registry.id)

    def test_revoke_role_removes_only_matching_requirement_and_revokes_target_sessions(self):
        public = self.public_module()
        actor, _, context = self.prepare_authorized_actor()
        target = self.create_account()
        self.enable_totp(target)
        assignment = self.seed_assignment(target, "seller_reviewer", assigned_by_id=actor.id)
        other_assignment = self.seed_assignment(target, "security_admin", assigned_by_id=actor.id)
        matching = TotpRequirement.objects.create(
            account=target,
            source_type="staff_role",
            source_id=assignment.id,
            created_at=self.now - timedelta(days=1),
        )
        other_role = TotpRequirement.objects.create(
            account=target,
            source_type="staff_role",
            source_id=other_assignment.id,
            created_at=self.now - timedelta(days=1),
        )
        seller = TotpRequirement.objects.create(
            account=target,
            source_type="seller_profile",
            source_id=uuid4(),
            created_at=self.now - timedelta(days=1),
        )
        sessions = (self.create_registry(target), self.create_registry(target))

        result = public.revoke_staff_role(
            assignment_id=assignment.id,
            reason="employment ended",
            context=context,
        )

        self.assertIsNone(result)
        assignment.refresh_from_db()
        self.assertEqual(assignment.state, "revoked")
        self.assertEqual(assignment.revoked_by_id, actor.id)
        self.assertEqual(assignment.revoked_reason, "employment ended")
        self.assertEqual(assignment.revoked_at, self.now)
        matching.refresh_from_db()
        other_role.refresh_from_db()
        seller.refresh_from_db()
        self.assertEqual(matching.removed_at, self.now)
        self.assertIsNone(other_role.removed_at)
        self.assertIsNone(seller.removed_at)
        for registry in sessions:
            registry.refresh_from_db()
            self.assertEqual(registry.revoked_at, self.now)
            self.assertEqual(registry.revoked_reason, "role_changed")
        audit = AuditEntry.objects.get(action="access.staff_role_revoked")
        self.assertEqual(audit.actor_id, actor.id)
        self.assertEqual(audit.effective_role, "security_admin")
        self.assertEqual(audit.reason, "employment ended")
        self.assertEqual(audit.before, {"role": "seller_reviewer", "state": "active"})
        self.assertEqual(
            audit.after,
            {
                "role": "seller_reviewer",
                "state": "revoked",
                "requirement_source": "staff_role",
                "revoked_session_count": 2,
            },
        )
        self.assertTrue(
            OutboxMessage.objects.filter(
                message_type="identity.protected_account_change",
                payload={"account_id": str(target.id), "change": "role_changed"},
            ).exists()
        )

    def test_revoke_requires_exact_permission_reason_and_active_assignment(self):
        public = self.public_module()
        reviewer, reviewer_registry, reviewer_context = self.prepare_authorized_actor(
            "seller_reviewer"
        )
        target = self.create_account()
        assignment = self.seed_assignment(target, "seller_reviewer")

        with self.assertRaises(PermissionDenied):
            public.revoke_staff_role(
                assignment_id=assignment.id,
                reason="not allowed",
                context=reviewer_context,
            )
        assignment.refresh_from_db()
        self.assertEqual(assignment.state, "active")

        _, _, admin_context = self.prepare_authorized_actor()
        for reason in ("", "   ", "x" * 1025):
            with self.subTest(reason_length=len(reason)), self.assertRaises(InputRejected):
                public.revoke_staff_role(
                    assignment_id=assignment.id,
                    reason=reason,
                    context=admin_context,
                )

        assignment.state = "revoked"
        assignment.revoked_by_id = reviewer.id
        assignment.revoked_reason = "already removed"
        assignment.revoked_at = self.now
        assignment.save(update_fields={"state", "revoked_by_id", "revoked_reason", "revoked_at"})
        with self.assertRaises(InvalidState):
            public.revoke_staff_role(
                assignment_id=assignment.id,
                reason="repeat",
                context=admin_context,
            )
        self.assertIsNotNone(reviewer_registry.id)

    def test_revoke_rolls_back_every_effect_when_outbox_fails(self):
        public = self.public_module()
        actor, _, context = self.prepare_authorized_actor()
        target = self.create_account()
        self.enable_totp(target)
        assignment = self.seed_assignment(target, "seller_reviewer", assigned_by_id=actor.id)
        requirement = TotpRequirement.objects.create(
            account=target,
            source_type="staff_role",
            source_id=assignment.id,
            created_at=self.now - timedelta(days=1),
        )
        target_session = self.create_registry(target)
        before_audit = AuditEntry.objects.count()
        before_outbox = OutboxMessage.objects.count()

        with patch(
            "open_marketplace.access.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            public.revoke_staff_role(
                assignment_id=assignment.id,
                reason="employment ended",
                context=context,
            )

        assignment.refresh_from_db()
        requirement.refresh_from_db()
        target_session.refresh_from_db()
        self.assertEqual(assignment.state, "active")
        self.assertIsNone(assignment.revoked_at)
        self.assertIsNone(requirement.removed_at)
        self.assertIsNone(target_session.revoked_at)
        self.assertEqual(AuditEntry.objects.count(), before_audit)
        self.assertEqual(OutboxMessage.objects.count(), before_outbox)
