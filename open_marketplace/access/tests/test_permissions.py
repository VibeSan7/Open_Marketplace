from datetime import timedelta
from typing import get_args
from uuid import uuid4

from django.apps import apps
from django.contrib.sessions.models import Session

from open_marketplace.common.errors import InputRejected, PermissionDenied
from open_marketplace.common.types import OperationContext
from open_marketplace.access.tests.test_roles import AccessTestCase


Account = apps.get_model("identity", "Account")
AuditEntry = apps.get_model("audit", "AuditEntry")


PERMISSION_CODES = (
    "seller_application.read",
    "seller_application.review",
    "staff.invite",
    "staff.invitation_revoke",
    "staff.role_revoke",
    "account.read",
    "account.block",
    "account.unblock",
    "identity.mandatory_totp_recover",
    "seller.read",
    "seller.suspend",
    "seller.restore",
    "seller.revoke",
    "audit.read",
    "outbox.manual_retry",
    "catalog.read",
    "catalog.manage",
)
SELLER_REVIEWER_PERMISSIONS = {
    "seller_application.read",
    "seller_application.review",
    "audit.read",
}
SECURITY_ADMIN_PERMISSIONS = {
    "staff.invite",
    "staff.invitation_revoke",
    "staff.role_revoke",
    "account.read",
    "account.block",
    "account.unblock",
    "identity.mandatory_totp_recover",
    "seller.read",
    "seller.suspend",
    "seller.restore",
    "seller.revoke",
    "audit.read",
    "outbox.manual_retry",
    "catalog.read",
    "catalog.manage",
}
SENSITIVE_PERMISSIONS = {
    "seller_application.review",
    "staff.invite",
    "staff.invitation_revoke",
    "staff.role_revoke",
    "account.block",
    "account.unblock",
    "identity.mandatory_totp_recover",
    "seller.suspend",
    "seller.restore",
    "seller.revoke",
    "outbox.manual_retry",
    "catalog.manage",
}
READ_ONLY_PERMISSIONS = {
    "seller_application.read",
    "account.read",
    "seller.read",
    "audit.read",
    "catalog.read",
}
REVIEWER_AUDIT_SCOPES = (
    "audit:object_type:seller_application",
    "audit:object_type:seller_application_version",
    "audit:object_type:seller_review_decision",
)
SECURITY_AUDIT_SCOPES = (
    "audit:object_type:account",
    "audit:object_type:session",
    "audit:object_type:staff_invitation",
    "audit:object_type:role_assignment",
    "audit:object_type:seller_profile",
    "audit:object_type:outbox_message",
    "audit:object_type:catalog_product",
    "audit:object_type:catalog_variant",
    "audit:object_type:catalog_stock",
    "audit:object_type:catalog_category",
    "audit:object_type:catalog_participant",
)


