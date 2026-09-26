from uuid import uuid4

from django.apps import apps

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.commerce.models import CommerceOrder
from open_marketplace.commerce.public import (
    add_commerce_cart_item,
    checkout_commerce_cart,
    create_delivery_address,
    get_commerce_cart,
    get_delivery_address,
    list_delivery_addresses,
)


class DeliveryAddressTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.product_id, self.variant_id, _ = self.product()

    def address_data(self, **overrides):
        data = {
            "label": "Дом",
            "recipient_name": "Иван Петров",
            "phone": "+79990001122",
            "postal_code": "123456",
            "region": "Московская область",
            "city": "Химки",
            "street": "Лесная",
            "building": "10",
            "apartment": "25",
            "comment": "Позвонить перед доставкой",
        }
        data.update(overrides)
        return data

    def test_buyer_can_create_and_list_own_address(self):
        address = create_delivery_address(data=self.address_data(), context=self.buyer_context)

        self.assertEqual(address["label"], "Дом")
        self.assertEqual(address["country_code"], "RU")
        self.assertEqual(list_delivery_addresses(context=self.buyer_context), (address,))

    def test_address_is_buyer_scoped_and_invalid_fields_are_rejected(self):
        address = create_delivery_address(data=self.address_data(), context=self.buyer_context)
        foreign_context = self.context(self.create_registry(self.create_account(kind="ordinary")))

        with self.assertRaises(PermissionDenied):
            get_delivery_address(address_id=address["id"], context=foreign_context)
        with self.assertRaises(PermissionDenied):
            get_delivery_address(address_id=uuid4(), context=self.buyer_context)
        with self.assertRaises(InputRejected):
            create_delivery_address(data=self.address_data(phone="bad"), context=self.buyer_context)
        with self.assertRaises(InputRejected):
            create_delivery_address(data=self.address_data(city=""), context=self.buyer_context)

    def test_checkout_persists_immutable_address_and_replay_requires_same_address(self):
        add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        first_address = create_delivery_address(data=self.address_data(), context=self.buyer_context)
        second_address = create_delivery_address(
            data=self.address_data(label="Работа", city="Москва"),
            context=self.buyer_context,
        )
        intent_id = get_commerce_cart(context=self.buyer_context)["intent_id"]

        first = checkout_commerce_cart(
            intent_id=intent_id,
            delivery_address_id=first_address["id"],
            context=self.buyer_context,
        )
        second = checkout_commerce_cart(
            intent_id=intent_id,
            delivery_address_id=first_address["id"],
            context=self.buyer_context,
        )

        self.assertEqual(first, second)
        order = CommerceOrder.objects.get(pk=first[0]["id"])
        self.assertEqual(order.delivery_address["city"], "Химки")
        self.assertEqual(order.delivery_address["recipient_name"], "Иван Петров")
        apps.get_model("commerce", "CommerceDeliveryAddress").objects.filter(
            pk=first_address["id"],
        ).update(city="Санкт-Петербург")
        order.refresh_from_db()
        self.assertEqual(order.delivery_address["city"], "Химки")
        with self.assertRaises(ConcurrentConflict):
            checkout_commerce_cart(
                intent_id=intent_id,
                delivery_address_id=second_address["id"],
                context=self.buyer_context,
            )
        receipt = apps.get_model("commerce", "CommerceCartCheckoutReceipt").objects.get(
            intent_id=intent_id,
        )
        self.assertEqual(str(receipt.delivery_address_id), first_address["id"])

    def test_checkout_requires_a_delivery_address(self):
        add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        intent_id = get_commerce_cart(context=self.buyer_context)["intent_id"]

        with self.assertRaises(InputRejected):
            checkout_commerce_cart(
                intent_id=intent_id,
                delivery_address_id=None,
                context=self.buyer_context,
            )
        self.assertEqual(CommerceOrder.objects.count(), 0)
