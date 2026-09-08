from unittest.mock import patch
from uuid import UUID, uuid4

from django.urls import reverse

from open_marketplace.common.errors import InputRejected
from open_marketplace.staff_admin.tests.helpers import StaffAdminTestCase


class StaffAdminOperationTests(StaffAdminTestCase):
    def assert_admin_context(self, operation, account, registry):
        context = operation.call_args.kwargs["context"]
        self.assertEqual(context.actor_account_id, account.id)
        self.assertEqual(context.session_id, registry.id)
        self.assertEqual(context.source, "admin")
        self.assertEqual(context.source_address, "198.51.100.17")
        self.assertIsInstance(context.request_id, UUID)

    def test_staff_invitation_create_calls_public_contract_and_uses_prg(self):
        account, registry = self.authenticate_staff("security_admin")
        with patch(
            "open_marketplace.staff_admin.access_admin.access_public.invite_staff_member",
            return_value=uuid4(),
        ) as operation:
            response = self.csrf_post(
                "admin:staff-invitation-create",
                {"email": "reviewer@example.com", "role": "seller_reviewer"},
                REMOTE_ADDR="198.51.100.17",
                HTTP_X_FORWARDED_FOR="203.0.113.99",
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("admin:staff-invitation-list"))
        self.assertEqual(operation.call_args.kwargs["email"], "reviewer@example.com")
        self.assertEqual(operation.call_args.kwargs["role"], "seller_reviewer")
        self.assert_admin_context(operation, account, registry)

    def test_identity_actions_call_only_public_contracts_with_reason(self):
        account, registry = self.authenticate_staff("security_admin")
        target_id = uuid4()
        cases = (
            ("admin:account-block", "block_account"),
            ("admin:account-unblock", "unblock_account"),
            ("admin:account-recover-totp", "recover_mandatory_totp"),
        )
        for route, function in cases:
            with self.subTest(function=function), patch(
                f"open_marketplace.staff_admin.identity_admin.identity_public.{function}"
            ) as operation:
                response = self.csrf_post(
                    route,
                    {"reason": "Verified support request."},
                    kwargs={"account_id": target_id},
                    REMOTE_ADDR="198.51.100.17",
                )
                self.assertEqual(response.status_code, 303)
                self.assertEqual(operation.call_args.kwargs["account_id"], target_id)
                self.assertEqual(
                    operation.call_args.kwargs["reason"],
                    "Verified support request.",
                )
                self.assert_admin_context(operation, account, registry)

    def test_invitation_and_role_revocation_call_public_contracts(self):
        account, registry = self.authenticate_staff("security_admin")
        target_id = uuid4()
        cases = (
            (
                "admin:staff-invitation-revoke",
                "revoke_staff_invitation",
                "invitation_id",
            ),
            (
                "admin:role-revoke",
                "revoke_staff_role",
                "assignment_id",
            ),
        )
        for route, function, identifier_name in cases:
            with self.subTest(function=function), patch(
                f"open_marketplace.staff_admin.access_admin.access_public.{function}"
            ) as operation:
                response = self.csrf_post(
                    route,
                    {"reason": "Access removal approved."},
                    kwargs={identifier_name: target_id},
                    REMOTE_ADDR="198.51.100.17",
                )
                self.assertEqual(response.status_code, 303)
                self.assertEqual(operation.call_args.kwargs[identifier_name], target_id)
                self.assertEqual(
                    operation.call_args.kwargs["reason"],
                    "Access removal approved.",
                )
                self.assert_admin_context(operation, account, registry)

    def test_review_actions_call_seller_public_contracts(self):
        account, registry = self.authenticate_staff("seller_reviewer")
        application_id = uuid4()
        cases = (
            ("admin:seller-application-start-review", "start_seller_application_review", False),
            ("admin:seller-application-request-changes", "request_seller_application_changes", True),
            ("admin:seller-application-approve", "approve_seller_application", True),
            ("admin:seller-application-reject", "reject_seller_application", True),
        )
        for route, function, needs_reason in cases:
            with self.subTest(function=function), patch(
                f"open_marketplace.staff_admin.seller_admin.seller_public.{function}"
            ) as operation:
                data = {"reason": "Evidence checked."} if needs_reason else {}
                response = self.csrf_post(
                    route,
                    data,
                    kwargs={"application_id": application_id},
                    REMOTE_ADDR="198.51.100.17",
                )
                self.assertEqual(response.status_code, 303)
                self.assertEqual(operation.call_args.kwargs["application_id"], application_id)
                if needs_reason:
                    self.assertEqual(operation.call_args.kwargs["reason"], "Evidence checked.")
                self.assert_admin_context(operation, account, registry)

    def test_seller_admission_actions_call_public_contracts_with_reason(self):
        account, registry = self.authenticate_staff("security_admin")
        seller_id = uuid4()
        cases = (
            ("admin:seller-profile-suspend", "suspend_seller"),
            ("admin:seller-profile-restore", "restore_seller"),
            ("admin:seller-profile-revoke", "revoke_seller"),
        )
        for route, function in cases:
            with self.subTest(function=function), patch(
                f"open_marketplace.staff_admin.seller_admin.seller_public.{function}"
            ) as operation:
                response = self.csrf_post(
                    route,
                    {"reason": "Security decision."},
                    kwargs={"seller_id": seller_id},
                    REMOTE_ADDR="198.51.100.17",
                )
                self.assertEqual(response.status_code, 303)
                self.assertEqual(operation.call_args.kwargs["seller_id"], seller_id)
                self.assertEqual(operation.call_args.kwargs["reason"], "Security decision.")
                self.assert_admin_context(operation, account, registry)

    def test_audit_and_outbox_lists_delegate_authorization_to_public_queries(self):
        reviewer, reviewer_registry = self.authenticate_staff("seller_reviewer")
        with patch(
            "open_marketplace.staff_admin.audit_admin.audit_public.query_audit_entries",
            return_value=(),
        ) as audit_query:
            response = self.client.get(
                reverse("admin:audit-list"),
                {"action": "seller.application.approved"},
                REMOTE_ADDR="198.51.100.17",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(callable(audit_query.call_args.kwargs["authorize"]))
        self.assert_admin_context(audit_query, reviewer, reviewer_registry)

        self.reset_client()
        admin, admin_registry = self.authenticate_staff("security_admin")
        with patch(
            "open_marketplace.staff_admin.outbox_admin.outbox_public.query_manual_review_messages",
            return_value=(),
        ) as outbox_query:
            response = self.client.get(
                reverse("admin:outbox-list"),
                REMOTE_ADDR="198.51.100.17",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(callable(outbox_query.call_args.kwargs["authorize"]))
        self.assert_admin_context(outbox_query, admin, admin_registry)

    def test_manual_outbox_retry_calls_public_contract(self):
        account, registry = self.authenticate_staff("security_admin")
        message_id = uuid4()
        with patch(
            "open_marketplace.staff_admin.outbox_admin.outbox_public.retry_message_from_manual_review"
        ) as operation:
            response = self.csrf_post(
                "admin:outbox-retry",
                {"reason": "Delivery issue resolved."},
                kwargs={"message_id": message_id},
                REMOTE_ADDR="198.51.100.17",
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(operation.call_args.kwargs["message_id"], message_id)
        self.assertEqual(operation.call_args.kwargs["reason"], "Delivery issue resolved.")
        self.assertTrue(callable(operation.call_args.kwargs["authorize"]))
        self.assert_admin_context(operation, account, registry)

    def test_mutations_are_post_only_and_csrf_protected(self):
        self.authenticate_staff("security_admin")
        target = uuid4()
        routes = (
            ("admin:staff-invitation-create", None),
            ("admin:account-block", {"account_id": target}),
            ("admin:seller-profile-suspend", {"seller_id": target}),
            ("admin:outbox-retry", {"message_id": target}),
        )
        for name, kwargs in routes:
            url = reverse(name, kwargs=kwargs)
            with self.subTest(name=name, method="GET"):
                self.assertEqual(self.client.get(url).status_code, 405)
            with self.subTest(name=name, method="POST without CSRF"):
                self.assertEqual(self.client.post(url, {"reason": "x"}).status_code, 403)

    def test_expected_domain_error_is_bounded_and_does_not_leak_detail(self):
        self.authenticate_staff("security_admin")
        sentinel = "SENTINEL_INTERNAL_DOMAIN_DETAIL"
        with patch(
            "open_marketplace.staff_admin.identity_admin.identity_public.block_account",
            side_effect=InputRejected(sentinel),
        ):
            response = self.csrf_post(
                "admin:account-block",
                {"reason": "Verified request."},
                kwargs={"account_id": uuid4()},
            )
        self.assertIn(response.status_code, (200, 303))
        if response.status_code == 303:
            response = self.client.get(response["Location"])
        self.assertNotContains(response, sentinel)
        self.assertLess(len(response.content), 16_384)
