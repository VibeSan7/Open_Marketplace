from importlib import import_module

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, PermissionDenied


class CatalogSearchTests(CatalogTestCase):
    def setUp(self):
        public = import_module("open_marketplace.catalog.public")
        self.assertTrue(callable(getattr(public, "search_catalog", None)), "Catalog search has not been implemented.")
        super().setUp()

    def search(self, query="", **kwargs):
        return self.catalog.search_catalog(query=query, context=self.buyer_context, **kwargs)

    def second_variant(self, product, photo, *, color, size, price, stock="1"):
        variant = self.catalog.add_variant(product_id=product, expected_version=self.revision(product), context=self.seller_context,
            data={"label": f"{color} {size}", "attributes": {"color": color, "size": size}, "photo_ids": [str(photo)]})
        self.catalog.set_offer(variant_id=variant, field="price", value=price, expected_version=0, context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="stock", value=stock, expected_version=0, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        return variant

    def test_only_one_card_is_returned_and_price_uses_matching_in_stock_variant(self):
        product, variant, photo = self.product(price="100")
        other = self.second_variant(product, photo, color="Синий", size="M", price="30")
        page = self.search(filters={"color": ["Красный"]})
        self.assertEqual([row["id"] for row in page["items"]], [str(product)])
        self.assertEqual(str(page["items"][0]["price"]), "100.00")
        self.assertEqual(page["items"][0]["variant_ids"], [str(variant)])

    def test_filters_cannot_match_different_variants(self):
        product, variant, photo = self.product()
        self.second_variant(product, photo, color="Синий", size="M", price="30")
        self.assertEqual(self.search(filters={"color": ["Красный"], "size": ["M"]})["items"], [])
        self.assertEqual(self.search(filters={"color": ["Красный", "Синий"], "size": ["M"]})["items"][0]["id"], str(product))

    def test_unavailable_values_are_visible_but_not_selectable_and_selection_is_preserved(self):
        self.product()
        page = self.search(filters={"size": ["M"]})
        self.assertEqual(page["items"], [])
        option = next(value for facet in page["facets"] if facet["key"] == "size" for value in facet["values"] if value["value"] == "M")
        self.assertTrue(option["selected"])
        self.assertFalse(option["available"])

    def test_description_and_public_characteristics_are_searchable(self):
        product, variant, photo = self.product()
        self.assertEqual(self.search("капюшоном")["items"][0]["id"], str(product))
        self.assertEqual(self.search("Красный")["items"][0]["id"], str(product))

    def test_exact_matches_precede_partial_and_typo_matches(self):
        exact, variant, photo = self.product(title="Куртка утеплённая")
        partial, variant, photo = self.product(title="Куртка", context=self.other_context)
        page = self.search("Куртка утеплённая")
        self.assertEqual(page["items"][0]["id"], str(exact))
        self.assertFalse(page["items"][0]["approximate"])
        other = next(row for row in page["items"] if row["id"] == str(partial))
        self.assertTrue(other["approximate"])
        typo = self.search("куркта")
        self.assertTrue(typo["items"])
        self.assertTrue(all(row["approximate"] for row in typo["items"]))
        self.assertEqual(typo["suggestion"], "куртка")

    def test_zero_stock_and_private_drafts_do_not_enter_search_or_suggestions(self):
        hidden, variant, photo = self.product(title="Секретныесапоги", publish=False)
        zero, variant, photo = self.product(stock="0", context=self.other_context)
        self.assertEqual(self.search()["items"], [])
        page = self.search("Секретныесапог")
        self.assertEqual(page["items"], [])
        self.assertIsNone(page["suggestion"])

    def test_incorrect_filter_is_not_silently_ignored_or_presented_as_no_results(self):
        self.product()
        for filters in ({"not-real": ["anything"]}, {"color": ["Несуществующий"]}, {"size": []}):
            with self.subTest(filters=filters):
                with self.assertRaises(InputRejected):
                    self.search(filters=filters)

    def test_free_and_mixed_price_labels_differ(self):
        product, variant, photo = self.product(price="0")
        self.assertEqual(self.search()["items"][0]["price_label"], "Бесплатно")
        self.second_variant(product, photo, color="Синий", size="M", price="10")
        self.assertEqual(self.search()["items"][0]["price_label"], "от 0,00 ₽")

    def test_participant_revocation_applies_to_search_too(self):
        self.product()
        self.catalog.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)
        with self.assertRaises(PermissionDenied):
            self.search()

    def test_keyset_pagination_has_no_duplicates_and_reports_real_total(self):
        expected = set()
        for index in range(23):
            product, variant, photo = self.product(title=f"Товар {index:03d}")
            expected.add(str(product))
        first = self.search()
        second = self.search(cursor=first["next_cursor"])
        actual = [row["id"] for page in (first, second) for row in page["items"]]
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(first["total"], 23)
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(set(actual), expected)
        self.assertIsNone(second["next_cursor"])

    def test_cursor_is_bound_to_conditions_and_cannot_be_forged(self):
        with self.assertRaises(InputRejected):
            self.search(cursor="not-a-signed-cursor")

    def test_search_never_rewrites_the_user_query_to_a_suggestion(self):
        self.product()
        page = self.search("куркта", filters={"color": ["Красный"]})
        self.assertEqual(page["query"], "куркта")
        self.assertEqual(page["filters"], {"color": ["Красный"]})
