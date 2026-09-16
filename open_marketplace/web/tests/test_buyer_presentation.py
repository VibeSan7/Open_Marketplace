from django.template.loader import render_to_string
from django.test import SimpleTestCase


class BuyerPresentationTests(SimpleTestCase):
    def test_buyer_lists_load_the_catalogue_stylesheet(self):
        for template, data in (("catalog/saved.html", {"products": []}),
                               ("catalog/seller.html", {"store": {"seller": {"display_name": "Тест"}, "products": []}})):
            with self.subTest(template=template):
                html = render_to_string(template, data)
                self.assertIn('href="/static/catalog/catalog.css"', html)
