from importlib import import_module

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import PermissionDenied


class ManagementQueryTests(CatalogTestCase):
    def common(self, *, unit="pc"):
        return import_module("open_marketplace.catalog.tests.test_common_cards").CommonCardTests.common(self, unit=unit)

    def setUp(self):
        api = import_module("open_marketplace.catalog.public")
        for name in ("list_matching_targets", "list_moderation_cards", "list_participants"):
            self.assertTrue(callable(getattr(api, name, None)), f"Missing management list: {name}")
        super().setUp()

    def test_seller_can_choose_a_published_common_variant_before_first_offer(self):
        product, variant, photo = self.product()
        common, target, photo = self.common()
        rows = self.catalog.list_matching_targets(source_variant_id=variant, context=self.seller_context)
        self.assertEqual([row["id"] for row in rows], [str(target)])
        self.assertIn("Куртка общая", rows[0]["title"])
        with self.assertRaises(PermissionDenied):
            self.catalog.list_matching_targets(source_variant_id=variant, context=self.other_context)

    def test_moderation_lists_published_blocked_content_not_private_drafts(self):
        product, variant, photo = self.product()
        draft, draft_variant, photo = self.product(title="Личный черновик", publish=False)
        self.catalog.set_product_block(product_id=product, blocked=True, reason="Проверка", context=self.staff_context)
        rows = self.catalog.list_moderation_cards(context=self.staff_context)
        self.assertEqual([row["id"] for row in rows], [str(product)])
        self.assertNotIn("Личный черновик", str(rows))
        with self.assertRaises(PermissionDenied):
            self.catalog.list_moderation_cards(context=self.buyer_context)

    def test_participant_emails_are_staff_only(self):
        rows = self.catalog.list_participants(context=self.staff_context)
        self.assertIn(self.buyer.email, [row["email"] for row in rows])
        with self.assertRaises(PermissionDenied):
            self.catalog.list_participants(context=self.seller_context)
