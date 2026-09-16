from django.test import SimpleTestCase
from django.urls import reverse


class SetupGuideTests(SimpleTestCase):
    def test_setup_guide_is_a_read_only_public_page_with_real_next_steps(self):
        response = self.client.get(reverse("setup-guide"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "setup.html")
        self.assertContains(response, "<h1", count=1)
        self.assertContains(response, 'role="search"')
        self.assertNotContains(response, 'method="post"')
        self.assertNotContains(response, "csrfmiddlewaretoken")
        for name in ("register", "login", "security", "seller-start", "catalog-search", "catalog-manage"):
            self.assertContains(response, f'href="{reverse(name)}"')
        self.assertContains(response, 'href="/admin/"')
        for text in ("искусственные демонстрационные данные", "Mailpit", "допуск", "localhost"):
            self.assertContains(response, text)
        self.assertContains(response, "заказ")
        self.assertContains(response, "оплат")
        self.assertNotContains(response, "настроено и готово")

    def test_setup_guide_does_not_accept_post(self):
        response = self.client.post(reverse("setup-guide"))

        self.assertEqual(response.status_code, 405)
