from uuid import uuid4

from django.apps import apps

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import PermissionDenied


class SellerStorefrontTests(CatalogTestCase):
    def seller_id(self, account):
        return apps.get_model("seller_onboarding", "SellerProfile").objects.get(owner_id=account.id).id

    def test_storefront_uses_current_public_product_summary(self):
        product, _, photo = self.product(title="Пальто", price="350", stock="4")

        store = self.catalog.get_seller_store(
            seller_id=self.seller_id(self.seller), context=self.buyer_context,
        )

        self.assertEqual(store["seller"], {"id": str(self.seller_id(self.seller)), "display_name": "Первый продавец"})
        self.assertEqual(store["products"], [{
            "id": str(product), "title": "Пальто", "category": "Одежда", "cover_id": str(photo),
            "unit_label": "шт.", "price": 350, "price_label": "350,00 ₽", "in_stock": True,
        }])

    def test_storefront_hides_private_seller_data(self):
        self.product()

        store = self.catalog.get_seller_store(
            seller_id=self.seller_id(self.seller), context=self.buyer_context,
        )
        rendered = str(store)
        for private_value in (self.seller.email, "Тестовая запись", "registration_identifier"):
            self.assertNotIn(private_value, rendered)
        self.assertNotIn(str(self.seller.id), rendered)

    def test_unknown_and_seller_without_visible_physical_card_are_neutral(self):
        unknown = None
        for seller_id in (uuid4(), self.seller_id(self.seller)):
            if seller_id == self.seller_id(self.seller):
                self.product(publish=False)
            with self.assertRaises(PermissionDenied) as error:
                self.catalog.get_seller_store(seller_id=seller_id, context=self.buyer_context)
            if unknown is None:
                unknown = str(error.exception)
            else:
                self.assertEqual(str(error.exception), unknown)

    def test_public_product_and_offer_expose_profile_id_only(self):
        product, variant, _ = self.product()

        card = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(card["seller_id"], str(self.seller_id(self.seller)))
        self.assertEqual(card["variants"][0]["offers"][0]["seller_id"], str(self.seller_id(self.seller)))
        self.assertNotIn("owner_id", str(card))
        self.assertNotIn(str(self.seller.id), str(card))