class ExactPermissionMatrixTests(AccessTestCase):
    def permitted_permissions(self, context):
        public = self.public_module()
        allowed = set()
        for permission in PERMISSION_CODES:
            try:
                public.authorize(context=context, permission=permission)
            except PermissionDenied:
                continue
            allowed.add(permission)
        return allowed

    def role_context(self, *roles, reauthenticated_at=None):
        account = self.create_account()
        self.enable_totp(account)
        for role in roles:
            self.seed_assignment(account, role)
        registry = self.create_registry(
            account,
            reauthenticated_at=(
                self.now - timedelta(minutes=1)
                if reauthenticated_at is None
                else reauthenticated_at
            ),
        )
        return account, registry, self.context(registry)

    def test_permission_code_is_the_exact_closed_catalog_release_literal(self):
        public = self.public_module()
        self.assertEqual(tuple(get_args(public.PermissionCode)), PERMISSION_CODES)
        self.assertEqual(len(PERMISSION_CODES), 17)

    def test_each_role_and_dual_role_receive_only_the_exact_permission_matrix(self):
        _, _, reviewer_context = self.role_context("seller_reviewer")
        _, _, security_context = self.role_context("security_admin")
        _, _, dual_context = self.role_context("seller_reviewer", "security_admin")

        self.assertEqual(
            self.permitted_permissions(reviewer_context),
            SELLER_REVIEWER_PERMISSIONS,
        )
        self.assertEqual(
            self.permitted_permissions(security_context),
            SECURITY_ADMIN_PERMISSIONS,
        )
        self.assertEqual(
            self.permitted_permissions(dual_context),
            SELLER_REVIEWER_PERMISSIONS | SECURITY_ADMIN_PERMISSIONS,
        )

    def test_decision_contains_only_roles_that_grant_the_requested_permission(self):
        account, _, context = self.role_context("seller_reviewer", "security_admin")
        public = self.public_module()

        review = public.authorize(context=context, permission="seller_application.review")
        security = public.authorize(context=context, permission="account.block")
        audit = public.authorize(context=context, permission="audit.read")

        self.assertEqual(review.account_id, account.id)
        self.assertEqual(review.permission, "seller_application.review")
        self.assertEqual(review.effective_roles, ("seller_reviewer",))
        self.assertEqual(security.effective_roles, ("security_admin",))
        self.assertEqual(audit.effective_roles, ("seller_reviewer", "security_admin"))
        self.assertEqual(review.reauthenticated_at, context.now - timedelta(minutes=1))

    def test_exact_scopes_are_stable_closed_and_union_without_duplicates(self):
        public = self.public_module()
        _, _, reviewer_context = self.role_context("seller_reviewer")
        _, _, security_context = self.role_context("security_admin")
        _, _, dual_context = self.role_context("seller_reviewer", "security_admin")

        reviewer_audit = public.authorize(
            context=reviewer_context,
            permission="audit.read",
        )
        security_audit = public.authorize(
            context=security_context,
            permission="audit.read",
        )
        dual_audit = public.authorize(context=dual_context, permission="audit.read")
        outbox = public.authorize(
            context=security_context,
            permission="outbox.manual_retry",
        )

        self.assertEqual(reviewer_audit.scopes, REVIEWER_AUDIT_SCOPES)
        self.assertEqual(security_audit.scopes, SECURITY_AUDIT_SCOPES)
        self.assertEqual(dual_audit.scopes, REVIEWER_AUDIT_SCOPES + SECURITY_AUDIT_SCOPES)
        self.assertEqual(len(dual_audit.scopes), len(set(dual_audit.scopes)))
        self.assertEqual(outbox.scopes, ("outbox:state:manual_review",))

        for permission in set(PERMISSION_CODES) - {"audit.read", "outbox.manual_retry"}:
            context = (
                reviewer_context
                if permission in SELLER_REVIEWER_PERMISSIONS
                else security_context
            )
            with self.subTest(permission=permission):
                self.assertEqual(
                    public.authorize(context=context, permission=permission).scopes,
                    (),
                )

    def test_sensitive_permissions_require_strictly_fresh_nonfuture_reauthentication(self):
        public = self.public_module()
        account = self.create_account()
        self.enable_totp(account)
        self.seed_assignment(account, "seller_reviewer")
        self.seed_assignment(account, "security_admin")
        equality = self.create_registry(
            account,
            reauthenticated_at=self.now - timedelta(minutes=15),
        )
        fresh = self.create_registry(
            account,
            reauthenticated_at=self.now - timedelta(minutes=15) + timedelta(microseconds=1),
        )
        future = self.create_registry(
            account,
            reauthenticated_at=self.now + timedelta(microseconds=1),
        )

        for permission in SENSITIVE_PERMISSIONS:
            with self.subTest(permission=permission, boundary="equal"), self.assertRaises(
                PermissionDenied
            ):
                public.authorize(context=self.context(equality), permission=permission)
            with self.subTest(permission=permission, boundary="fresh"):
                decision = public.authorize(
                    context=self.context(fresh),
                    permission=permission,
                )
                self.assertEqual(decision.permission, permission)
            with self.subTest(permission=permission, boundary="future"), self.assertRaises(
                PermissionDenied
            ):
                public.authorize(context=self.context(future), permission=permission)

    def test_read_only_permissions_do_not_require_reauthentication(self):
        public = self.public_module()
        account = self.create_account()
        self.enable_totp(account)
        self.seed_assignment(account, "seller_reviewer")
        self.seed_assignment(account, "security_admin")
        registry = self.create_registry(account, reauthenticated_at=None)
        context = self.context(registry)

        for permission in READ_ONLY_PERMISSIONS:
            with self.subTest(permission=permission):
                decision = public.authorize(context=context, permission=permission)
                self.assertEqual(decision.permission, permission)
                self.assertIsNone(decision.reauthenticated_at)

    def test_check_permission_and_authorize_apply_the_same_implementation(self):
        public = self.public_module()
        _, _, context = self.role_context("seller_reviewer")

        direct = public.authorize(
            context=context,
            permission="seller_application.read",
        )
        checked = public.check_permission(
            permission="seller_application.read",
            context=context,
        )

        self.assertEqual(checked, direct)


