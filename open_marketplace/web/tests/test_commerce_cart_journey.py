from django.apps import apps
from django.test import Client

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.catalog.tests import test_web
from open_marketplace.commerce import public as commerce_public


class CommerceCartJourneyWebTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.product_id, self.variant_id, _ = self.product(title="Рабочая корзина")
        self.client = test_web.CatalogWebTests.client_for(self, self.buyer_registry)
        self.address = commerce_public.create_delivery_address(
            data={
                "label": "Дом",
                "recipient_name": "Иван Петров",
                "phone": "+79990001122",
                "postal_code": "123456",
                "region": "Московская область",
                "city": "Химки",
                "street": "Лесная",
                "building": "10",
                "apartment": "25",
                "comment": "",
            },
            context=self.buyer_context,
        )

    def test_guest_is_redirected_to_login(self):
        response = Client().get("/commerce-cart/")
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login/?next=%2Fcommerce-cart%2F", response["Location"])

    def test_buyer_can_add_item_and_see_server_confirmed_cart(self):
        page = self.client.get("/commerce-cart/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Рабочая корзина")
        self.client.get(f"/catalog/p/{self.product_id}/?variant={self.variant_id}")
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            f"/commerce-cart/add/{self.variant_id}/",
            {"quantity": "1", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 303)
        page = self.client.get("/commerce-cart/")
        self.assertContains(page, "Рабочая корзина")
        self.assertContains(page, "120,00")
        self.assertContains(page, "Реальная оплата")

    def test_buyer_can_create_and_list_saved_address(self):
        page = self.client.get("/commerce-addresses/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Адреса доставки")
        self.assertContains(page, "Химки")

        form_page = self.client.get("/commerce-addresses/new/")
        self.assertEqual(form_page.status_code, 200)
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            "/commerce-addresses/new/",
            {
                "label": "Работа",
                "recipient_name": "Иван Петров",
                "phone": "+79990001122",
                "postal_code": "123456",
                "region": "Москва",
                "city": "Москва",
                "street": "Тверская",
                "building": "1",
                "apartment": "",
                "comment": "",
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/commerce-addresses/", response["Location"])

    def test_buyer_can_edit_and_delete_saved_address(self):
        edit_page = self.client.get(f"/commerce-addresses/{self.address['id']}/edit/")
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, "Редактирование адреса")

        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            f"/commerce-addresses/{self.address['id']}/edit/",
            {
                "label": "Работа",
                "recipient_name": "Иван Петров",
                "phone": "+79900112233",
                "postal_code": "123456",
                "region": "Москва",
                "city": "Москва",
                "street": "Тверская",
                "building": "1",
                "apartment": "",
                "comment": "",
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertContains(self.client.get("/commerce-addresses/"), "Москва")

        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            f"/commerce-addresses/{self.address['id']}/delete/",
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 303)
        self.assertNotContains(self.client.get("/commerce-addresses/"), "Москва")

    def test_address_delete_requires_post_and_exact_fields(self):
        response = self.client.get(f"/commerce-addresses/{self.address['id']}/delete/")
        self.assertEqual(response.status_code, 405)

        self.client.get("/commerce-addresses/")
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            f"/commerce-addresses/{self.address['id']}/delete/",
            {"csrfmiddlewaretoken": token, "confirm": "yes"},
        )
        self.assertEqual(response.status_code, 400)

    def test_checkout_requires_address_selection(self):
        commerce_public.add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        page = self.client.get("/commerce-cart/checkout/")
        intent_id = page.context["form"].initial["intent_id"]
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            "/commerce-cart/checkout/",
            {"intent_id": intent_id, "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "адрес", status_code=400)

    def test_checkout_rejects_foreign_address(self):
        foreign = self.create_account(kind="ordinary")
        foreign_context = self.context(self.create_registry(foreign))
        foreign_address = commerce_public.create_delivery_address(
            data={
                "label": "Чужой адрес",
                "recipient_name": "Иван Петров",
                "phone": "+79990001122",
                "postal_code": "123456",
                "region": "Москва",
                "city": "Москва",
                "street": "Тверская",
                "building": "1",
                "apartment": "",
                "comment": "",
            },
            context=foreign_context,
        )
        commerce_public.add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        page = self.client.get("/commerce-cart/checkout/")
        intent_id = page.context["form"].initial["intent_id"]
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            "/commerce-cart/checkout/",
            {
                "intent_id": intent_id,
                "delivery_address_id": foreign_address["id"],
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_checkout_creates_local_order_without_payment_claim(self):
        commerce_public.add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        page = self.client.get("/commerce-cart/checkout/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Локальное оформление")
        intent_id = page.context["form"].initial["intent_id"]
        self.client.get(f"/catalog/p/{self.product_id}/?variant={self.variant_id}")
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            "/commerce-cart/checkout/",
            {
                "intent_id": intent_id,
                "delivery_address_id": self.address["id"],
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заказ создан локально")
        self.assertContains(response, "Оплата не подключена")

    def test_product_page_offers_working_cart_action(self):
        response = self.client.get(f"/catalog/p/{self.product_id}/?variant={self.variant_id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="/commerce-cart/add/{self.variant_id}/"')
        self.assertContains(response, "В рабочую корзину")

    def test_cart_rejects_unknown_post_fields(self):
        self.client.get("/commerce-cart/")
        self.client.get(f"/catalog/p/{self.product_id}/?variant={self.variant_id}")
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            f"/commerce-cart/add/{self.variant_id}/",
            {"quantity": "1", "price": "0", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "не поддерживается", status_code=400)

    def test_buyer_can_view_order_history_and_order_detail(self):
        commerce_public.add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        orders = commerce_public.checkout_commerce_cart(
            intent_id=commerce_public.get_commerce_cart(context=self.buyer_context)["intent_id"],
            delivery_address_id=self.address["id"],
            context=self.buyer_context,
        )
        order_id = orders[0]["id"]

        history = self.client.get("/commerce-orders/")
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, "Мои заказы")
        self.assertContains(history, order_id)

        detail = self.client.get(f"/commerce-orders/{order_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Заказ")
        self.assertContains(detail, "120,00")
        self.assertContains(detail, "Ожидает подтверждения оплаты")
        self.assertContains(detail, "Химки")

    def test_buyer_can_cancel_unpaid_order_and_release_reservation(self):
        commerce_public.add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        orders = commerce_public.checkout_commerce_cart(
            intent_id=commerce_public.get_commerce_cart(context=self.buyer_context)["intent_id"],
            delivery_address_id=self.address["id"],
            context=self.buyer_context,
        )
        order_id = orders[0]["id"]
        reservation_id = orders[0]["reservation_id"]
        detail = self.client.get(f"/commerce-orders/{order_id}/")
        token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            f"/commerce-orders/{order_id}/cancel/",
            {"csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 303)
        reservation = apps.get_model("catalog", "InventoryReservation").objects.get(pk=reservation_id)
        self.assertEqual(reservation.state, "released")
        detail = self.client.get(f"/commerce-orders/{order_id}/")
        self.assertContains(detail, "Отменено")
        self.assertNotContains(detail, "Отменить заказ")

    def test_guest_is_redirected_from_order_history(self):
        response = Client().get("/commerce-orders/")
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login/?next=%2Fcommerce-orders%2F", response["Location"])
