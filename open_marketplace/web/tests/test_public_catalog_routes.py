from django.apps import apps
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class PublicCatalogRoutesTests(CatalogTestCase):
    def client_for(self, registry, *, csrf=False):
        session = SessionStore(session_key=registry.django_session_key)
        session["account_id"] = str(registry.account_id)
        session["session_id"] = str(registry.id)
        session.save()
        client = Client(enforce_csrf_checks=csrf)
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        return client

    def test_anonymous_catalog_is_a_page_not_a_login_redirect(self):
        response = Client().get(reverse("catalog-search"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])

    def test_owner_opt_in_exposes_only_published_content_and_opt_out_hides_photo(self):
        product_id, _, photo_id = self.product(title="Опубликованная куртка")
        model = apps.get_model("catalog", "Product")
        product = model.objects.get(pk=product_id)
        product.draft["title"] = "Секретный новый черновик"
        product.save(update_fields=("draft",))
        owner = self.client_for(self.seller_registry, csrf=True)
        editor = reverse("catalog-own-product", kwargs={"product_id": product_id})
        owner.get(editor)
        token = owner.cookies["csrftoken"].value
        response = owner.post(editor, {"action": "set_public_listing", "enabled": "true", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 303)
        detail = reverse("catalog-product", kwargs={"product_id": product_id})
        guest = Client()
        page = guest.get(detail)
        self.assertContains(page, "Опубликованная куртка")
        self.assertNotContains(page, "Секретный новый черновик")
        photo_url = reverse("catalog-photo", kwargs={"photo_id": photo_id})
        image = guest.get(photo_url)
        self.assertEqual(image.status_code, 200)
        self.assertTrue(b"".join(image.streaming_content).startswith(b"\x89PNG"))
        self.assertEqual(owner.post(editor, {"action": "set_public_listing", "enabled": "false", "csrfmiddlewaretoken": token}).status_code, 303)
        self.assertEqual(guest.get(detail).status_code, 403)
        self.assertEqual(guest.get(photo_url).status_code, 403)
        self.assertEqual(self.client_for(self.buyer_registry).get(detail).status_code, 200)

    def test_opt_in_requires_csrf_and_owner(self):
        product_id, _, _ = self.product()
        editor = reverse("catalog-own-product", kwargs={"product_id": product_id})
        payload = {"action": "set_public_listing", "enabled": "true"}
        self.assertEqual(self.client_for(self.seller_registry, csrf=True).post(editor, payload).status_code, 403)
        self.assertEqual(self.client_for(self.other_registry).post(editor, payload).status_code, 403)
        self.assertEqual(Client(enforce_csrf_checks=True).post(editor, payload).status_code, 403)

    def test_revoked_seller_is_hidden_from_guests_too(self):
        product_id, _, photo_id = self.product()
        self.catalog.set_public_listing(product_id=product_id, enabled=True, context=self.seller_context)
        self.catalog.set_participant(account_id=self.seller.id, allowed=False, context=self.staff_context)
        guest = Client()
        self.assertEqual(guest.get(reverse("catalog-product", kwargs={"product_id": product_id})).status_code, 403)
        self.assertEqual(guest.get(reverse("catalog-photo", kwargs={"photo_id": photo_id})).status_code, 403)

    def test_toggle_rejects_ambiguous_input(self):
        product_id, _, _ = self.product()
        editor = reverse("catalog-own-product", kwargs={"product_id": product_id})
        owner = self.client_for(self.seller_registry)
        duplicate = QueryDict(mutable=True)
        duplicate["action"] = "set_public_listing"
        duplicate.setlist("enabled", ["true", "false"])
        for payload in ({"action": "set_public_listing", "enabled": "yes"},
                        {"action": "set_public_listing", "enabled": "true", "owner_id": str(self.other.id)}):
            with self.subTest(payload=payload):
                self.assertEqual(owner.post(editor, payload).status_code, 400)
        self.assertEqual(owner.post(editor, duplicate.urlencode(), content_type="application/x-www-form-urlencoded").status_code, 400)
        product = self.catalog.get_own_product(product_id=product_id, context=self.seller_context)
        self.assertFalse(product.get("public_listing", False))
