from importlib import import_module
from uuid import uuid4

from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class CatalogIntegrationTests(CatalogTestCase):
    client_for = import_module("open_marketplace.catalog.tests.test_web").CatalogWebTests.client_for
    common = import_module("open_marketplace.catalog.tests.test_common_cards").CommonCardTests.common

    def post(self, client, url, data):
        client.get(url)
        return client.post(url, {**data, "csrfmiddlewaretoken": client.cookies["csrftoken"].value})

    def test_seller_can_choose_common_card_without_existing_offers(self):
        product, variant, photo = self.product()
        common, target, photo = self.common()
        client = self.client_for(self.seller_registry)
        response = client.get(f"/catalog/own/{product}/")
        self.assertContains(response, "Куртка общая")
        self.assertContains(response, f'value="{target}"')
        response = self.post(client, f"/catalog/own/{product}/", {
            "action": "request_match", "source_variant_id": str(variant),
            "target_variant_id": str(target), "reason": "Идентичные модель и размер",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.catalog.list_match_requests(context=self.seller_context, own=True)), 1)

    def test_management_includes_published_seller_products_and_participants(self):
        product, variant, photo = self.product(title="Публичный товар продавца")
        self.product(title="Личный черновик", publish=False)
        response = self.client_for(self.staff_registry).get("/catalog/manage/")
        self.assertContains(response, "Публичный товар продавца")
        self.assertContains(response, self.buyer.email)
        self.assertNotContains(response, "Личный черновик")

    def test_new_storage_location_can_be_filled_for_existing_variant(self):
        product, variant, photo = self.product()
        location = self.catalog.create_location(name="Второй склад", context=self.seller_context)
        client = self.client_for(self.seller_registry)
        page = client.get(f"/catalog/own/{product}/")
        self.assertContains(page, f'value="{location}"')
        response = self.post(client, f"/catalog/own/{product}/", {
            "action": "set_stock", "variant_id": str(variant), "location_id": str(location),
            "expected_version": "0", "quantity": "5",
        })
        self.assertEqual(response.status_code, 303)
        own = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        stock = next(row for row in own["variants"][0]["stocks"] if row["location_id"] == str(location))
        self.assertEqual(stock["quantity"], 5)

    def test_foreign_variant_input_does_not_crash_or_change_content(self):
        product, variant, photo = self.product()
        client = self.client_for(self.seller_registry)
        response = self.post(client, f"/catalog/own/{product}/", {
            "action": "save_variant", "variant_id": str(uuid4()),
            "expected_version": str(self.revision(product)), "label": "Подмена",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["title"], "Куртка")

    def test_price_conflict_preserves_input_and_allows_explicit_retry(self):
        product, variant, photo = self.product()
        self.catalog.set_offer(variant_id=variant, field="price", value="130", expected_version=1, context=self.seller_context)
        client = self.client_for(self.seller_registry)
        response = self.post(client, f"/catalog/own/{product}/", {
            "action": "set_price", "variant_id": str(variant), "expected_version": "1", "price": "145,50",
        })
        self.assertEqual(response.status_code, 409)
        form = response.context["variants"][0]["price_form"]
        self.assertEqual(form["price"].value(), "145,50")
        self.assertEqual(str(form["expected_version"].value()), "2")
        self.assertContains(response, "130", status_code=409)
        current = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.assertEqual(current["variants"][0]["price"], 130)
        response = self.post(client, f"/catalog/own/{product}/", {
            "action": "set_price", "variant_id": str(variant), "expected_version": "2", "price": "145,50",
        })
        self.assertEqual(response.status_code, 303)

    def test_suggestion_preserves_category_and_filters(self):
        self.product()
        response = self.client_for(self.buyer_registry).get("/catalog/", {
            "q": "куркта", "category": str(self.category_id), "f.color": "Красный",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("f.color=", response.context["suggestion_url"])
        self.assertIn(f"category={self.category_id}", response.context["suggestion_url"])

    def test_unknown_filter_has_explicit_case_insensitive_error(self):
        response = self.client_for(self.buyer_registry).get("/catalog/?f.missing=x")
        self.assertEqual(response.status_code, 400)
        self.assertIn("фильтр", response.content.decode().casefold())

    def test_seller_sees_answers_to_own_requests_and_suggestions(self):
        product, variant, photo = self.product()
        common, target, photo = self.common()
        request = self.catalog.request_match(source_variant_id=variant, target_variant_id=target, reason="Совпадает", context=self.seller_context)
        self.catalog.review_match(request_id=request, approve=True, identity_confirmed=True, reason="Модель и комплектация подтверждены", context=self.staff_context)
        suggestion = self.catalog.suggest_change(kind="category", target_id=None, text="Нужна обувь", context=self.seller_context)
        self.catalog.review_suggestion(suggestion_id=suggestion, response="Добавлена категория обуви", context=self.staff_context)
        response = self.client_for(self.seller_registry).get("/catalog/own/")
        self.assertContains(response, "Модель и комплектация подтверждены")
        self.assertContains(response, "Добавлена категория обуви")
        other = self.client_for(self.other_registry).get("/catalog/own/")
        self.assertNotContains(other, "Добавлена категория обуви")

    def test_stock_status_is_explicit_and_zero_stock_is_not_compared_as_an_offer(self):
        product, variant, photo = self.product(stock="3")
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product}/")
        self.assertContains(response, "В наличии")
        location = self.catalog.get_own_product(product_id=product, context=self.seller_context)["locations"][0]["id"]
        self.catalog.set_offer(variant_id=variant, field="stock", value="0", expected_version=1, location_id=location, context=self.seller_context)
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product}/")
        self.assertContains(response, "Нет в наличии")
        self.assertNotContains(response, "<h3>Предложения</h3>")

    def test_service_account_can_create_common_card_from_browser(self):
        client = self.client_for(self.staff_registry)
        page = client.get("/catalog/own/new/")
        self.assertContains(page, 'value="common"')
        response = self.post(client, "/catalog/own/new/", {"kind": "common", "unit": "pc"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.catalog.list_own_products(context=self.staff_context)), 1)
