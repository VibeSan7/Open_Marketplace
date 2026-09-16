from io import StringIO
from tempfile import TemporaryDirectory

from django.apps import apps
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class DemoStorefrontSeedTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings = override_settings(CATALOG_MEDIA_ROOT=self.media.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def test_command_is_available(self):
        self.assertIn("seed_demo_storefront", get_commands())

    def test_every_bundled_photo_has_attribution_and_matches_manifest(self):
        import hashlib
        from open_marketplace.verification.demo_storefront import ASSETS, load_manifest

        manifest = load_manifest()
        self.assertEqual(len({item["key"] for item in manifest["products"]}), len(manifest["products"]))
        for item in manifest["products"]:
            with self.subTest(key=item["key"]):
                for field in ("author", "source", "license", "changes"):
                    self.assertTrue(item["credit"][field].strip())
                self.assertEqual(hashlib.sha256((ASSETS / item["image"]).read_bytes()).hexdigest(), item["image_sha256"])

    @override_settings(DEMO_CONTENT_ENABLED=False)
    def test_command_refuses_without_explicit_environment_opt_in(self):
        with self.assertRaises(CommandError) as raised:
            call_command("seed_demo_storefront", confirm_demo=True)
        self.assertIn("DEMO_CONTENT_ENABLED", str(raised.exception))
        self.assertEqual(apps.get_model("identity", "Account").objects.count(), 0)

    @override_settings(DEMO_CONTENT_ENABLED=True)
    def test_command_refuses_without_confirmation(self):
        with self.assertRaises(CommandError) as raised:
            call_command("seed_demo_storefront")
        self.assertIn("confirm-demo", str(raised.exception))

    @override_settings(DEMO_CONTENT_ENABLED=True)
    def test_seed_is_idempotent_has_photos_and_no_shared_login(self):
        from open_marketplace.verification.demo_storefront import load_manifest

        manifest = load_manifest()
        out = StringIO()
        call_command("seed_demo_storefront", confirm_demo=True, stdout=out)
        models = {name: apps.get_model(*label) for name, label in {
            "accounts": ("identity", "Account"), "products": ("catalog", "Product"),
            "photos": ("catalog", "Photo"), "variants": ("catalog", "Variant"),
            "sellers": ("seller_onboarding", "SellerProfile"),
        }.items()}
        before = {name: tuple(model.objects.values_list("pk", flat=True).order_by("pk")) for name, model in models.items()}
        self.assertEqual(len(before["products"]), len(manifest["products"]))
        self.assertEqual(len(before["sellers"]), len(manifest["sellers"]))
        self.assertTrue(all(not row.has_usable_password() for row in models["accounts"].objects.all()))
        self.assertEqual(models["accounts"].objects.filter(kind="service").count(), 0)
        self.assertEqual(models["products"].objects.filter(public_listing=True).count(), len(manifest["products"]))
        from pathlib import Path
        self.assertEqual(len(list(Path(self.media.name).glob("*.png"))), len(before["photos"]))
        call_command("seed_demo_storefront", confirm_demo=True, stdout=out)
        after = {name: tuple(model.objects.values_list("pk", flat=True).order_by("pk")) for name, model in models.items()}
        self.assertEqual(before, after)
        self.assertNotIn("@", out.getvalue())
        self.assertNotIn("password", out.getvalue().lower())


@override_settings(DEMO_CONTENT_ENABLED=True)
class DemoStorefrontIsolationTests(CatalogTestCase):
    def test_seed_preserves_existing_private_product_and_its_photo(self):
        from pathlib import Path

        product, _, _ = self.product(title="Существующий закрытый товар")
        before = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        photos = {path.name: path.read_bytes() for path in Path(self.media.name).glob("*.png")}
        call_command("seed_demo_storefront", confirm_demo=True, stdout=StringIO())
        self.assertEqual(self.catalog.get_own_product(product_id=product, context=self.seller_context), before)
        self.assertFalse(before["public_listing"])
        for name, data in photos.items():
            self.assertEqual((Path(self.media.name) / name).read_bytes(), data)

    def test_category_collision_rolls_back_synthetic_accounts_and_writes_no_images(self):
        from pathlib import Path
        from open_marketplace.verification.demo_storefront import load_manifest

        self.catalog.create_category(name=load_manifest()["categories"][0]["name"], attributes=[], context=self.staff_context)
        accounts = set(apps.get_model("identity", "Account").objects.values_list("id", flat=True))
        with self.assertRaises(CommandError):
            call_command("seed_demo_storefront", confirm_demo=True, stdout=StringIO())
        self.assertEqual(set(apps.get_model("identity", "Account").objects.values_list("id", flat=True)), accounts)
        self.assertEqual(list(Path(self.media.name).glob("*.png")), [])
