from uuid import uuid4

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import PermissionDenied


class ProductReadinessTests(CatalogTestCase):
    def readiness(self, product_id, context=None):
        operation = getattr(self.catalog, "get_publication_readiness", None)
        self.assertTrue(callable(operation), "Catalogue publication readiness is missing")
        return operation(product_id=product_id, context=context or self.seller_context)

    def summary(self, product_id):
        return next(row for row in self.catalog.list_own_products(context=self.seller_context)
                    if row["id"] == str(product_id))

    def test_empty_draft_has_guidance_without_mutation(self):
        product_id = self.catalog.create_product(kind="physical", unit="pc", context=self.seller_context)
        before = self.catalog.get_own_product(product_id=product_id, context=self.seller_context)

        result = self.readiness(product_id)

        self.assertFalse(result["ready"])
        self.assertTrue(result["issues"])
        self.assertFalse(result["can_view_published"])
        self.assertFalse(any(row["complete"] for row in result["checks"]))
        self.assertEqual(before, self.catalog.get_own_product(product_id=product_id, context=self.seller_context))
        self.assertEqual(self.summary(product_id)["status_label"], "Черновик")

    def test_zero_price_and_zero_stock_are_complete_not_missing(self):
        product_id, _, _ = self.product(price="0", stock="0", publish=False)

        result = self.readiness(product_id)

        self.assertTrue(result["ready"])
        self.assertEqual(result["issues"], [])
        self.assertTrue(all(row["complete"] for row in result["checks"]))
        self.assertFalse(result["can_view_published"])
        self.assertEqual(self.summary(product_id)["price_label"], "Бесплатно")
        self.assertEqual(self.summary(product_id)["availability_label"], "Нет в наличии")

    def test_published_product_reports_visible_state_without_draft_changes(self):
        product_id, _, _ = self.product()

        result = self.readiness(product_id)
        row = self.summary(product_id)

        self.assertTrue(result["ready"])
        self.assertTrue(result["can_view_published"])
        self.assertFalse(result["has_unpublished_changes"])
        self.assertEqual(row["status_label"], "Опубликована")
        self.assertEqual(row["kind_label"], "Физический товар")
        self.assertEqual(row["availability_label"], "В наличии")

    def test_changed_draft_does_not_change_published_content(self):
        product_id, _, _ = self.product()
        before = self.catalog.get_own_product(product_id=product_id, context=self.seller_context)
        self.catalog.save_product_draft(product_id=product_id, expected_version=before["draft_version"],
            data={**before["draft"], "title": "Новое название в черновике"}, context=self.seller_context)

        result = self.readiness(product_id)

        self.assertTrue(result["has_unpublished_changes"])
        self.assertTrue(result["can_view_published"])
        public = self.catalog.get_product(product_id=product_id, context=self.buyer_context)
        self.assertNotEqual(public["title"], "Новое название в черновике")

    def test_new_required_attribute_blocks_readiness_not_existing_publication(self):
        product_id, _, _ = self.product()
        category = next(row for row in self.catalog.list_categories(context=self.staff_context)
                        if row["id"] == str(self.category_id))
        self.catalog.update_category(category_id=self.category_id, name=category["name"],
            attributes=[*category["attributes"], {"key": "fabric", "label": "Материал", "required": True,
                                                "values": ["Хлопок"]}],
            active=True, expected_version=category["version"], context=self.staff_context)

        result = self.readiness(product_id)

        self.assertFalse(result["ready"])
        self.assertIn("Материал", " ".join(result["issues"]))
        self.assertTrue(result["can_view_published"])

    def test_withdrawn_product_is_not_mislabeled_as_public(self):
        product_id, _, _ = self.product()
        self.catalog.withdraw_product(product_id=product_id, context=self.seller_context)

        result = self.readiness(product_id)

        self.assertFalse(result["ready"])
        self.assertFalse(result["can_view_published"])
        self.assertEqual(self.summary(product_id)["status_label"], "Снята с продажи")

    def test_digital_draft_cannot_report_publication_ready(self):
        product_id = self.catalog.create_product(kind="digital", unit="pc", context=self.seller_context)

        result = self.readiness(product_id)

        self.assertFalse(result["ready"])
        self.assertFalse(result["can_view_published"])
        self.assertIn("Цифровые", " ".join(result["issues"]))

    def test_foreign_and_unknown_product_are_equally_denied(self):
        product_id, _, _ = self.product()
        errors = []
        for target in (product_id, uuid4()):
            with self.assertRaises(PermissionDenied) as error:
                self.readiness(target, self.other_context)
            errors.append(str(error.exception))
        self.assertEqual(errors[0], errors[1])
