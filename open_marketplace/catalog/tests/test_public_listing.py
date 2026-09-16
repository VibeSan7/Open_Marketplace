from importlib import import_module
from uuid import uuid4

from django.apps import apps

from open_marketplace.catalog.models import Participant
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, PermissionDenied
from open_marketplace.common.types import OperationContext


class PublicListingTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.public = import_module("open_marketplace.catalog.public")
        self.anonymous_context = OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.20",
            now=self.now,
        )

    def non_admitted_context(self):
        account = self.create_account(kind="ordinary")
        registry = self.create_registry(account)
        return account, self.context(registry)

    def set_public(self, product, enabled, context):
        setter = getattr(self.public, "set_public_listing", None)
        self.assertIsNotNone(setter, "set_public_listing is not implemented")
        return setter(product_id=product, enabled=enabled, context=context)

    def anonymous_search(self, **kwargs):
        try:
            return self.public.search_catalog(context=self.anonymous_context, **kwargs)
        except PermissionDenied as exc:
            self.fail(f"anonymous search was denied: {exc}")

    def anonymous_categories(self):
        try:
            return self.public.list_categories(context=self.anonymous_context)
        except PermissionDenied as exc:
            self.fail(f"anonymous categories were denied: {exc}")

    def test_private_content_is_not_composed_for_anonymous_browsing(self):
        product, variant, photo = self.product(title="Секретный товар")

        self.assertEqual(self.anonymous_search()["items"], [])
        self.assertEqual(self.anonymous_categories(), [])
        for action in (
            lambda: self.public.get_product(product_id=product, context=self.anonymous_context),
            lambda: self.public.get_photo(photo_id=photo, context=self.anonymous_context),
        ):
            with self.assertRaises(PermissionDenied):
                action()

    def test_owner_can_opt_in_published_content_for_anonymous_browsing(self):
        product, variant, photo = self.product(title="Открытый товар")

        self.set_public(product, True, self.seller_context)

        page = self.anonymous_search()
        self.assertEqual([row["id"] for row in page["items"]], [str(product)])
        view = self.public.get_product(product_id=product, context=self.anonymous_context)
        self.assertEqual(view["id"], str(product))
        self.assertEqual(view["selected_variant_id"], str(variant))
        self.assertEqual(view["variants"][0]["photo_ids"], [str(photo)])
        self.public.get_photo(photo_id=photo, context=self.anonymous_context).close()
        self.assertTrue(self.public.get_own_product(product_id=product, context=self.seller_context)["public_listing"])

    def test_public_listing_requires_owner_and_published_eligible_content(self):
        product, variant, photo = self.product()

        with self.assertRaises(PermissionDenied):
            self.set_public(product, True, self.other_context)

        draft, draft_variant, draft_photo = self.product(publish=False)
        with self.assertRaises(InputRejected):
            self.set_public(draft, True, self.seller_context)

    def test_opt_out_hides_content_from_non_admitted_buyer_but_not_legacy_admitted_buyer(self):
        product, variant, photo = self.product()
        self.set_public(product, True, self.seller_context)
        _, non_admitted = self.non_admitted_context()
        self.set_public(product, False, self.seller_context)

        with self.assertRaises(PermissionDenied):
            self.public.get_product(product_id=product, context=non_admitted)
        self.assertEqual(self.anonymous_search()["items"], [])
        self.assertEqual(self.public.get_product(product_id=product, context=self.buyer_context)["id"], str(product))

    def test_participant_revocation_does_not_hide_explicitly_public_content(self):
        product, variant, photo = self.product()
        self.set_public(product, True, self.seller_context)
        self.public.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)

        self.assertEqual(self.public.get_product(product_id=product, context=self.buyer_context)["id"], str(product))
        self.public.set_saved_product(product_id=product, saved=True, context=self.buyer_context)
        self.assertEqual(self.public.list_saved_products(context=self.buyer_context)[0]["id"], str(product))

    def test_verified_non_admitted_buyer_can_browse_public_content_and_get_demo_lock(self):
        product, variant, photo = self.product()
        self.set_public(product, True, self.seller_context)
        account, context = self.non_admitted_context()

        participant = self.public.get_demo_participant(context=context, lock=True)
        self.assertEqual(participant.id, account.id)
        self.assertFalse(Participant.objects.get(account_id=account.id).allowed)
        offer = self.public.get_demo_offer_snapshot(variant_id=variant, context=context)
        self.assertEqual(offer["product_id"], product)

    def test_public_composition_excludes_private_category_and_suggestion_sources(self):
        public_product, public_variant, public_photo = self.product(title="Куртка открытая")
        self.set_public(public_product, True, self.seller_context)
        private_product, private_variant, private_photo = self.product(title="Секретныесапоги", context=self.other_context)
        hidden_category = self.public.create_category(
            name="Секретная категория",
            attributes=[
                {"key": "color", "label": "Цвет", "required": True, "values": ["Красный", "Синий"]},
                {"key": "size", "label": "Размер", "required": True, "values": ["S", "M", "L"]},
            ],
            context=self.staff_context,
        )
        self.public.save_product_draft(
            product_id=private_product,
            expected_version=self.revision(private_product, self.other_context),
            data={"category_id": str(hidden_category)},
            context=self.other_context,
        )
        self.public.publish_product(
            product_id=private_product,
            expected_version=self.revision(private_product, self.other_context),
            context=self.other_context,
        )

        page = self.anonymous_search(query="Секретныесапоги")
        self.assertEqual(page["items"], [])
        self.assertIsNone(page["suggestion"])
        self.assertNotIn(str(hidden_category), {row["id"] for row in self.anonymous_categories()})

    def test_draft_withdrawn_blocked_inactive_and_suspended_content_is_not_public(self):
        product, variant, photo = self.product()
        self.set_public(product, True, self.seller_context)

        self.public.set_product_block(product_id=product, blocked=True, reason="Проверка", context=self.staff_context)
        with self.assertRaises(PermissionDenied):
            self.public.get_product(product_id=product, context=self.anonymous_context)

        self.public.set_product_block(product_id=product, blocked=False, reason="Снято", context=self.staff_context)
        self.public.withdraw_variant(variant_id=variant, context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.public.get_product(product_id=product, context=self.anonymous_context)

        product, variant, photo = self.product(context=self.other_context)
        self.set_public(product, True, self.other_context)
        apps.get_model("seller_onboarding", "SellerProfile").objects.filter(owner_id=self.other.id).update(state="suspended")
        with self.assertRaises(PermissionDenied):
            self.public.get_product(product_id=product, context=self.anonymous_context)

    def test_inactive_category_removes_opted_in_product_from_public_composition(self):
        product, variant, photo = self.product()
        self.set_public(product, True, self.seller_context)
        category = self.public.list_categories(context=self.staff_context)[0]
        self.public.update_category(
            category_id=category["id"],
            name=category["name"],
            attributes=category["attributes"],
            active=False,
            expected_version=category["version"],
            context=self.staff_context,
        )

        with self.assertRaises(PermissionDenied):
            self.public.get_product(product_id=product, context=self.anonymous_context)

    def test_unpublished_photo_never_becomes_public_with_public_product(self):
        product, variant, original = self.product()
        self.set_public(product, True, self.seller_context)
        replacement = self.public.upload_photo(product_id=product, uploaded_file=self.image(), attested=True, context=self.seller_context)
        self.public.save_product_draft(
            product_id=product,
            expected_version=self.revision(product),
            data={"cover_id": str(replacement)},
            context=self.seller_context,
        )

        view = self.public.get_product(product_id=product, context=self.anonymous_context)
        self.assertEqual(view["cover_id"], str(original))
        with self.assertRaises(PermissionDenied):
            self.public.get_photo(photo_id=replacement, context=self.anonymous_context)

    def test_linked_offer_requires_public_source_and_target(self):
        from open_marketplace.catalog.tests.test_common_cards import CommonCardTests

        common, common_variant, common_photo = CommonCardTests.common(self)
        source, source_variant, source_photo = self.product()
        CommonCardTests.match(self, source_variant, common_variant)
        self.set_public(common, True, self.staff_context)
        self.assertEqual(self.anonymous_search()["items"], [])

        self.set_public(source, True, self.seller_context)
        page = self.anonymous_search()
        self.assertEqual([row["id"] for row in page["items"]], [str(common)])
        view = self.public.get_product(product_id=common, context=self.anonymous_context)
        self.assertTrue(view["variants"][0]["offers"])
