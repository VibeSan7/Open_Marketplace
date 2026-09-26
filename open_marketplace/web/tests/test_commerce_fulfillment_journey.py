from uuid import uuid4

from django.apps import apps

from open_marketplace.catalog.tests import test_web
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.commerce import public as commerce_public


class CommerceFulfillmentJourneyWebTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        _, variant_id, _ = self.product(title="Отгрузка продавца", stock="3")
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
                    "quantity": "2",
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
        self.assertContains(response, "Отгрузка продавца")
        self.assertContains(response, "Красный S")
        self.assertContains(response, "2")
        self.assertNotContains(response, "Упаковок")
        seller_list = self.seller_client.get("/commerce-fulfillment/")
        self.assertEqual(seller_list.status_code, 200)
        self.assertContains(seller_list, "Отгрузка продавца")
        self.assertContains(seller_list, "Красный S")
        self.assertContains(seller_list, "2")
        self.assertContains(seller_list, "Упаковок: 0")
        detail = self.seller_client.get(f"/commerce-fulfillment/{self.shipment['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Отгрузка")
        self.assertContains(detail, "История состояния")
        self.assertContains(detail, "Отгрузка запланирована")
        self.assertNotContains(detail, "Химки")

    def test_fulfillment_list_filters_by_state_and_rejects_invalid_query(self):
        matching = self.seller_client.get("/commerce-fulfillment/?state=pending")
        self.assertEqual(matching.status_code, 200)
        self.assertContains(matching, self.shipment["id"])
        self.assertContains(matching, "Фильтр: Ожидает планирования")
        self.assertContains(matching, "Всего: 1")
        self.assertContains(matching, "Ожидает планирования: 1")

        not_matching = self.seller_client.get("/commerce-fulfillment/?state=ready")
        self.assertEqual(not_matching.status_code, 200)
        self.assertNotContains(not_matching, self.shipment["id"])
        self.assertContains(not_matching, "По этому фильтру отгрузок нет.")
        self.assertContains(not_matching, "Всего: 1")
        self.assertContains(not_matching, "Ожидает планирования: 1")

        for query in (
            "state=pending&state=ready",
            "state=unknown",
            "unexpected=value",
        ):
            response = self.seller_client.get(f"/commerce-fulfillment/?{query}")
            self.assertEqual(response.status_code, 400)

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

    def _package_payload(self, client, rows):
        detail_url = f"/commerce-fulfillment/{self.shipment['id']}/"
        client.get(detail_url)
        if "csrftoken" not in client.cookies:
            client.get("/login/")
        token = client.cookies["csrftoken"].value
        data = {
            "csrfmiddlewaretoken": token,
            "packages-TOTAL_FORMS": str(len(rows)),
            "packages-INITIAL_FORMS": "0",
            "packages-MIN_NUM_FORMS": "0",
            "packages-MAX_NUM_FORMS": "32",
        }
        for index, row in enumerate(rows):
            for field, value in row.items():
                data[f"packages-{index}-{field}"] = str(value)
        return data

    def test_seller_can_save_multiple_packages_and_buyer_cannot_see_them(self):
        rows = [
            {"weight_grams": 1000, "length_cm": 10, "width_cm": 20, "height_cm": 30, "line_0": "1"},
            {"weight_grams": 2000, "length_cm": 40, "width_cm": 50, "height_cm": 60, "line_0": "1"},
        ]
        response = self.seller_client.post(
            f"/commerce-fulfillment/{self.shipment['id']}/packages/",
            self._package_payload(self.seller_client, rows),
        )
        self.assertEqual(response.status_code, 303)
        seller_detail = self.seller_client.get(f"/commerce-fulfillment/{self.shipment['id']}/")
        seller_list = self.seller_client.get("/commerce-fulfillment/")
        self.assertContains(seller_detail, "1000 г")
        self.assertContains(seller_detail, "2000 г")
        self.assertContains(seller_detail, "Данные упаковки")
        self.assertContains(seller_list, "Упаковок: 2")
        seller_snapshot = commerce_public.get_fulfillment_shipment(
            shipment_id=self.shipment["id"],
            context=self.context(self.seller_registry),
        )
        self.assertEqual(
            seller_snapshot["packages"][0]["items"],
            [{"line_index": 0, "quantity": "1"}],
        )
        self.assertEqual(
            seller_snapshot["packages"][1]["items"],
            [{"line_index": 0, "quantity": "1"}],
        )
        buyer_detail = self.buyer_client.get(f"/commerce-fulfillment/{self.shipment['id']}/")
        self.assertNotContains(buyer_detail, "1000 г")
        self.assertNotContains(buyer_detail, "Данные упаковки")

    def test_empty_package_submission_clears_manifest(self):
        commerce_public.set_fulfillment_packages(
            shipment_id=self.shipment["id"],
            packages=[{"weight_grams": 1000, "length_cm": 10, "width_cm": 10, "height_cm": 10, "items": [{"line_index": 0, "quantity": "2"}]}],
            context=self.context(self.seller_registry),
        )
        response = self.seller_client.post(
            f"/commerce-fulfillment/{self.shipment['id']}/packages/",
            self._package_payload(self.seller_client, []),
        )
        self.assertEqual(response.status_code, 303)
        seller = commerce_public.get_fulfillment_shipment(
            shipment_id=self.shipment["id"],
            context=self.context(self.seller_registry),
        )
        self.assertEqual(seller["packages"], [])

    def test_invalid_or_foreign_package_submission_does_not_mutate(self):
        invalid = self._package_payload(
            self.seller_client,
            [{"weight_grams": 0, "length_cm": 10, "width_cm": 10}],
        )
        response = self.seller_client.post(
            f"/commerce-fulfillment/{self.shipment['id']}/packages/",
            invalid,
        )
        self.assertEqual(response.status_code, 400)
        seller = commerce_public.get_fulfillment_shipment(
            shipment_id=self.shipment["id"],
            context=self.context(self.seller_registry),
        )
        self.assertEqual(seller["packages"], [])

        foreign_data = self._package_payload(
            self.other_client,
            [{"weight_grams": 1000, "length_cm": 10, "width_cm": 10, "height_cm": 10}],
        )
        response = self.other_client.post(
            f"/commerce-fulfillment/{self.shipment['id']}/packages/",
            foreign_data,
        )
        self.assertEqual(response.status_code, 403)

    def test_package_submission_is_locked_after_dispatch(self):
        commerce_public.transition_fulfillment(
            shipment_id=self.shipment["id"],
            target_state="ready",
            context=self.context(self.seller_registry),
        )
        response = self.seller_client.post(
            f"/commerce-fulfillment/{self.shipment['id']}/packages/",
            self._package_payload(
                self.seller_client,
                [{"weight_grams": 1000, "length_cm": 10, "width_cm": 10, "height_cm": 10}],
            ),
        )
        self.assertEqual(response.status_code, 409)

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
