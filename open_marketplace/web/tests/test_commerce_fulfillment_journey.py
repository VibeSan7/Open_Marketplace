from uuid import uuid4

from django.apps import apps

from open_marketplace.catalog.tests import test_web
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.commerce import public as commerce_public


class CommerceFulfillmentJourneyWebTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        _, variant_id, _ = self.product(title="Отгрузка продавца")
        self.address = commerce_public.create_delivery_address(
            data={
                "label": "Дом",
                "recipient_name": "Иван Петров",
                "phone": "+79991234567",
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
        order = commerce_public.create_order(
            intent_id=uuid4(),
            lines=[
                {
                    "variant_id": str(variant_id),
                    "quantity": "1",
                    "expected_unit_price": "120",
                },
            ],
            delivery_address=self.address,
            context=self.buyer_context,
        )
        apps.get_model("commerce", "CommerceOrder").objects.filter(pk=order["id"]).update(
            state=apps.get_model("commerce", "CommerceOrder").State.PAID,
        )
        self.shipment = commerce_public.create_fulfillment_plan(
            order_id=order["id"],
            delivery_modes={order["lines"][0]["seller_account_id"]: "seller"},
            context=self.buyer_context,
        )[0]
        self.buyer_client = test_web.CatalogWebTests.client_for(self, self.buyer_registry)
        self.seller_client = test_web.CatalogWebTests.client_for(self, self.seller_registry)
        self.other_client = test_web.CatalogWebTests.client_for(self, self.other_registry)

    def _csrf_token(self, client, url):
        client.get(url)
        return client.cookies["csrftoken"].value

    def test_buyer_and_seller_can_open_authorized_shipment_screens(self):
        response = self.buyer_client.get("/commerce-fulfillment/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.shipment["id"])
        detail = self.seller_client.get(f"/commerce-fulfillment/{self.shipment['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Отгрузка")
        self.assertNotContains(detail, "Химки")

    def test_foreign_shipment_is_not_exposed_to_seller(self):
        response = self.other_client.get(f"/commerce-fulfillment/{self.shipment['id']}/")
        unknown = self.other_client.get(f"/commerce-fulfillment/{uuid4()}/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content, unknown.content)

    def test_seller_can_prepare_and_dispatch_seller_shipment(self):
        url = f"/commerce-fulfillment/{self.shipment['id']}/transition/"
        response = self.seller_client.post(url, {"target_state": "ready"})
        self.assertEqual(response.status_code, 403)
        token = self._csrf_token(self.seller_client, f"/commerce-fulfillment/{self.shipment['id']}/")
        response = self.seller_client.post(
            url,
            {"target_state": "ready", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 303)
        token = self.seller_client.cookies["csrftoken"].value
        response = self.seller_client.post(
            url,
            {"target_state": "in_transit", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 303)
        self.assertContains(
            self.seller_client.get(f"/commerce-fulfillment/{self.shipment['id']}/"),
            "В пути",
        )

    def test_buyer_can_confirm_receipt_after_seller_dispatch(self):
        commerce_public.transition_fulfillment(
            shipment_id=self.shipment["id"],
            target_state="ready",
            context=self.context(self.seller_registry),
        )
        commerce_public.transition_fulfillment(
            shipment_id=self.shipment["id"],
            target_state="in_transit",
            context=self.context(self.seller_registry),
        )
        url = f"/commerce-fulfillment/{self.shipment['id']}/transition/"
        token = self._csrf_token(self.buyer_client, f"/commerce-fulfillment/{self.shipment['id']}/")
        response = self.buyer_client.post(
            url,
            {"target_state": "delivered", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 303)
        self.assertContains(
            self.buyer_client.get(f"/commerce-fulfillment/{self.shipment['id']}/"),
            "Доставлено",
        )

    def test_cdek_transition_is_not_available_from_browser(self):
        order = commerce_public.create_order(
            intent_id=uuid4(),
            lines=[
                {
                    "variant_id": self.shipment["lines"][0]["variant_id"],
                    "quantity": "1",
                    "expected_unit_price": "120",
                },
            ],
            delivery_address=self.address,
            context=self.buyer_context,
        )
        apps.get_model("commerce", "CommerceOrder").objects.filter(pk=order["id"]).update(
            state=apps.get_model("commerce", "CommerceOrder").State.PAID,
        )
        shipment = commerce_public.create_fulfillment_plan(
            order_id=order["id"],
            delivery_modes={order["lines"][0]["seller_account_id"]: "cdek"},
            context=self.buyer_context,
        )[0]
        client = self.seller_client
        token = self._csrf_token(client, f"/commerce-fulfillment/{shipment['id']}/")
        response = client.post(
            f"/commerce-fulfillment/{shipment['id']}/transition/",
            {"target_state": "in_transit", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "провайдера", status_code=409)
