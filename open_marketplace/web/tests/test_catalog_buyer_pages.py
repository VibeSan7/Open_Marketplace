from django.apps import apps
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class CatalogBuyerPagesTests(CatalogTestCase):
    def client_for(self, registry):
        session = SessionStore(session_key=registry.django_session_key)
        session["account_id"] = str(registry.account_id)
        session["session_id"] = str(registry.id)
        session.save()
        client = Client(enforce_csrf_checks=True)
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        return client

    def seller_id(self, account):
        return apps.get_model("seller_onboarding", "SellerProfile").objects.get(owner_id=account.id).id

    def csrf_post(self, client, url, data, product_id):
        client.get(reverse("catalog-product", kwargs={"product_id": product_id}))
        return client.post(url, {**data, "csrfmiddlewaretoken": client.cookies["csrftoken"].value})

    def test_saved_page_is_personal_and_uses_live_escaped_summary(self):
        product, _, _ = self.product(title='<script>alert("xss")</script>')
        self.catalog.set_saved_product(product_id=product, saved=True, context=self.buyer_context)

        response = self.client_for(self.buyer_registry).get(reverse("catalog-saved"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Избранное")
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, 'name="action" value="remove"')
        self.assertNotContains(response, '<script>alert("xss")</script>')
        self.assertIn("no-store", response["Cache-Control"])

    def test_save_is_post_only_csrf_protected_and_redirects_to_fixed_list(self):
        product, _, _ = self.product()
        client = self.client_for(self.buyer_registry)
        url = reverse("catalog-save-product", kwargs={"product_id": product})

        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url, {"action": "save"}).status_code, 403)
        response = self.csrf_post(client, url, {"action": "save"}, product)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("catalog-saved"))
        self.assertEqual([item["id"] for item in self.catalog.list_saved_products(context=self.buyer_context)], [str(product)])

    def test_save_form_rejects_malformed_or_duplicated_action(self):
        product, _, _ = self.product()
        client = self.client_for(self.buyer_registry)
        url = reverse("catalog-save-product", kwargs={"product_id": product})
        client.get(reverse("catalog-product", kwargs={"product_id": product}))
        csrf = client.cookies["csrftoken"].value

        duplicate = QueryDict(mutable=True)
        duplicate.setlist("action", ["save", "remove"])
        duplicate["csrfmiddlewaretoken"] = csrf
        for data in ({"action": "toggle"}, duplicate):
            with self.subTest(data=data):
                payload = {**data, "csrfmiddlewaretoken": csrf} if isinstance(data, dict) else data
                response = client.post(url, payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.catalog.list_saved_products(context=self.buyer_context), [])

    def test_product_and_store_pages_link_to_public_seller(self):
        product, _, _ = self.product(title="Пальто")
        seller_id = self.seller_id(self.seller)
        client = self.client_for(self.buyer_registry)

        product_page = client.get(reverse("catalog-product", kwargs={"product_id": product}))
        store_page = client.get(reverse("catalog-seller", kwargs={"seller_id": seller_id}))

        self.assertContains(product_page, reverse("catalog-seller", kwargs={"seller_id": seller_id}))
        self.assertContains(product_page, 'name="action" value="save"')
        self.assertContains(store_page, "Первый продавец")
        self.assertContains(store_page, "Каталог для тестирования")
        self.assertContains(store_page, "Доставка, возвраты и оформление заказов пока не настроены")
        self.assertContains(store_page, "Пальто")
        self.assertNotContains(store_page, self.seller.email)

    def test_header_has_saved_link_without_a_global_post_form(self):
        response = self.client_for(self.buyer_registry).get(reverse("catalog-search"))
        header = response.content.decode().partition("<main")[0]

        self.assertContains(response, f'href="{reverse("catalog-saved")}"')
        self.assertNotIn("<form", header)

    def test_removal_is_owner_scoped(self):
        product, _, _ = self.product()
        client = self.client_for(self.buyer_registry)
        url = reverse("catalog-save-product", kwargs={"product_id": product})
        self.csrf_post(client, url, {"action": "save"}, product)
        self.csrf_post(client, url, {"action": "remove"}, product)

        self.assertEqual(self.catalog.list_saved_products(context=self.buyer_context), [])
        self.assertEqual(self.catalog.list_saved_products(context=self.other_context), [])
