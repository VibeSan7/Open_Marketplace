from django.test import Client, override_settings

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.catalog.tests import test_web


@override_settings(DEMO_ORDERS_ENABLED=True)
class CartJourneyWebTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.product_id, self.variant_id, _ = self.product(title="Корзина в браузере")
        self.client = test_web.CatalogWebTests.client_for(self, self.buyer_registry)
        from open_marketplace.demo_orders import cart
        cart.add_cart_item(variant_id=self.variant_id, quantity="1", context=self.buyer_context)

    def test_cart_page_has_real_forms_and_no_csrf_allows_mutation(self):
        page = self.client.get("/cart/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Корзина")
        self.assertContains(page, "csrfmiddlewaretoken")
        rejected = self.client.post(f"/cart/add/{self.variant_id}/", {"quantity": "1"})
        self.assertEqual(rejected.status_code, 403)

    def test_cart_rejects_unknown_post_fields(self):
        self.client.get("/cart/")
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            f"/cart/add/{self.variant_id}/",
            {"quantity": "1", "price": "0", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "не поддерживается", status_code=400)

    def test_checkout_confirmation_creates_order_link_without_payment_claim(self):
        page = self.client.get("/cart/checkout/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Подтвердить тестовый заказ")
        intent_id = page.context["form"].initial["intent_id"]
        token = self.client.cookies["csrftoken"].value
        response = self.client.post("/cart/checkout/", {"intent_id": intent_id, "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Тестовые заказы созданы")
        self.assertContains(response, "реальные деньги")
        self.assertContains(response, "/demo-orders/")

    def test_disabled_cart_is_honest_and_not_a_checkout_form(self):
        with override_settings(DEMO_ORDERS_ENABLED=False):
            response = Client().get("/cart/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "отключена")
        self.assertNotContains(response, 'action="/cart/checkout/"')

    def test_changed_price_is_shown_before_explicit_confirmation(self):
        product = self.catalog.get_own_product(product_id=self.product_id, context=self.seller_context)
        self.catalog.set_offer(
            variant_id=self.variant_id, field="price", value="247.25",
            expected_version=product["variants"][0]["price_version"], context=self.seller_context,
        )
        response = self.client.get("/cart/")
        self.assertContains(response, "Новая цена: 247,25")
        self.assertNotContains(response, "Перейти к подтверждению")