class PermissionDenialTests(AccessTestCase):
    def assert_permission_denied(self, *, context, permission="account.read"):
        with self.assertRaises(PermissionDenied) as raised:
            self.public_module().authorize(context=context, permission=permission)
        self.assertEqual(str(raised.exception), "Permission denied.")

    def test_account_kind_state_verification_totp_and_assignment_all_fail_closed(self):
        ordinary = self.create_account(kind=Account.Kind.ORDINARY)
        self.enable_totp(ordinary)
        self.seed_assignment(ordinary, "security_admin")
        ordinary_context = self.context(self.create_registry(ordinary))

        no_assignment = self.create_account()
        self.enable_totp(no_assignment)
        no_assignment_context = self.context(self.create_registry(no_assignment))
        self.assertTrue(no_assignment.is_staff)

        no_totp = self.create_account()
        self.seed_assignment(no_totp, "security_admin")
        no_totp_context = self.context(self.create_registry(no_totp))

        blocked = self.create_account(state=Account.State.BLOCKED)
        self.enable_totp(blocked)
        self.seed_assignment(blocked, "security_admin")
        blocked_context = self.context(self.create_registry(blocked))

        pending = self.create_account(
            state=Account.State.PENDING_EMAIL_VERIFICATION,
            verified=False,
        )
        self.enable_totp(pending)
        self.seed_assignment(pending, "security_admin")
        pending_context = self.context(self.create_registry(pending))

        unverified = self.create_account(verified=False)
        self.enable_totp(unverified)
        self.seed_assignment(unverified, "security_admin")
        unverified_context = self.context(self.create_registry(unverified))

        for name, context in (
            ("ordinary", ordinary_context),
            ("is_staff_without_role", no_assignment_context),
            ("without_totp", no_totp_context),
            ("blocked", blocked_context),
            ("pending", pending_context),
            ("unverified", unverified_context),
        ):
            with self.subTest(name=name):
                self.assert_permission_denied(context=context)

    def test_missing_unknown_revoked_expired_idle_or_foreign_session_fails_closed(self):
        account = self.create_account()
        self.enable_totp(account)
        self.seed_assignment(account, "security_admin")
        other = self.create_account()
        self.enable_totp(other)
        self.seed_assignment(other, "security_admin")

        valid = self.create_registry(account)
        foreign = self.create_registry(other)
        revoked = self.create_registry(
            account,
            revoked_at=self.now - timedelta(seconds=1),
            revoked_reason="user_revoked",
        )
        expired = self.create_registry(account, absolute_expires_at=self.now)
        idle = self.create_registry(
            account,
            last_activity_at=self.now - timedelta(minutes=30),
        )
        backing_expired = self.create_registry(
            account,
            django_key=self.create_django_session(expires_at=self.now),
        )
        orphan = self.create_registry(account)
        Session.objects.filter(session_key=orphan.django_session_key).delete()

        contexts = (
            self.context(None, actor_id=None, session_id=None),
            self.context(None, actor_id=account.id, session_id=None),
            self.context(None, actor_id=account.id, session_id=uuid4()),
            self.context(None, actor_id=account.id, session_id=foreign.id),
            self.context(revoked),
            self.context(expired),
            self.context(idle),
            self.context(backing_expired),
            self.context(orphan),
        )
        for context in contexts:
            with self.subTest(actor=context.actor_account_id, session=context.session_id):
                self.assert_permission_denied(context=context)

        self.assertEqual(
            self.public_module().authorize(
                context=self.context(valid),
                permission="account.read",
            ).account_id,
            account.id,
        )

    def test_invalid_permission_and_context_are_input_errors_not_role_fallbacks(self):
        account = self.create_account()
        self.enable_totp(account)
        self.seed_assignment(account, "security_admin")
        registry = self.create_registry(account)
        public = self.public_module()

        for permission in (None, "*", "account.*", "django.auth.change_user"):
            with self.subTest(permission=permission), self.assertRaises(InputRejected):
                public.authorize(context=self.context(registry), permission=permission)

        invalid_context = OperationContext(
            actor_account_id=account.id,
            session_id=registry.id,
            request_id=uuid4(),
            source="admin",
            source_address="203.0.113.10",
            now=self.now.replace(tzinfo=None),
        )
        with self.assertRaises(InputRejected):
            public.authorize(context=invalid_context, permission="account.read")

    def test_denial_writes_one_safe_audit_entry_and_exposes_one_neutral_error(self):
        account = self.create_account()
        self.enable_totp(account)
        registry = self.create_registry(account)
        context = self.context(registry)

        self.assert_permission_denied(context=context, permission="account.block")

        entries = AuditEntry.objects.filter(action="access.permission_denied")
        self.assertEqual(entries.count(), 1)
        entry = entries.get()
        self.assertEqual(entry.actor_id, account.id)
        self.assertEqual(entry.object_type, "account")
        self.assertEqual(entry.object_id, str(account.id))
        self.assertEqual(entry.result, "denied")
        self.assertEqual(entry.reason, "permission_denied")
        self.assertEqual(entry.before, {})
        self.assertEqual(entry.after, {})
        self.assertIsNone(entry.effective_role)
        serialized = repr(
            {
                "action": entry.action,
                "object_type": entry.object_type,
                "object_id": entry.object_id,
                "reason": entry.reason,
                "before": entry.before,
                "after": entry.after,
            }
        ).casefold()
        for forbidden in ("password", "secret", "recovery_code", "token", "totp"):
            self.assertNotIn(forbidden, serialized)
