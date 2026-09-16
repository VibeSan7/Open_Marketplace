from decimal import Decimal
from uuid import uuid4

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, PermissionDenied


class SavedProductsTests(CatalogTestCase):
    def save(self, product_id, saved=True, context=None):
        operation = getattr(self.catalog, "set_saved_product", None)
        self.assertTrue(callable(operation), "Saving catalogue products is not implemented")
        return operation(product_id=product_id, saved=saved, context=context or self.buyer_context)

    def saved(self, context=None):
        operation = getattr(self.catalog, "list_saved_products", None)
        self.assertTrue(callable(operation), "Saved catalogue list is not implemented")
        return operation(context=context or self.buyer_context)

    def test_save_and_remove_are_idempotent_and_personal(self):
        product, _, _ = self.product()
        self.save(product)
        self.save(product)
        self.assertEqual([item["id"] for item in self.saved()], [str(product)])
        self.assertEqual(self.saved(self.other_context), [])
        self.save(product, False, self.other_context)
        self.assertEqual(len(self.saved()), 1)
        self.save(product, False)
        self.save(product, False)
        self.assertEqual(self.saved(), [])

    def test_saved_content_uses_current_visible_title_and_price(self):
        product, variant, _ = self.product()
        self.save(product)
        data = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.catalog.save_product_draft(product_id=product, expected_version=data["draft_version"],
            data={**data["draft"], "title": "Новое опубликованное название"}, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="price", value="350", expected_version=1, context=self.seller_context)
        item = self.saved()[0]
        self.assertEqual(item["title"], "Новое опубликованное название")
        self.assertEqual(item["price"], Decimal("350.00"))
        self.assertTrue(item["in_stock"])

    def test_unavailable_stock_keeps_visible_saved_card(self):
        product, _, _ = self.product(price="0", stock="0")
        self.save(product)
        item = self.saved()[0]
        self.assertEqual(item["price_label"], "Бесплатно")
        self.assertFalse(item["in_stock"])

    def test_withdrawn_card_disappears_and_can_still_be_removed(self):
        product, _, _ = self.product()
        self.save(product)
        self.catalog.withdraw_product(product_id=product, context=self.seller_context)
        self.assertEqual(self.saved(), [])
        self.save(product, False)
        self.assertEqual(self.saved(), [])

    def test_seller_admission_revocation_hides_saved_content(self):
        product, _, _ = self.product()
        self.save(product)
        self.catalog.set_participant(account_id=self.seller_context.actor_account_id, allowed=False, context=self.staff_context)
        self.assertEqual(self.saved(), [])
        with self.assertRaises(PermissionDenied):
            self.save(product)
        self.save(product, False)

    def test_viewer_revocation_denies_all_saved_operations(self):
        product, _, _ = self.product()
        self.save(product)
        self.catalog.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)
        with self.assertRaises(PermissionDenied):
            self.saved()
        with self.assertRaises(PermissionDenied):
            self.save(product, False)

    def test_hidden_and_unknown_products_cannot_be_added(self):
        product, _, _ = self.product(publish=False)
        errors = []
        for target in (product, uuid4()):
            with self.assertRaises(PermissionDenied) as error:
                self.save(target)
            errors.append(str(error.exception))
        self.assertEqual(errors[0], errors[1])

    def test_saved_argument_is_an_explicit_boolean(self):
        product, _, _ = self.product()
        for value in ("true", "false", 1, None):
            with self.subTest(value=value):
                with self.assertRaises(InputRejected):
                    self.save(product, value)
        self.assertEqual(self.saved(), [])

    def test_product_saved_flag_is_scoped_to_current_viewer(self):
        product, _, _ = self.product()
        self.save(product)
        self.assertTrue(self.catalog.get_product(product_id=product, context=self.buyer_context)["is_saved"])
        self.assertFalse(self.catalog.get_product(product_id=product, context=self.other_context)["is_saved"])
