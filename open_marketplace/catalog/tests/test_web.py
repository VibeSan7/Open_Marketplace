from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client
from django.urls import reverse

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

    def test_buyer_navigation_does_not_offer_a_forbidden_card_editor(self):
        response = self.client_for(self.buyer_registry).get("/")
        self.assertContains(response, 'href="/seller/"')
        self.assertNotContains(response, 'href="/catalog/own/"')

    def test_admitted_seller_start_leads_to_cards_not_another_application(self):
        response = self.client_for(self.seller_registry).get("/seller/")
        self.assertContains(response, "Допуск продавца активен")
        self.assertContains(response, 'href="/catalog/own/"')
        self.assertNotContains(response, 'href="' + reverse("seller-application-create") + '"')

    def test_own_list_has_understandable_state_price_and_availability(self):
        self.product(title="Бесплатный черновик", price="0", stock="0", publish=False)
        response = self.client_for(self.seller_registry).get("/catalog/own/")
        self.assertContains(response, "Черновик")
        self.assertContains(response, "Физический товар")
        self.assertContains(response, "Бесплатно")
        self.assertContains(response, "Нет в наличии")

    def test_editor_checks_saved_draft_and_does_not_link_to_missing_public_page(self):
        product, _, _ = self.product(publish=False)
        response = self.client_for(self.seller_registry).get(f"/catalog/own/{product}/")
        self.assertContains(response, "Проверка перед публикацией")
        self.assertContains(response, "последний сохранённый черновик")
        self.assertContains(response, f'href="/catalog/own/{product}/preview/"')
        self.assertNotContains(response, f'href="/catalog/p/{product}/"')

    def test_preview_shows_own_draft_without_publication_or_exact_stock(self):
        product, _, _ = self.product(title="Новый черновик", stock="987654321012345", publish=False)
        before = self.catalog.get_own_product(product_id=product, context=self.seller_context)
        client = self.client_for(self.seller_registry)
        response = client.get(f"/catalog/own/{product}/preview/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Предпросмотр сохранённого черновика")
        self.assertContains(response, "Новый черновик")
        self.assertContains(response, "Красный S")
        self.assertNotContains(response, "987654321012345")
        self.assertNotContains(response, "<form")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(before, self.catalog.get_own_product(product_id=product, context=self.seller_context))
        self.assertEqual(self.client_for(self.buyer_registry).get(f"/catalog/p/{product}/").status_code, 403)

    def test_preview_of_foreign_and_unknown_cards_has_same_response(self):
        from uuid import uuid4

        product, _, _ = self.product()
        client = self.client_for(self.other_registry)
        foreign = client.get(f"/catalog/own/{product}/preview/")
        unknown = client.get(f"/catalog/own/{uuid4()}/preview/")
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(unknown.status_code, 403)
        self.assertEqual(foreign.content, unknown.content)

    def test_incomplete_draft_preview_cannot_claim_ready(self):
        product = self.catalog.create_product(kind="physical", unit="pc", context=self.seller_context)
        response = self.client_for(self.seller_registry).get(f"/catalog/own/{product}/preview/")
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "Готово к публикации", status_code=400)

    def test_user_content_is_escaped(self):
        product, variant, photo = self.product(title='<script>alert("xss")</script>')
        response = self.client_for(self.buyer_registry).get(f"/catalog/p/{product}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<script>alert("xss")</script>')
        self.assertContains(response, "&lt;script&gt;")
