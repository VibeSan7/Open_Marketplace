from datetime import timedelta

from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from open_marketplace.staff_admin.tests.helpers import StaffAdminTestCase


class StaffAdminSitePermissionTests(StaffAdminTestCase):
    def test_posting_default_admin_login_fields_cannot_create_a_registry_session(self):
        AccountSession = apps.get_model("identity", "AccountSession")
        self.client.get(reverse("login"))
        token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            "/admin/login/",
            {
                "csrfmiddlewaretoken": token,
                "username": "admin@example.com",
                "password": "not-a-real-password",
            },
        )

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response["Location"].startswith(reverse("login")))
        self.assertEqual(AccountSession.objects.count(), 0)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)

    def test_anonymous_admin_access_uses_the_shared_login_route(self):
        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/login/?next=/admin/")

        login = self.client.get(response["Location"])
        self.assertEqual(login.status_code, 303)
        self.assertEqual(login["Location"], f"{reverse('login')}?next=%2Fadmin%2F")

    def test_admin_auth_routes_cannot_expose_default_django_auth_forms(self):
        external = self.client.get("/admin/login/?next=//evil.example/steal")
        self.assertEqual(external.status_code, 303)
        self.assertEqual(external["Location"], f"{reverse('login')}?next=%2Fadmin%2F")
        self.assertNotIn(b"username", external.content)
        self.assertNotIn(b"password", external.content)

        self.authenticate_staff("security_admin")
        for path in ("/admin/password_change/", "/admin/password_change/done/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response["Location"], reverse("password-change"))
                self.assertNotIn(b"old_password", response.content)
                self.assertNotIn(b"new_password1", response.content)

    def test_admin_logout_delegates_post_to_the_shared_logout_route(self):
        _, registry = self.authenticate_staff("security_admin")

        get_response = self.client.get("/admin/logout/")
        missing_csrf = self.client.post("/admin/logout/")
        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(missing_csrf.status_code, 403)
        registry.refresh_from_db()
        self.assertIsNone(registry.revoked_at)

        token = self.csrf_token()
        response = self.client.post(
            "/admin/logout/",
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response["Location"], reverse("logout"))
        registry.refresh_from_db()
        self.assertIsNone(registry.revoked_at)

        completed = self.client.post(
            response["Location"],
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(completed.status_code, 303)
        self.assertEqual(completed["Location"], reverse("login"))
        registry.refresh_from_db()
        self.assertIsNotNone(registry.revoked_at)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)

    def test_admin_logout_still_delegates_after_role_revocation(self):
        account, registry = self.authenticate_staff("security_admin")
        token = self.csrf_token()
        RoleAssignment = apps.get_model("access", "RoleAssignment")
        RoleAssignment.objects.filter(account_id=account.id).update(
            state="revoked",
            revoked_at=timezone.now(),
            revoked_by_id=account.id,
            revoked_reason="Access removed.",
        )

        response = self.client.post(
            "/admin/logout/",
            {"csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response["Location"], reverse("logout"))
        registry.refresh_from_db()
        self.assertIsNone(registry.revoked_at)

        completed = self.client.post(
            response["Location"],
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(completed.status_code, 303)
        registry.refresh_from_db()
        self.assertIsNotNone(registry.revoked_at)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)

    def test_posting_default_admin_password_fields_cannot_change_credentials(self):
        account, _ = self.authenticate_staff("security_admin")
        original_password_hash = account.password
        token = self.csrf_token()

        response = self.client.post(
            "/admin/password_change/",
            {
                "csrfmiddlewaretoken": token,
                "old_password": self.password,
                "new_password1": "Unexpected Password 44!",
                "new_password2": "Unexpected Password 44!",
            },
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("password-change"))
        account.refresh_from_db()
        self.assertEqual(account.password, original_password_hash)

    def test_only_fully_eligible_service_accounts_enter_the_site(self):
        cases = (
            ({"roles": ("seller_reviewer",)}, 200, "reviewer"),
            ({"roles": ("security_admin",)}, 200, "security admin"),
            ({"roles": ("seller_reviewer", "security_admin")}, 200, "dual role"),
            ({"roles": ()}, 302, "no role"),
            ({"roles": ("seller_reviewer",), "roles_active": False}, 302, "revoked role"),
            ({"roles": ("seller_reviewer",), "with_totp": False}, 302, "missing TOTP"),
            (
                {"roles": ("security_admin",), "state": "blocked"},
                302,
                "blocked account",
            ),
            (
                {
                    "roles": ("security_admin",),
                    "state": "pending_email_verification",
                    "verified": False,
                },
                302,
                "pending account",
            ),
            (
                {"roles": ("seller_reviewer",), "kind": "ordinary"},
                302,
                "ordinary account",
            ),
        )
        for values, expected_status, label in cases:
            with self.subTest(label=label):
                self.reset_client()
                roles = values.pop("roles")
                self.authenticate_staff(*roles, **values)
                response = self.client.get("/admin/")
                self.assertEqual(response.status_code, expected_status)

    def test_reviewer_and_security_admin_have_exact_page_separation(self):
        self.authenticate_staff("seller_reviewer")
        for name in ("admin:seller-application-list", "admin:audit-list"):
            with self.subTest(role="reviewer", name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        for name in (
            "admin:staff-invitation-list",
            "admin:account-list",
            "admin:seller-profile-list",
            "admin:outbox-list",
        ):
            with self.subTest(role="reviewer", name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

        self.reset_client()
        self.authenticate_staff("security_admin")
        for name in (
            "admin:staff-invitation-list",
            "admin:account-list",
            "admin:seller-profile-list",
            "admin:audit-list",
            "admin:outbox-list",
        ):
            with self.subTest(role="security_admin", name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:seller-application-list")).status_code,
            403,
        )

    def test_reviewer_and_security_admin_have_exact_action_separation(self):
        target = "00000000-0000-0000-0000-000000000001"
        self.authenticate_staff("seller_reviewer")
        reviewer_denied = (
            ("admin:staff-invitation-create", None, {"email": "staff@example.com", "role": "security_admin"}),
            ("admin:staff-invitation-revoke", {"invitation_id": target}, {"reason": "Denied."}),
            ("admin:role-revoke", {"assignment_id": target}, {"reason": "Denied."}),
            ("admin:account-block", {"account_id": target}, {"reason": "Denied."}),
            ("admin:account-recover-totp", {"account_id": target}, {"reason": "Denied."}),
            ("admin:seller-profile-suspend", {"seller_id": target}, {"reason": "Denied."}),
            ("admin:outbox-retry", {"message_id": target}, {"reason": "Denied."}),
        )
        for name, kwargs, data in reviewer_denied:
            with self.subTest(role="reviewer", name=name):
                self.assertEqual(self.csrf_post(name, data, kwargs=kwargs).status_code, 403)

        self.reset_client()
        self.authenticate_staff("security_admin")
        security_admin_denied = (
            ("admin:seller-application-start-review", {}),
            ("admin:seller-application-approve", {"reason": "Denied."}),
        )
        for name, data in security_admin_denied:
            with self.subTest(role="security_admin", name=name):
                self.assertEqual(
                    self.csrf_post(
                        name,
                        data,
                        kwargs={"application_id": target},
                    ).status_code,
                    403,
                )

    def test_account_detail_links_to_role_revocation_flow(self):
        account, _ = self.authenticate_staff("security_admin")
        RoleAssignment = apps.get_model("access", "RoleAssignment")
        assignment = RoleAssignment.objects.get(account_id=account.id)

        detail = self.client.get(
            reverse("admin:account-detail", kwargs={"account_id": account.id})
        )
        role_list_url = reverse("admin:role-list", kwargs={"account_id": account.id})
        self.assertContains(detail, role_list_url)

        role_list = self.client.get(role_list_url)
        self.assertContains(
            role_list,
            reverse("admin:role-revoke", kwargs={"assignment_id": assignment.id}),
        )

    def test_sensitive_operation_is_denied_after_reauthentication_expires(self):
        self.authenticate_staff(
            "security_admin",
            reauthenticated_at=timezone.now() - timedelta(minutes=16),
        )

        response = self.csrf_post(
            "admin:staff-invitation-create",
            {"email": "reviewer@example.com", "role": "seller_reviewer"},
        )

        self.assertEqual(response.status_code, 403)

    def test_fresh_reauthentication_allows_sensitive_adapter_to_reach_public_contract(self):
        self.authenticate_staff("security_admin")

        response = self.csrf_post(
            "admin:staff-invitation-create",
            {"email": "reviewer@example.com", "role": "seller_reviewer"},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("admin:staff-invitation-list"))
