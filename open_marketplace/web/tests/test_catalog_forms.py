from django.test import SimpleTestCase

from open_marketplace.web.catalog_forms import AttributeFormSet, ProductDraftForm


class CatalogWebFormTests(SimpleTestCase):
    def test_product_draft_form_maps_category_attributes_to_public_mapping(self):
        categories = [{
            "id": "category-1",
            "name": "Одежда",
            "active": True,
            "version": 1,
            "attributes": [
                {"key": "color", "label": "Цвет", "required": True, "values": ["Красный", "Синий"]},
                {"key": "brand", "label": "Бренд", "required": False, "values": []},
            ],
        }]
        form = ProductDraftForm(categories=categories, data={
            "title": "Куртка",
            "description": "Описание",
            "category_id": "category-1",
            "attr_color": "Красный",
            "attr_brand": "Nord",
            "unit": "pc",
            "expected_version": "0",
        })

        self.assertTrue(form.is_valid())
        self.assertEqual(form.public_attributes(), {"color": "Красный", "brand": "Nord"})

    def test_attribute_formset_turns_choices_into_backend_definitions(self):
        formset = AttributeFormSet(prefix="attributes", data={
            "attributes-TOTAL_FORMS": "1",
            "attributes-INITIAL_FORMS": "0",
            "attributes-MIN_NUM_FORMS": "0",
            "attributes-MAX_NUM_FORMS": "50",
            "attributes-0-label": "Цвет",
            "attributes-0-key": "color",
            "attributes-0-required": "on",
            "attributes-0-choices": "Красный\nСиний",
        })

        self.assertTrue(formset.is_valid())
        self.assertEqual(formset.as_definitions(), [{
            "key": "color",
            "label": "Цвет",
            "required": True,
            "values": ["Красный", "Синий"],
        }])
