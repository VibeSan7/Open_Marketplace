from importlib import import_module

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied


class CommonCardTests(CatalogTestCase):
    def setUp(self):
        public = import_module("open_marketplace.catalog.public")
        self.assertTrue(callable(getattr(public, "request_match", None)), "Common-card matching has not been implemented.")
        super().setUp()

    def common(self, *, unit="pc"):
        product = self.catalog.create_product(kind="common", unit=unit, context=self.staff_context)
        self.catalog.save_product_draft(product_id=product, expected_version=self.revision(product, self.staff_context), context=self.staff_context,
            data={"title": "Куртка общая", "description": "Проверенная общая карточка зимней куртки.", "category_id": str(self.category_id), "attributes": {}})
        photo = self.catalog.upload_photo(product_id=product, uploaded_file=self.image(), attested=True, context=self.staff_context)
        variant = self.catalog.add_variant(product_id=product, expected_version=self.revision(product, self.staff_context), context=self.staff_context,
            data={"label": "Красный S", "attributes": {"color": "Красный", "size": "S"}, "photo_ids": [str(photo)]})
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product, self.staff_context), context=self.staff_context)
        return product, variant, photo

    def match(self, variant, common_variant, *, context=None):
        request = self.catalog.request_match(source_variant_id=variant, target_variant_id=common_variant, reason="Совпадают модель, характеристики, комплектация и состояние.", context=context or self.seller_context)
        self.catalog.review_match(request_id=request, approve=True, identity_confirmed=True, reason="Идентичность проверена.", context=self.staff_context)
        return request

    def test_pending_match_does_not_hide_own_publication_or_create_common_offer(self):
        product, variant, photo = self.product()
        common, target, common_photo = self.common()
        request = self.catalog.request_match(source_variant_id=variant, target_variant_id=target, reason="Идентичный товар", context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["id"], str(product))
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=common, context=self.buyer_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.review_match(request_id=request, approve=True, identity_confirmed=True, reason="Проверено", context=self.seller_context)

    def test_verified_offers_use_current_prices_and_do_not_sum_quantities(self):
        first, first_variant, photo = self.product(price="100", stock="2")
        second, second_variant, photo = self.product(price="80", stock="99", context=self.other_context)
        common, target, common_photo = self.common()
        self.match(first_variant, target)
        self.match(second_variant, target, context=self.other_context)
        view = self.catalog.get_product(product_id=common, context=self.buyer_context)
        self.assertEqual([str(offer["price"]) for offer in view["variants"][0]["offers"]], ["80.00", "100.00"])
        self.assertEqual(view["variants"][0]["photo_ids"], [str(common_photo)])
        self.assertNotIn("quantity", str(view))
        self.catalog.set_offer(variant_id=first_variant, field="price", value="50", expected_version=1, context=self.seller_context)
        self.assertEqual(str(self.catalog.get_product(product_id=common, context=self.buyer_context)["variants"][0]["price"]), "50.00")

    def test_common_content_cannot_be_edited_by_seller(self):
        common, target, photo = self.common()
        with self.assertRaises(PermissionDenied):
            self.catalog.save_product_draft(product_id=common, expected_version=0, data={"title": "Подмена"}, context=self.seller_context)
        suggestion = self.catalog.suggest_change(kind="common", target_id=common, text="Проверьте описание модели.", context=self.seller_context)
        self.assertTrue(suggestion)
        self.assertEqual(self.catalog.get_own_product(product_id=common, context=self.staff_context)["draft"]["title"], "Куртка общая")

    def test_common_published_unit_cannot_change_in_an_unpublished_draft(self):
        common, variant, photo = self.common()
        with self.assertRaises(InputRejected):
            self.catalog.save_product_draft(product_id=common, expected_version=self.revision(common, self.staff_context), data={"unit": "kg"}, context=self.staff_context)
        self.assertEqual(self.catalog.get_own_product(product_id=common, context=self.staff_context)["unit"], "pc")

    def test_units_must_match_without_relabeling(self):
        product, variant, photo = self.product(unit="kg")
        common, target, common_photo = self.common(unit="pc")
        with self.assertRaises(InputRejected):
            self.catalog.request_match(source_variant_id=variant, target_variant_id=target, reason="Проверить", context=self.seller_context)

    def test_changed_content_requires_new_staff_confirmation(self):
        product, variant, photo = self.product()
        common, target, common_photo = self.common()
        request = self.catalog.request_match(source_variant_id=variant, target_variant_id=target, reason="Проверить", context=self.seller_context)
        self.catalog.save_product_draft(product_id=product, expected_version=self.revision(product), data={"title": "Другая модель"}, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        with self.assertRaises(ConcurrentConflict):
            self.catalog.review_match(request_id=request, approve=True, identity_confirmed=True, reason="Проверено", context=self.staff_context)

    def test_blocked_or_withdrawn_offer_disappears_from_common_card(self):
        product, variant, photo = self.product()
        common, target, common_photo = self.common()
        self.match(variant, target)
        self.catalog.withdraw_variant(variant_id=variant, context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=common, context=self.buyer_context)
