from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client

from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class CatalogWebTests(CatalogTestCase):
    def client_for(self, registry):
        session = SessionStore(session_key=registry.django_session_key)
        session["account_id"] = str(registry.account_id)
        session["session_id"] = str(registry.id)
        session.save()
        client = Client(enforce_csrf_checks=True)
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        return client

    def test_buyer_can_browse_and_open_but_cannot_see_exact_stock(self):
        product, variant, photo = self.product(stock="987654321012345")
        client = self.client_for(self.buyer_registry)
        page = client.get("/catalog/")
        self.assertContains(page, "Куртка")
        self.assertContains(page, "Общее фото товара")
        self.assertNotContains(page, "987654321012345")
        detail = client.get(f"/catalog/p/{product}/?variant={variant}")
        self.assertContains(detail, "Красный S")
        self.assertNotContains(detail, "987654321012345")

    def test_unknown_url_filter_is_an_error_not_a_fake_empty_search(self):
        client = self.client_for(self.buyer_registry)
        response = client.get("/catalog/?f.unsupported=x")
        self.assertEqual(response.status_code, 400)
        self.assertIn("фильтр", response.content.decode().casefold())

    def test_invalid_condition_can_be_removed_without_losing_query_or_valid_filters(self):
        from urllib.parse import parse_qs, urlsplit

        self.product()
        client = self.client_for(self.buyer_registry)
        response = client.get("/catalog/", {
            "q": "Куртка", "f.color": "Красный", "f.unsupported": "ошибка",
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'name="q" value="Куртка"', status_code=400)
        self.assertContains(response, 'name="f.color" value="Красный"', status_code=400)
        self.assertContains(response, 'name="f.unsupported" value="ошибка"', status_code=400)
        conditions = response.context.get("conditions", [])
        invalid = next((row for row in conditions if row["name"] == "f.unsupported"), None)
        self.assertIsNotNone(invalid, "The error page needs an explicit single-condition removal action.")
        self.assertEqual(parse_qs(urlsplit(invalid["remove_url"]).query), {"q": ["Куртка"], "f.color": ["Красный"]})
        corrected = client.get(invalid["remove_url"])
        self.assertContains(corrected, "Куртка")
        self.assertEqual(corrected.context["search"]["filters"], {"color": ["Красный"]})

    def test_zero_stock_selected_variant_has_status_but_no_available_offer(self):
        product, variant, photo = self.product(stock="0")
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product}/?variant={variant}")
        self.assertContains(response, "Нет в наличии")
        self.assertNotContains(response, "<h3>Предложения</h3>")

    def test_a_session_without_catalog_admission_cannot_receive_content(self):
        product, variant, photo = self.product()
        self.catalog.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)
        client = self.client_for(self.buyer_registry)
        response = client.get("/catalog/")
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "Куртка", status_code=403)
        response = client.get(f"/catalog/photo/{photo}/")
        self.assertIn(response.status_code, (403, 404))

    def test_own_page_and_management_page_have_real_forms(self):
        product, variant, photo = self.product()
        client = self.client_for(self.seller_registry)
        page = client.get(f"/catalog/own/{product}/")
        self.assertContains(page, "csrfmiddlewaretoken")
        self.assertContains(page, "Опубликовать")
        self.assertContains(page, "Остаток")
        self.assertEqual(self.client_for(self.staff_registry).get("/catalog/manage/").status_code, 200)
        self.assertEqual(self.client_for(self.buyer_registry).get("/catalog/manage/").status_code, 403)

    def test_photo_is_png_private_no_store_and_not_a_path_redirect(self):
        product, variant, photo = self.product()
        client = self.client_for(self.buyer_registry)
        response = client.get(f"/catalog/photo/{photo}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("Location", response)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))

    def test_catalog_mutations_require_csrf(self):
        product, variant, photo = self.product()
        client = self.client_for(self.seller_registry)
        response = client.post(f"/catalog/own/{product}/", {"action": "withdraw_all"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.catalog.get_product(product_id=product, context=self.buyer_context))

    def test_user_content_is_escaped(self):
        product, variant, photo = self.product(title='<script>alert("xss")</script>')
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<script>alert("xss")</script>')
        self.assertContains(response, "&lt;script&gt;")
