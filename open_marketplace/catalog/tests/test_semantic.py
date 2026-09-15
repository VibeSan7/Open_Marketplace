from importlib import import_module

from django.test import SimpleTestCase


class SemanticSearchTests(SimpleTestCase):
    def test_real_multilingual_model_matches_meaning_not_only_spelling(self):
        try:
            semantic = import_module("open_marketplace.catalog.semantic")
        except ImportError:
            self.fail("Local semantic search has not been implemented.")
        scores = semantic.similarities("обувь для бега", ["Кроссовки с дышащей сеткой и упругой подошвой", "Фарфоровая чашка для чая"])
        self.assertEqual(len(scores), 2)
        self.assertGreater(scores[0], scores[1])
        self.assertGreaterEqual(scores[0], semantic.MIN_SIMILARITY)

    def test_real_model_covers_multiple_product_families(self):
        semantic = import_module("open_marketplace.catalog.semantic")
        cases = (
            ("детский транспорт", "Трёхколёсный велосипед для малышей", "Набор столовых вилок"),
            ("сумка для поездок", "Дорожный рюкзак с отделением для ноутбука", "Настольная лампа"),
            ("winter jacket", "Зимняя куртка с утеплителем", "Фарфоровая чашка для чая"),
        )
        for query, relevant, unrelated in cases:
            with self.subTest(query=query):
                positive, negative = semantic.similarities(query, [relevant, unrelated])
                self.assertGreaterEqual(positive, semantic.MIN_SIMILARITY)
                self.assertGreater(positive, negative)

    def test_real_embeddings_return_finite_bounded_scores(self):
        try:
            semantic = import_module("open_marketplace.catalog.semantic")
        except ImportError:
            self.fail("Local semantic search has not been implemented.")
        scores = semantic.similarities("зимняя куртка", ["зимняя куртка", "тёплая одежда для мороза", "USB кабель"])
        self.assertAlmostEqual(scores[0], 1.0, places=4)
        self.assertTrue(all(-1.0 <= value <= 1.0 for value in scores))
        self.assertGreater(scores[1], scores[2])
