from importlib import import_module
from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from open_marketplace.access.tests.test_roles import AccessTestCase


class CatalogTestCase(AccessTestCase):
    def setUp(self):
        self.now = timezone.now()
        try:
            self.catalog = import_module("open_marketplace.catalog.public")
        except ImportError:
            self.fail("Catalog operations have not been implemented.")
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(CATALOG_MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.staff, self.staff_registry, self.staff_context = self.prepare_authorized_actor()
        self.seller, self.seller_registry, self.seller_context = self.make_seller("Первый продавец")
        self.other, self.other_registry, self.other_context = self.make_seller("Другой продавец")
        self.buyer = self.create_account(kind="ordinary")
        self.buyer_registry = self.create_registry(self.buyer)
        self.buyer_context = self.context(self.buyer_registry)
        for account in (self.seller, self.other, self.buyer):
            self.catalog.set_participant(account_id=account.id, allowed=True, context=self.staff_context)
        self.category_id = self.catalog.create_category(
            name="Одежда", attributes=[
                {"key": "color", "label": "Цвет", "required": True, "values": ["Красный", "Синий"]},
                {"key": "size", "label": "Размер", "required": True, "values": ["S", "M", "L"]},
            ], context=self.staff_context,
        )

    def make_seller(self, name):
        account = self.create_account(kind="ordinary")
        self.enable_totp(account)
        application = apps.get_model("seller_onboarding", "SellerApplication").objects.create(
            applicant_id=account.id, state="approved", current_version=1, created_at=self.now,
        )
        apps.get_model("seller_onboarding", "SellerApplicationVersion").objects.create(
            application=application, version_number=1, business_form="self_employed",
            display_name=name, official_name="Тестовая запись", registration_identifier=uuid4().hex,
            contact_email=account.email, test_data_attested=True, submitted_at=self.now,
        )
        apps.get_model("seller_onboarding", "SellerProfile").objects.create(
            owner_id=account.id, application=application, approved_version=1, state="active",
            created_at=self.now, updated_at=self.now,
        )
        registry = self.create_registry(account)
        return account, registry, self.context(registry)

    def revision(self, product_id, context=None):
        return self.catalog.get_own_product(product_id=product_id, context=context or self.seller_context)["draft_version"]

    def image(self):
        from PIL import Image
        out = BytesIO()
        Image.new("RGB", (32, 24), (190, 70, 50)).save(out, format="PNG")
        return SimpleUploadedFile("test-fixture.png", out.getvalue(), content_type="image/png")

    def product(self, *, unit="pc", kind="physical", context=None, title="Куртка", price="120", stock="2", color="Красный", size="S", publish=True):
        context = context or self.seller_context
        product_id = self.catalog.create_product(kind=kind, unit=unit, context=context)
        self.catalog.save_product_draft(
            product_id=product_id, expected_version=self.revision(product_id, context), context=context,
            data={"title": title, "description": "Тёплая зимняя одежда с капюшоном.", "category_id": str(self.category_id), "attributes": {}},
        )
        variant_id = self.catalog.add_variant(
            product_id=product_id, expected_version=self.revision(product_id, context), context=context,
            data={"label": f"{color} {size}", "attributes": {"color": color, "size": size}, "photo_ids": []},
        )
        photo_id = self.catalog.upload_photo(product_id=product_id, uploaded_file=self.image(), attested=True, context=context)
        self.catalog.save_variant_draft(
            product_id=product_id, variant_id=variant_id, expected_version=self.revision(product_id, context), context=context,
            data={"label": f"{color} {size}", "attributes": {"color": color, "size": size}, "photo_ids": [str(photo_id)]},
        )
        self.catalog.set_offer(variant_id=variant_id, field="price", value=price, expected_version=0, context=context)
        self.catalog.set_offer(variant_id=variant_id, field="stock", value=stock, expected_version=0, context=context)
        if publish:
            self.catalog.publish_product(product_id=product_id, expected_version=self.revision(product_id, context), context=context)
        return product_id, variant_id, photo_id
