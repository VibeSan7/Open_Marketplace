from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.contrib.auth.models import AnonymousUser


class StorefrontPresentationTests(TestCase):
    def test_home_exposes_explore_storefront_contract(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-storefront')
        self.assertContains(response, 'data-storefront-grid')
        self.assertContains(response, "Каталог товаров")
        self.assertContains(response, "Витрина пока пуста")

    def test_global_header_search_and_buyer_navigation_are_available(self):
        response = self.client.get("/")
        header = response.content.decode().partition("<main")[0]

        self.assertIn('action="/catalog/"', header)
        self.assertIn('name="q"', header)
        self.assertIn('href="/catalog/saved/"', header)
        self.assertIn('href="/cart/"', header)
        self.assertIn('href="/login/"', header)

    def test_catalog_page_keeps_one_search_form_and_async_result_hooks(self):
        request = RequestFactory().get("/catalog/")
        request.user = AnonymousUser()
        request.resolver_match = type("ResolverMatch", (), {"url_name": "catalog-search"})()
        html = render_to_string(
            "catalog/search.html",
            {
                "search": {
                    "query": "",
                    "price_min": None,
                    "price_max": None,
                    "sort": "relevance",
                    "categories": [],
                    "category_id": None,
                    "facets": [],
                    "suggestion": None,
                    "items": [],
                    "total": 0,
                    "next_cursor": None,
                },
                "applied_url": "/catalog/",
                "next_url": "/catalog/",
            },
            request=request,
        )

        self.assertNotIn('class="global-search"', html)
        self.assertIn('data-results', html)
        self.assertIn('data-items', html)
        self.assertIn('data-next-cursor', html)
