from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, PermissionDenied


class CatalogPhotoTests(CatalogTestCase):
    def test_mislabeled_html_is_not_accepted_as_a_photo(self):
        product = self.catalog.create_product(kind="physical", unit="pc", context=self.seller_context)
        upload = SimpleUploadedFile("real.jpg", b"<svg onload='alert(1)'/>", content_type="image/jpeg")
        with self.assertRaises(InputRejected):
            self.catalog.upload_photo(product_id=product, uploaded_file=upload, attested=True, context=self.seller_context)

    def test_attestation_is_required_not_inferred_from_filename(self):
        product = self.catalog.create_product(kind="physical", unit="pc", context=self.seller_context)
        with self.assertRaises(InputRejected):
            self.catalog.upload_photo(product_id=product, uploaded_file=self.image(), attested=False, context=self.seller_context)

    def test_foreign_photo_cannot_be_published_in_own_card(self):
        product, variant, photo = self.product()
        foreign, foreign_variant, foreign_photo = self.product(context=self.other_context)
        with self.assertRaises(InputRejected):
            self.catalog.save_variant_draft(product_id=product, variant_id=variant, expected_version=self.revision(product), context=self.seller_context,
                data={"label": "Красный S", "attributes": {"color": "Красный", "size": "S"}, "photo_ids": [str(foreign_photo)]})

    def test_draft_photo_is_private_until_its_variant_is_published(self):
        product, variant, photo = self.product(publish=False)
        with self.assertRaises(PermissionDenied):
            self.catalog.get_photo(photo_id=photo, context=self.buyer_context)
        file = self.catalog.get_photo(photo_id=photo, context=self.seller_context)
        try:
            self.assertTrue(file.read().startswith(b"\x89PNG\r\n\x1a\n"))
        finally:
            file.close()

    def test_metadata_and_user_supplied_path_are_not_preserved(self):
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        product = self.catalog.create_product(kind="physical", unit="pc", context=self.seller_context)
        metadata = PngInfo()
        metadata.add_text("private-marker", "location-not-for-publication")
        out = BytesIO()
        Image.new("RGB", (16, 16)).save(out, format="PNG", pnginfo=metadata)
        photo = self.catalog.upload_photo(product_id=product, uploaded_file=SimpleUploadedFile("../../original.png", out.getvalue()), attested=True, context=self.seller_context)
        file = self.catalog.get_photo(photo_id=photo, context=self.seller_context)
        try:
            self.assertNotIn(b"location-not-for-publication", file.read())
        finally:
            file.close()

    def test_missing_public_photo_is_not_replaced_by_another_variant_photo(self):
        product, variant, photo = self.product()
        file = self.catalog.get_photo(photo_id=photo, context=self.seller_context)
        path = file.name
        file.close()
        from pathlib import Path
        Path(path).unlink()
        view = self.catalog.get_product(product_id=product, context=self.buyer_context)
        self.assertEqual(view["variants"][0]["photo_ids"], [])
