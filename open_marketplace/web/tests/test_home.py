from django.test import TestCase, override_settings


class HomeTests(TestCase):
    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_home_has_real_next_actions_and_demo_notice(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        for target in ("/catalog/", "/seller/", "/setup/", "/register/", "/cart/", "/demo-content/credits/"):
            self.assertContains(response, f'href="{target}"')
        self.assertContains(response, "не списывают деньги")
        self.assertContains(response, "без регистрации")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_home_has_one_main_heading_and_no_mutation_form(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1", count=1)
        self.assertNotContains(response, 'method="post"')
        self.assertNotContains(response, 'name="csrfmiddlewaretoken"')

    def test_home_does_not_accept_post(self):
        self.assertEqual(self.client.post("/").status_code, 405)
