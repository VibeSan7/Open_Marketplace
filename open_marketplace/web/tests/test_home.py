from django.test import SimpleTestCase


class HomeTests(SimpleTestCase):
    def test_home_has_real_next_actions_and_demo_notice(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        for text in ("Каталог", "Стать продавцом", "демонстрацион"):
            self.assertContains(response, text)
        self.assertContains(response, 'href="/catalog/"')
        self.assertContains(response, 'href="/seller/"')
        self.assertContains(response, 'href="/setup/"')
        self.assertContains(response, 'href="/register/"')
        self.assertContains(response, "отдельный допуск")
        self.assertContains(response, "Реальные заказы и платежи")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_home_has_one_main_heading_and_no_mutation_form(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1", count=1)
        self.assertNotContains(response, 'method="post"')
        self.assertNotContains(response, 'name="csrfmiddlewaretoken"')

    def test_home_does_not_accept_post(self):
        response = self.client.post("/")

        self.assertEqual(response.status_code, 405)
