from urllib.parse import parse_qs, urlsplit

from open_marketplace.catalog.tests import test_common_cards, test_web
from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class BudgetWebTests(CatalogTestCase):
    client_for = test_web.CatalogWebTests.client_for
    common = test_common_cards.CommonCardTests.common
    match = test_common_cards.CommonCardTests.match

    def test_search_applies_budget_and_keeps_it_in_links(self):
        self.product(title="Куртка ниже диапазона", price="100")
        product_id, _, _ = self.product(title="Куртка в диапазоне", price="300")
        response = self.client_for(self.buyer_registry).get("/catalog/", {
            "q": "Куртка", "price_min": "200", "price_max": "400,00", "sort": "price_desc",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.context["search"]["items"]], [str(product_id)])
        for url in (response.context["applied_url"], response.context["search"]["items"][0]["url"]):
            parameters = parse_qs(urlsplit(url).query)
            self.assertEqual(parameters["price_min"], ["200.00"])
            self.assertEqual(parameters["price_max"], ["400.00"])
            self.assertEqual(parameters["sort"], ["price_desc"])

    def test_default_variant_respects_budget_and_shares_conditions(self):
        product_id, cheap, photo = self.product(price="100")
        expensive = self.catalog.add_variant(product_id=product_id,
            expected_version=self.revision(product_id), context=self.seller_context,
            data={"label": "Синий M", "attributes": {"color": "Синий", "size": "M"}, "photo_ids": [str(photo)]})
        self.catalog.set_offer(variant_id=expensive, field="price", value="300", expected_version=0, context=self.seller_context)
        self.catalog.set_offer(variant_id=expensive, field="stock", value="1", expected_version=0, context=self.seller_context)
        self.catalog.publish_product(product_id=product_id, expected_version=self.revision(product_id), context=self.seller_context)
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product_id}/", {
            "from_search": "1", "price_min": "200", "price_max": "400", "sort": "price_desc",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["product"]["selected_variant_id"], str(expensive))
        for url in (response.context["back_url"], response.context["share_url"]):
            values = parse_qs(urlsplit(url).query)
            self.assertEqual(values["price_min"], ["200.00"])
            self.assertEqual(values["sort"], ["price_desc"])

    def test_explicit_variant_outside_budget_stays_selected_and_is_explained(self):
        product_id, variant_id, _ = self.product(price="100")
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product_id}/", {
            "variant": str(variant_id), "price_min": "200",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["product"]["selected_variant_id"], str(variant_id))
        self.assertContains(response, "вне выбранного диапазона цен")

    def test_common_offer_comparison_uses_matching_budget_without_fake_stock(self):
        common, common_variant, _ = self.common()
        _, low, _ = self.product(price="100", stock="1")
        _, high, _ = self.product(price="250", stock="1", context=self.other_context)
        self.match(low, common_variant)
        self.match(high, common_variant, context=self.other_context)
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{common}/", {
            "from_search": "1", "price_min": "200", "price_max": "300",
        })
        self.assertEqual(response.status_code, 200)
        selected = response.context["product"]["selected_variant"]
        self.assertEqual(str(selected["price"]), "250.00")
        self.assertEqual(len(selected["offers"]), 1)
        self.assertTrue(selected["in_stock"])
        self.assertContains(response, "Показаны предложения в выбранном диапазоне цен")

    def test_invalid_and_duplicate_price_conditions_are_visible_errors(self):
        client = self.client_for(self.buyer_registry)
        for query in ("price_min=no", "price_min=300&price_max=100", "sort=missing", "price_min=1&price_min=2"):
            with self.subTest(query=query):
                self.assertEqual(client.get("/catalog/?" + query).status_code, 400)

    def test_zero_price_survives_search_and_product_links(self):
        product_id, _, _ = self.product(price="0")
        response = self.client_for(self.buyer_registry).get("/catalog/?price_min=0&price_max=0")
        self.assertEqual(response.status_code, 200)
        url = response.context["search"]["items"][0]["url"]
        self.assertEqual(parse_qs(urlsplit(url).query)["price_max"], ["0.00"])
        self.assertEqual(self.client_for(self.buyer_registry).get(url).status_code, 200)
