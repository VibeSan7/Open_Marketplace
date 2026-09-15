from decimal import Decimal

from django.apps import apps

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied


class CatalogLifecycleTests(CatalogTestCase):
    def test_publish_exposes_content_but_not_precise_stock(self):
        product, variant, photo = self.product(stock="7")
        view = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(view["title"], "Куртка")
        self.assertEqual(view["selected_variant_id"], str(variant))
        self.assertEqual(view["variants"][0]["photo_ids"], [str(photo)])
        self.assertTrue(view["variants"][0]["in_stock"])
        self.assertNotIn("quantity", str(view))
        self.assertNotIn("stock_version", str(view))
        self.assertNotIn("owner_id", view)

    def test_incomplete_first_publication_has_no_partial_effect(self):
        product = self.catalog.create_product(kind="physical", unit="pc", context=self.seller_context)
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=0, context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)

    def test_content_draft_does_not_publish_itself(self):
        product, variant, photo = self.product()
        self.catalog.save_product_draft(
            product_id=product, expected_version=self.revision(product),
            data={"title": "Новый заголовок", "description": "", "category_id": str(self.category_id), "attributes": {}},
            context=self.seller_context,
        )
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["title"], "Куртка")
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["title"], "Куртка")

    def test_price_is_immediate_and_old_content_does_not_roll_it_back(self):
        product, variant, photo = self.product()
        self.catalog.set_offer(variant_id=variant, field="price", value="99.01", expected_version=1, context=self.seller_context)
        self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["variants"][0]["price"], Decimal("99.01"))

    def test_stale_price_conflict_preserves_new_price(self):
        product, variant, photo = self.product()
        self.catalog.set_offer(variant_id=variant, field="price", value="90", expected_version=1, context=self.seller_context)
        with self.assertRaises(ConcurrentConflict):
            self.catalog.set_offer(variant_id=variant, field="price", value="80", expected_version=1, context=self.seller_context)
        self.assertEqual(self.catalog.get_product(product_id=product, context=self.buyer_context)["variants"][0]["price"], Decimal("90"))

    def test_stock_conflicts_are_per_location_not_price(self):
        product, variant, photo = self.product()
        self.catalog.set_offer(variant_id=variant, field="stock", value="1", expected_version=1, context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, field="price", value="0", expected_version=1, context=self.seller_context)
        with self.assertRaises(ConcurrentConflict):
            self.catalog.set_offer(variant_id=variant, field="stock", value="4", expected_version=1, context=self.seller_context)
        location = self.catalog.create_location(name="Второе место", context=self.seller_context)
        self.catalog.set_offer(variant_id=variant, location_id=location, field="stock", value="3", expected_version=0, context=self.seller_context)
        owned = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.assertEqual(sum(row["quantity"] for row in owned["variants"][0]["stocks"]), Decimal("4"))

    def test_unit_locks_on_zero_price(self):
        product, variant, photo = self.product(price="0", publish=False)
        with self.assertRaises(InputRejected):
            self.catalog.save_product_draft(product_id=product, expected_version=self.revision(product), data={"unit": "kg"}, context=self.seller_context)

    def test_zero_stock_retains_content_and_selected_variant(self):
        product, variant, photo = self.product(stock="0")
        view = self.catalog.get_product(product_id=product, variant_id=variant, context=self.buyer_context)
        self.assertEqual(view["title"], "Куртка")
        self.assertEqual(view["selected_variant_id"], str(variant))
        self.assertFalse(view["variants"][0]["in_stock"])

    def test_withdrawal_hides_last_variant_without_erasing_stock(self):
        product, variant, photo = self.product(stock="6")
        self.catalog.withdraw_variant(variant_id=variant, context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)
        own = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        self.assertEqual(own["variants"][0]["stocks"][0]["quantity"], Decimal("6"))
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)

    def test_return_requires_explicit_new_draft_and_cannot_clear_staff_block(self):
        product, variant, photo = self.product()
        self.catalog.withdraw_variant(variant_id=variant, context=self.seller_context)
        self.catalog.save_variant_draft(
            product_id=product, variant_id=variant, expected_version=self.revision(product), context=self.seller_context,
            data={"label": "Красный S", "attributes": {"color": "Красный", "size": "S"}, "photo_ids": [str(photo)], "restore": True},
        )
        self.catalog.set_variant_block(variant_id=variant, blocked=True, reason="Проверка", context=self.staff_context)
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)

    def test_digital_draft_cannot_be_published(self):
        product, variant, photo = self.product(kind="digital", publish=False)
        with self.assertRaises(InputRejected):
            self.catalog.publish_product(product_id=product, expected_version=self.revision(product), context=self.seller_context)

    def test_other_seller_cannot_edit_or_inspect_owner_data(self):
        product, variant, photo = self.product()
        with self.assertRaises(PermissionDenied):
            self.catalog.get_own_product(product_id=product, context=self.other_context)
        with self.assertRaises(PermissionDenied):
            self.catalog.set_offer(variant_id=variant, field="price", value="1", expected_version=1, context=self.other_context)

    def test_withdrawn_participant_loses_direct_card_and_photo_access(self):
        product, variant, photo = self.product()
        self.catalog.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)
        for action in (
            lambda: self.catalog.get_product(product_id=product, context=self.buyer_context),
            lambda: self.catalog.get_photo(photo_id=photo, context=self.buyer_context),
        ):
            with self.assertRaises(PermissionDenied):
                action()

    def test_suspended_seller_is_hidden_in_current_public_view(self):
        product, variant, photo = self.product()
        apps.get_model("seller_onboarding", "SellerProfile").objects.filter(owner_id=self.seller.id).update(state="suspended")
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)

    def test_fresh_email_verification_does_not_grant_catalog_access(self):
        stranger = self.create_account(kind="ordinary")
        context = self.context(self.create_registry(stranger))
        with self.assertRaises(PermissionDenied):
            self.catalog.list_categories(context=context)

    def test_revoked_session_is_rejected_before_read(self):
        product, variant, photo = self.product()
        self.buyer_registry.revoked_at = self.now
        self.buyer_registry.revoked_reason = "user_revoked"
        self.buyer_registry.save()
        with self.assertRaises(PermissionDenied):
            self.catalog.get_product(product_id=product, context=self.buyer_context)
