from decimal import Decimal
from inspect import signature
from unittest.mock import patch

from open_marketplace.catalog.tests import test_common_cards
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected


class BudgetSearchTests(CatalogTestCase):
    common = test_common_cards.CommonCardTests.common
    match = test_common_cards.CommonCardTests.match

    def search(self, **options):
        self.assertTrue({"price_min", "price_max", "sort"} <= set(signature(self.catalog.search_catalog).parameters),
                        "Budget search and sorting are not implemented")
        return self.catalog.search_catalog(context=self.buyer_context, **options)

    def test_budget_is_inclusive_and_zero_is_a_real_bound(self):
        free, _, _ = self.product(title="Бесплатная вещь", price="0")
        lower, _, _ = self.product(title="Цена сто", price="100")
        upper, _, _ = self.product(title="Цена двести", price="200")
        self.assertEqual([row["id"] for row in self.search(price_max="0")["items"]], [str(free)])
        rows = self.search(price_min="100", price_max="200")["items"]
        self.assertEqual({row["id"] for row in rows}, {str(lower), str(upper)})

    def test_comma_decimal_is_supported_without_rounding(self):
        product, _, _ = self.product(price="12.34")
        self.assertEqual([row["id"] for row in self.search(price_min="12,34", price_max="12,34")["items"]], [str(product)])
        with self.assertRaises(InputRejected):
            self.search(price_min="12.345")

    def test_invalid_bounds_and_sort_fail_closed(self):
        self.search()
        for options in ({"price_min": "-1"}, {"price_max": "NaN"}, {"price_min": True},
                        {"price_min": 1.5}, {"price_min": "1e3"}, {"price_max": {}},
                        {"price_min": "200", "price_max": "100"}, {"sort": "random"}, {"sort": []}):
            with self.subTest(options=options):
                with self.assertRaises(InputRejected):
                    self.search(**options)

    def test_no_rounding_or_float_loss_in_price_order(self):
        higher, _, _ = self.product(title="Альфа дорогая", price="9999999999999999.99")
        lower, _, _ = self.product(title="Янтарь дешёвая", price="9999999999999999.98")
        self.assertEqual([row["id"] for row in self.search(sort="price_asc")["items"]], [str(lower), str(higher)])
        self.assertEqual([row["id"] for row in self.search(sort="price_desc")["items"]], [str(higher), str(lower)])

    def test_only_matching_available_variant_sets_grid_price(self):
        product, _, photo = self.product(price="100", stock="3", color="Красный", size="S")
        variant = self.catalog.add_variant(product_id=product, expected_version=self.revision(product), context=self.seller_context,
            data={"label": "Синий M", "attributes": {"color": "Синий", "size": "M"}, "photo_ids": [str(photo)]})
        self.catalog.set_offer(variant_id=variant, field="price", value="300", expected_version=0, context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="stock", value="2", expected_version=0, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        row = self.search(price_min="200")["items"][0]
        self.assertEqual(row["id"], str(product))
        self.assertEqual(row["price"], Decimal("300.00"))
        self.assertEqual(row["variant_ids"], [str(variant)])
        self.assertEqual(self.search(price_min="200", filters={"color": ["Красный"]})["items"], [])

    def test_stock_and_grouping_rules_still_apply(self):
        hidden, _, _ = self.product(price="5", stock="0")
        visible, variant, _ = self.product(price="10")
        common, target, _ = self.common()
        self.match(variant, target)
        ids = [row["id"] for row in self.search(price_max="20")["items"]]
        self.assertEqual(ids, [str(common)])
        self.assertNotIn(str(hidden), ids)
        self.assertNotIn(str(visible), ids)

    def test_common_offer_above_minimum_is_not_hidden_by_cheaper_offer(self):
        _, low_variant, _ = self.product(price="100")
        _, high_variant, _ = self.product(price="250", context=self.other_context)
        common, target, _ = self.common()
        self.match(low_variant, target)
        self.match(high_variant, target, context=self.other_context)
        row = self.search(price_min="200", price_max="300")["items"][0]
        self.assertEqual(row["id"], str(common))
        self.assertEqual(row["price"], Decimal("250.00"))
        self.assertEqual(row["price_label"], "250,00 ₽")
        original = self.catalog.get_product(product_id=common, context=self.buyer_context)
        self.assertEqual(original["variants"][0]["price"], Decimal("100.00"))

    def test_facet_availability_respects_budget_without_losing_choices(self):
        self.product(price="50", color="Красный")
        self.product(price="250", color="Синий")
        data = self.search(category_id=str(self.category_id), price_min="200")
        color = next(row for row in data["facets"] if row["key"] == "color")
        self.assertEqual({value["value"] for value in color["values"] if value["available"]}, {"Синий"})
        self.assertEqual({value["value"] for value in color["values"]}, {"Красный", "Синий"})
        empty = self.search(price_min="300")
        self.assertEqual(empty["items"], [])
        self.assertIn(str(self.category_id), {row["id"] for row in empty["categories"]})

    def test_sorted_cursor_is_stable_and_rejects_changed_conditions(self):
        for title, price in (("Бета", "100"), ("Альфа", "100"), ("Гамма", "300")):
            self.product(title=title, price=price)
        with patch("open_marketplace.catalog.search.PAGE_SIZE", 1):
            first = self.search(price_min="50", sort="price_asc")
            second = self.search(price_min="50.00", sort="price_asc", cursor=first["next_cursor"])
            third = self.search(price_min="50", sort="price_asc", cursor=second["next_cursor"])
        titles = [page["items"][0]["title"] for page in (first, second, third)]
        self.assertEqual(titles, ["Альфа", "Бета", "Гамма"])
        self.assertIsNone(third["next_cursor"])
        for options in ({"sort": "price_desc", "price_min": "50"}, {"sort": "price_asc", "price_min": "100"}):
            with self.subTest(options=options):
                with self.assertRaises(InputRejected):
                    self.search(cursor=first["next_cursor"], **options)

    def test_price_sort_preserves_exact_and_semantic_labels(self):
        approximate, _, _ = self.product(title="Куртки", price="10")
        literal, _, _ = self.product(title="Куртка", price="200")
        rows = self.search(query="Куртка", sort="price_desc")["items"]
        exact = next(row for row in rows if row["id"] == str(literal))
        self.assertFalse(exact["approximate"])
        near = next(row for row in rows if row["id"] == str(approximate))
        self.assertTrue(near["approximate"])

    def test_price_sort_keeps_suggestion_for_free_approximate_match(self):
        self.product(title="Куртка", price="0")
        result = self.search(query="куртко", sort="price_asc")
        self.assertEqual(result["suggestion"], "куртка")
        self.assertTrue(result["items"][0]["approximate"])
