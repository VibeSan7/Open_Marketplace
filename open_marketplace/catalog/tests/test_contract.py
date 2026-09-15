from importlib import import_module

from django.test import SimpleTestCase


class CatalogContractTests(SimpleTestCase):
    def test_catalog_exposes_commands_instead_of_orm_models(self):
        try:
            public = import_module("open_marketplace.catalog.public")
        except ImportError:
            self.fail("The catalog public command interface is missing.")
        for name in (
            "set_participant", "create_category", "update_category", "list_categories",
            "create_product", "get_own_product", "list_own_products", "save_product_draft",
            "add_variant", "save_variant_draft", "set_offer", "publish_product",
            "withdraw_variant", "create_location", "upload_photo", "get_photo",
            "get_product", "search_catalog", "set_product_block", "set_variant_block",
            "suggest_change", "list_suggestions", "request_match", "review_match",
        ):
            with self.subTest(operation=name):
                self.assertTrue(callable(getattr(public, name, None)), name)
        for name in ("Product", "Variant", "Stock", "Participant", "Category", "Photo"):
            self.assertFalse(hasattr(public, name), f"Do not expose ORM model {name}.")
