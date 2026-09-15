from decimal import Decimal
from importlib import import_module

from django.test import SimpleTestCase

from open_marketplace.common.errors import InputRejected


class CatalogNumberTests(SimpleTestCase):
    def setUp(self):
        try:
            self.domain = import_module("open_marketplace.catalog.domain")
        except ImportError:
            self.fail("Catalog number validation has not been implemented.")

    def test_price_keeps_cents_and_accepts_comma_or_dot(self):
        for raw, expected in (("12,34", "12.34"), ("12.3", "12.30"), ("12", "12.00"), ("12.3400", "12.34")):
            with self.subTest(raw=raw):
                self.assertEqual(self.domain.price_value(raw), Decimal(expected))

    def test_empty_draft_price_is_not_free(self):
        self.assertIsNone(self.domain.price_value("", allow_empty=True))
        self.assertEqual(self.domain.price_value("0"), Decimal("0"))
        with self.assertRaises(InputRejected):
            self.domain.price_value("")

    def test_price_rejects_loss_of_precision_and_invalid_numbers(self):
        for value in ("12.3456", "-1", "NaN", "Infinity", "1e3", "1,2.3", "1 000", "9" * 17, True, 1.25):
            with self.subTest(value=value):
                with self.assertRaises(InputRejected):
                    self.domain.price_value(value)

    def test_quantities_preserve_millimeters_and_grams(self):
        for unit in ("kg", "m"):
            for value in ("1.234", "1,5", "0", "2.0000"):
                with self.subTest(unit=unit, value=value):
                    self.assertEqual(self.domain.stock_value(value, unit), Decimal(value.replace(",", ".")))

    def test_quantity_never_rounds_to_zero_or_to_another_quantity(self):
        for unit in ("kg", "m"):
            for value in ("0.0004", "1.2345", "-0.001", "NaN"):
                with self.subTest(unit=unit, value=value):
                    with self.assertRaises(InputRejected):
                        self.domain.stock_value(value, unit)

    def test_pieces_are_integral_and_unit_is_validated(self):
        self.assertEqual(self.domain.stock_value("2.000", "pc"), Decimal("2"))
        with self.assertRaises(InputRejected):
            self.domain.stock_value("1.5", "pc")
        with self.assertRaises(InputRejected):
            self.domain.stock_value("1", "liter")

    def test_non_ruble_currency_is_not_relabelled(self):
        with self.assertRaises(InputRejected):
            self.domain.price_value("1", currency="USD")

    def test_display_distinguishes_free_from_mixed_price(self):
        self.assertEqual(self.domain.price_label(Decimal("0")), "Бесплатно")
        self.assertEqual(self.domain.price_label(Decimal("12.34")), "12,34 ₽")
        self.assertEqual(self.domain.price_label(Decimal("0"), different=True), "от 0,00 ₽")
