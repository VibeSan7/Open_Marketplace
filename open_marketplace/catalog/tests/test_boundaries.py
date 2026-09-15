from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, PermissionDenied


class PublicationBoundaryTests(CatalogTestCase):
    def test_direct_link_rejects_unsupported_filter_instead_of_ignoring_it(self):
        product, variant, photo = self.product()
        with self.assertRaises(InputRejected):
            self.catalog.get_product(product_id=product, variant_id=variant, filters={"unsupported": ["x"]}, context=self.buyer_context)

    def test_whole_withdrawal_preserves_offers_and_cannot_be_undone_by_old_draft(self):
        self.assertTrue(callable(getattr(self.catalog, "withdraw_product", None)), "Whole-card withdrawal is not implemented.")
        product, variant, photo = self.product(stock="3")
        revision = self.revision(product)
        self.catalog.withdraw_product(product_id=product, context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=revision, context=self.seller_context)
        owned = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.assertEqual(str(owned["variants"][0]["stocks"][0]["quantity"]), "3.000")
