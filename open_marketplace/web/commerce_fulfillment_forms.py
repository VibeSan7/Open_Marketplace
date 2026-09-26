from django import forms
from django.forms import formset_factory


class FulfillmentPackageForm(forms.Form):
    weight_grams = forms.IntegerField(label="Вес, г", min_value=1)
    length_cm = forms.IntegerField(label="Длина, см", min_value=1)
    width_cm = forms.IntegerField(label="Ширина, см", min_value=1)
    height_cm = forms.IntegerField(label="Высота, см", min_value=1)


FulfillmentPackageFormSet = formset_factory(
    FulfillmentPackageForm,
    can_delete=True,
    extra=1,
    max_num=32,
    validate_max=True,
)
