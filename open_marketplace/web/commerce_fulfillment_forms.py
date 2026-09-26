from django import forms
from django.forms import formset_factory


class FulfillmentPackageForm(forms.Form):
    weight_grams = forms.IntegerField(label="Вес, г", min_value=1)
    length_cm = forms.IntegerField(label="Длина, см", min_value=1)
    width_cm = forms.IntegerField(label="Ширина, см", min_value=1)
    height_cm = forms.IntegerField(label="Высота, см", min_value=1)

    def __init__(self, *args, line_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        for line_index, label in line_choices:
            self.fields[f"line_{line_index}"] = forms.CharField(
                label=label,
                required=False,
            )


FulfillmentPackageFormSet = formset_factory(
    FulfillmentPackageForm,
    can_delete=True,
    extra=1,
    max_num=32,
    validate_max=True,
)


def _line_label(line, *, index):
    title = line.get("title", "Товар")
    variant = line.get("variant_label", "")
    unit = line.get("unit", "")
    suffix = f" · {variant}" if variant else ""
    return f"{index + 1}. {title}{suffix} — количество ({unit}), всего {line.get('quantity', '')}"


def fulfillment_package_formset(*, data=None, packages=(), lines=()):
    line_choices = tuple(
        (index, _line_label(line, index=index))
        for index, line in enumerate(lines)
    )
    initial = []
    for package in packages:
        row = {
            field: package[field]
            for field in ("weight_grams", "length_cm", "width_cm", "height_cm")
        }
        for item in package.get("items", ()):
            row[f"line_{item['line_index']}"] = item["quantity"]
        initial.append(row)
    return FulfillmentPackageFormSet(
        data=data,
        initial=tuple(initial),
        prefix="packages",
        form_kwargs={"line_choices": line_choices},
    )
