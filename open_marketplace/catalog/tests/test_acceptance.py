from decimal import Decimal

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, PermissionDenied


class CatalogAcceptanceTests(CatalogTestCase):
    def test_new_variant_and_content_publish_atomically_without_copying_stock(self):
        product, first, photo = self.product()
        second = self.catalog.add_variant(
            product_id=product, expected_version=self.revision(product), context=self.seller_context,
            data={"label": "Синий M", "attributes": {"color": "Синий", "size": "M"}, "photo_ids": [str(photo)]},
        )
        self.catalog.save_product_draft(product_id=product, expected_version=self.revision(product),
                                        data={"title": "Новое название"}, context=self.seller_context)
        self.catalog.set_offer(variant_id=second, field="stock", value="3", expected_version=0, context=self.seller_context)
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        old = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(old["title"], "Куртка")
        self.assertEqual([row["id"] for row in old["variants"]], [str(first)])
        self.catalog.set_offer(variant_id=second, field="price", value="10", expected_version=0, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        new = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(new["title"], "Новое название")
        self.assertEqual({row["id"] for row in new["variants"]}, {str(first), str(second)})
        own = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.assertEqual({row["id"]: row["stocks"][0]["quantity"] for row in own["variants"]},
                         {str(first): Decimal("2"), str(second): Decimal("3")})

    def test_new_required_attribute_preserves_old_publication_and_numeric_edits(self):
        product, variant, photo = self.product()
        category = self.catalog.list_categories(context=self.staff_context)[0]
        definitions = category["attributes"] + [{"key": "material", "label": "Материал", "required": True, "values": []}]
        self.catalog.update_category(category_id=self.category_id, name=category["name"], attributes=definitions,
                                     active=True, expected_version=category["version"], context=self.staff_context)
        self.assertEqual(self.catalog.search_catalog(context=self.buyer_context)["total"], 1)
        self.catalog.set_offer(variant_id=variant, field="price", value="99", expected_version=1, context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="stock", value="4", expected_version=1, context=self.seller_context)
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["title"], "Куртка")
        self.catalog.save_product_draft(product_id=product, expected_version=self.revision(product),
                                        data={"attributes": {"material": "Хлопок"}}, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["selected_variant"]["price"], Decimal("99"))

    def test_explicit_restore_uses_same_variant_and_current_price_and_stock(self):
        product, variant, photo = self.product()
        self.catalog.withdraw_variant(variant_id=variant, context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="price", value="42", expected_version=1, context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="stock", value="5", expected_version=1, context=self.seller_context)
        self.catalog.save_variant_draft(product_id=product, variant_id=variant, expected_version=self.revision(product),
            data={"label": "Красный S", "attributes": {"color": "Красный", "size": "S"}, "photo_ids": [str(photo)], "restore": True},
            context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        view = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(view["selected_variant_id"], str(variant))
        self.assertEqual(view["selected_variant"]["price"], Decimal("42"))
        own = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.assertEqual(len(own["variants"]), 1)
        self.assertEqual(own["variants"][0]["stocks"][0]["quantity"], Decimal("5"))

    def test_direct_search_and_explicit_links_select_current_appropriate_variant(self):
        product, first, photo = self.product(price="100")
        second = self.catalog.add_variant(product_id=product, expected_version=self.revision(product), context=self.seller_context,
            data={"label": "Синий M", "attributes": {"color": "Синий", "size": "M"}, "photo_ids": [str(photo)]})
        self.catalog.set_offer(variant_id=second, field="price", value="20", expected_version=0, context=self.seller_context)
        self.catalog.set_offer(variant_id=second, field="stock", value="1", expected_version=0, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["selected_variant_id"], str(second))
        filtered = self.catalog.get_product(product_id=product, from_search=True, filters={"color": ["Красный"]}, context=self.buyer_context)
        self.assertEqual(filtered["selected_variant_id"], str(first))
        self.assertEqual(self.catalog.get_product(product_id=product, variant_id=first, context=self.buyer_context)["selected_variant_id"], str(first))
        self.catalog.set_offer(variant_id=first, field="price", value="0", expected_version=1, context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["selected_variant_id"], str(first))
        self.catalog.withdraw_variant(variant_id=first, context=self.seller_context)
        hidden = self.catalog.get_product(product_id=product, variant_id=first, context=self.buyer_context)
        self.assertIsNone(hidden["selected_variant_id"])
        self.assertNotIn(str(first), [row["id"] for row in hidden["variants"]])
        missing_match = self.catalog.get_product(product_id=product, from_search=True, filters={"color": ["Красный"]}, context=self.buyer_context)
        self.assertIsNone(missing_match["selected_variant_id"])

    def test_new_photo_and_cover_remain_private_until_content_is_published(self):
        product, variant, original = self.product()
        replacement = self.catalog.upload_photo(product_id=product, uploaded_file=self.image(), attested=True, context=self.seller_context)
        self.catalog.save_product_draft(product_id=product, expected_version=self.revision(product),
                                        data={"cover_id": str(replacement)}, context=self.seller_context)
        self.catalog.save_variant_draft(product_id=product, variant_id=variant, expected_version=self.revision(product), context=self.seller_context,
            data={"label": "Красный S", "attributes": {"color": "Красный", "size": "S"}, "photo_ids": [str(replacement)]})
        view = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(view["cover_id"], str(original))
        self.assertEqual(view["selected_variant"]["photo_ids"], [str(original)])
        with self.assertRaises(PermissionDenied):
            self.catalog.get_photo(photo_id=replacement, context=self.buyer_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        view = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(view["cover_id"], str(replacement))
        self.assertEqual(view["selected_variant"]["photo_ids"], [str(replacement)])

    def test_digital_draft_never_appears_in_search_or_direct_access(self):
        product, variant, photo = self.product(kind="digital", price="0", publish=False)
        self.assertEqual(self.catalog.search_catalog(context=self.buyer_context)["items"], [])
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(self.catalog.get_own_product(product_id=product, context=self.seller_context)["variants"][0]["price"], Decimal("0"))
