
from django.test import override_settings

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.demo_orders import cart
from open_marketplace.demo_orders.models import Cart


@override_settings(DEMO_ORDERS_ENABLED=True)
class CartIntegrityTests(CatalogTestCase):
    def test_empty_cart_read_does_not_create_database_records(self):
        before = Cart.objects.count()
        result = cart.get_cart(context=self.buyer_context)
        self.assertEqual(Cart.objects.count(), before)
        self.assertEqual(result["items"], ())
        self.assertFalse(result["checkout_available"])

    def test_different_sellers_with_equal_names_remain_separate(self):
        _, first, _ = self.product()
        second_seller, _, second_context = self.make_seller("Первый продавец")
        self.catalog.set_participant(account_id=second_seller.id, allowed=True, context=self.staff_context)
        _, second, _ = self.product(context=second_context)
        cart.add_cart_item(variant_id=first, quantity="1", context=self.buyer_context)
        cart.add_cart_item(variant_id=second, quantity="1", context=self.buyer_context)
        result = cart.get_cart(context=self.buyer_context)
        self.assertEqual(len(result["sellers"]), 2)
        self.assertEqual(len({row["seller_id"] for row in result["sellers"]}), 2)
