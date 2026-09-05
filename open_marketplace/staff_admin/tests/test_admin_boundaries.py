import ast
from importlib import import_module
from pathlib import Path

from django.apps import apps
from django.contrib import admin
from django.urls import resolve, reverse

from open_marketplace.staff_admin.tests.helpers import StaffAdminTestCase


class StaffAdminBoundaryTests(StaffAdminTestCase):
    production_files = (
        "site.py",
        "identity_admin.py",
        "access_admin.py",
        "seller_admin.py",
        "audit_admin.py",
        "outbox_admin.py",
    )

    def production_root(self):
        return Path(__file__).resolve().parents[1]

    def test_all_planned_adapter_files_and_templates_exist(self):
        root = self.production_root()
        for filename in self.production_files:
            with self.subTest(filename=filename):
                self.assertTrue((root / filename).is_file())

        template_root = root.parent / "templates" / "admin"
        self.assertTrue(template_root.is_dir())
        self.assertTrue(any(template_root.glob("*.html")))

    def test_staff_admin_imports_only_public_module_contracts(self):
        root = self.production_root()
        forbidden_parts = {"models", "application", "managers", "repositories"}
        for filename in self.production_files:
            source_path = root / filename
            self.assertTrue(source_path.is_file(), filename)
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=filename)
            for node in ast.walk(tree):
                imported = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                for module in imported:
                    if not module.startswith("open_marketplace."):
                        continue
                    self.assertFalse(
                        forbidden_parts.intersection(module.split(".")),
                        f"{filename} imports protected module {module}",
                    )
                    if module.startswith(
                        (
                            "open_marketplace.identity.",
                            "open_marketplace.access.",
                            "open_marketplace.seller_onboarding.",
                            "open_marketplace.audit.",
                            "open_marketplace.outbox.",
                        )
                    ):
                        self.assertTrue(
                            module.endswith(".public"),
                            f"{filename} must use a public contract: {module}",
                        )

    def test_staff_admin_has_no_direct_orm_write_or_query_path(self):
        root = self.production_root()
        forbidden_fragments = (
            ".objects",
            ".save(",
            ".delete(",
            "QuerySet",
            "apps.get_model",
        )
        for filename in self.production_files:
            source_path = root / filename
            self.assertTrue(source_path.is_file(), filename)
            source = source_path.read_text(encoding="utf-8")
            for fragment in forbidden_fragments:
                with self.subTest(filename=filename, fragment=fragment):
                    self.assertNotIn(fragment, source)

    def test_custom_site_is_mounted_and_has_no_registered_models(self):
        site_module = import_module("open_marketplace.staff_admin.site")
        custom_site = site_module.staff_admin_site
        match = resolve("/admin/")

        self.assertIs(match.func.admin_site, custom_site)
        self.assertIsNot(custom_site, admin.site)
        self.assertEqual(custom_site._registry, {})
        for model in apps.get_models():
            self.assertNotIn(model, custom_site._registry)

    def test_all_explicit_admin_routes_reverse(self):
        target = "00000000-0000-0000-0000-000000000001"
        routes = (
            ("admin:index", None),
            ("admin:login", None),
            ("admin:logout", None),
            ("admin:password_change", None),
            ("admin:password_change_done", None),
            ("admin:seller-application-list", None),
            ("admin:seller-application-detail", {"application_id": target}),
            ("admin:seller-application-start-review", {"application_id": target}),
            ("admin:seller-application-request-changes", {"application_id": target}),
            ("admin:seller-application-approve", {"application_id": target}),
            ("admin:seller-application-reject", {"application_id": target}),
            ("admin:staff-invitation-list", None),
            ("admin:staff-invitation-create", None),
            ("admin:staff-invitation-revoke", {"invitation_id": target}),
            ("admin:role-list", {"account_id": target}),
            ("admin:role-revoke", {"assignment_id": target}),
            ("admin:account-list", None),
            ("admin:account-detail", {"account_id": target}),
            ("admin:account-block", {"account_id": target}),
            ("admin:account-unblock", {"account_id": target}),
            ("admin:account-recover-totp", {"account_id": target}),
            ("admin:seller-profile-list", None),
            ("admin:seller-profile-detail", {"seller_id": target}),
            ("admin:seller-profile-suspend", {"seller_id": target}),
            ("admin:seller-profile-restore", {"seller_id": target}),
            ("admin:seller-profile-revoke", {"seller_id": target}),
            ("admin:audit-list", None),
            ("admin:outbox-list", None),
            ("admin:outbox-retry", {"message_id": target}),
        )
        for name, kwargs in routes:
            with self.subTest(name=name):
                self.assertTrue(reverse(name, kwargs=kwargs).startswith("/admin/"))

    def test_protected_model_crud_urls_do_not_exist(self):
        self.authenticate_staff("security_admin")
        for path in (
            "/admin/identity/account/",
            "/admin/access/roleassignment/",
            "/admin/seller_onboarding/sellerprofile/",
            "/admin/audit/auditentry/",
            "/admin/outbox/outboxmessage/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
