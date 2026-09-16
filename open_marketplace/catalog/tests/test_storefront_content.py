from django.test import override_settings
from django.urls import reverse

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.catalog.tests import test_web


class StorefrontContentTests(CatalogTestCase):
    def test_home_preview_is_bounded_and_links_to_full_catalog(self):
        for number in range(13):
            product, _, _ = self.product(title=f"Публичный товар {number}")
            self.catalog.set_public_listing(product_id=product, enabled=True, context=self.seller_context)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["storefront"]["total"], 13)
        self.assertEqual(len(response.context["storefront"]["items"]), 12)
        self.assertContains(response, "Смотреть все товары")

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_buyer_can_choose_fractional_quantity_on_product_page(self):
        product, _, _ = self.product(unit="kg", stock="0.5")
        client = test_web.CatalogWebTests.client_for(self, self.buyer_registry)
        response = client.get(reverse("catalog-product", kwargs={"product_id": product}))
        self.assertContains(response, 'name="quantity"')
        self.assertNotContains(response, 'type="hidden" name="quantity"')
        self.assertContains(response, 'step="0.001"')

    @override_settings(DEMO_ORDERS_ENABLED=False)
    def test_disabled_demo_does_not_offer_cart_mutations_on_product(self):
        product, _, _ = self.product()
        client = test_web.CatalogWebTests.client_for(self, self.buyer_registry)
        response = client.get(reverse("catalog-product", kwargs={"product_id": product}))
        self.assertNotContains(response, 'action="/cart/add/')
