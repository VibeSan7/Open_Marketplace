from django import forms
from django.forms import formset_factory
from django.utils.text import slugify


UNITS = (("pc", "шт."), ("kg", "кг"), ("m", "м"))


def _category_attributes(categories, category_id):
    for category in categories:
        if str(category["id"]) == str(category_id):
            return category.get("attributes", ())
    return ()


class ProductCreateForm(forms.Form):
    kind = forms.ChoiceField(choices=(
        ("physical", "Физический товар"),
        ("digital", "Цифровой черновик"),
        ("common", "Общая карточка (для сотрудников)"),
    ))
    unit = forms.ChoiceField(choices=UNITS)


class ProductDraftForm(forms.Form):
    title = forms.CharField(max_length=200, required=False, label="Название")
    description = forms.CharField(max_length=10000, required=False, label="Описание", widget=forms.Textarea)
    category_id = forms.ChoiceField(choices=(), required=False, label="Категория")
    unit = forms.ChoiceField(choices=UNITS, label="Единица")
    cover_id = forms.ChoiceField(choices=(("", "Автоматически по первому фото"),), required=False, label="Обложка")
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *, categories, initial=None, data=None, photos=(), **kwargs):
        initial = initial or {}
        super().__init__(data=data, initial=initial, **kwargs)
        self.categories = categories
        self.fields["category_id"].choices = [
            (category["id"], category["name"] + (" (неактивна)" if not category.get("active", True) else ""))
            for category in categories
        ]
        self.fields["cover_id"].choices = [("", "Автоматически по первому фото")] + [
            (str(photo["id"]), f"Фото {index + 1}") for index, photo in enumerate(photos)
        ]
        category_id = (data or {}).get("category_id") or initial.get("category_id")
        attributes = initial.get("attributes", {})
        for definition in _category_attributes(categories, category_id):
            key = definition["key"]
            field = (
                forms.ChoiceField(
                    choices=[("", "—")] + [(value, value) for value in definition.get("values", ())],
                    required=False,
                    label=definition["label"],
                )
                if definition.get("values")
                else forms.CharField(max_length=256, required=False, label=definition["label"])
            )
            field.initial = attributes.get(key, "")
            self.fields[f"attr_{key}"] = field

    def public_attributes(self):
        return {key[5:]: value for key, value in self.cleaned_data.items() if key.startswith("attr_") and value}


class VariantDraftForm(forms.Form):
    label = forms.CharField(max_length=200, required=False, label="Название варианта")
    restore = forms.BooleanField(required=False, label="Явно вернуть снятый вариант")
    photo_ids = forms.MultipleChoiceField(choices=(), required=False, label="Фотографии варианта", widget=forms.CheckboxSelectMultiple)
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *, categories, category_id, photos=(), initial=None, data=None, **kwargs):
        initial = initial or {}
        super().__init__(data=data, initial=initial, **kwargs)
        self.fields["photo_ids"].choices = [(str(photo["id"]), f"Фото {index + 1}") for index, photo in enumerate(photos)]
        attributes = initial.get("attributes", {})
        for definition in _category_attributes(categories, category_id):
            key = definition["key"]
            field = (
                forms.ChoiceField(
                    choices=[("", "—")] + [(value, value) for value in definition.get("values", ())],
                    required=False,
                    label=definition["label"],
                )
                if definition.get("values")
                else forms.CharField(max_length=256, required=False, label=definition["label"])
            )
            field.initial = attributes.get(key, "")
            self.fields[f"attr_{key}"] = field

    def public_attributes(self):
        return {key[5:]: value for key, value in self.cleaned_data.items() if key.startswith("attr_") and value}


class PhotoUploadForm(forms.Form):
    photo = forms.ImageField(label="Файл фотографии")
    attested = forms.BooleanField(label="Это настоящее фото товара без AI-дорисовок")


class LocationForm(forms.Form):
    name = forms.CharField(max_length=120, label="Название места хранения")


class ExpectedVersionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class PriceForm(ExpectedVersionForm):
    price = forms.CharField(max_length=128, label="Цена, ₽", widget=forms.TextInput(attrs={"inputmode": "decimal"}))


class StockForm(ExpectedVersionForm):
    location_id = forms.UUIDField(widget=forms.HiddenInput)
    quantity = forms.CharField(max_length=128, label="Остаток", widget=forms.TextInput(attrs={"inputmode": "decimal"}))


class VariantActionForm(forms.Form):
    variant_id = forms.UUIDField(widget=forms.HiddenInput)


class BlockForm(forms.Form):
    object_id = forms.UUIDField(widget=forms.HiddenInput)
    blocked = forms.BooleanField(required=False, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=1024, label="Причина")


class ParticipantForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Email аккаунта")
    allowed = forms.BooleanField(required=False, label="Разрешить участие")


class CategoryForm(forms.Form):
    name = forms.CharField(max_length=120, label="Название категории")
    active = forms.BooleanField(required=False, initial=True, label="Категория активна")
    expected_version = forms.IntegerField(min_value=0, required=False, widget=forms.HiddenInput)


class AttributeForm(forms.Form):
    key = forms.CharField(max_length=64, required=False, label="Стабильный ключ")
    label = forms.CharField(max_length=120, required=False, label="Название")
    required = forms.BooleanField(required=False, label="Обязательная")
    choices = forms.CharField(required=False, label="Допустимые значения (по одному в строке)", widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned = super().clean()
        label = (cleaned.get("label") or "").strip()
        key = (cleaned.get("key") or "").strip()
        if not label and not key and not (cleaned.get("choices") or "").strip():
            return cleaned
        if not label:
            self.add_error("label", "Укажите название характеристики.")
        if not key and label:
            cleaned["key"] = slugify(label, allow_unicode=True).replace(" ", "-")
        if cleaned.get("choices"):
            values = [value.strip() for value in cleaned["choices"].splitlines() if value.strip()]
            if len(values) != len(set(values)):
                self.add_error("choices", "Значения должны быть разными.")
            cleaned["_values"] = values
        else:
            cleaned["_values"] = []
        return cleaned


AttributeFormSet = formset_factory(AttributeForm, extra=1, can_delete=True, max_num=50, validate_max=True)


def attribute_formset_initial(category):
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "required": item["required"],
            "choices": "\n".join(item.get("values", ())),
        }
        for item in (category or {}).get("attributes", ())
    ]


def _definitions(formset):
    definitions = []
    for form in formset:
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            continue
        if not form.cleaned_data.get("label"):
            continue
        definitions.append({
            "key": form.cleaned_data["key"],
            "label": form.cleaned_data["label"],
            "required": form.cleaned_data.get("required", False),
            "values": form.cleaned_data.get("_values", []),
        })
    return definitions


AttributeFormSet.as_definitions = _definitions


class MatchRequestForm(forms.Form):
    source_variant_id = forms.UUIDField(widget=forms.HiddenInput)
    target_variant_id = forms.UUIDField(label="Общий вариант")
    reason = forms.CharField(max_length=2000, label="Почему это идентичный товар", widget=forms.Textarea)

    def __init__(self, *args, targets=(), **kwargs):
        super().__init__(*args, **kwargs)
        if targets:
            self.fields["target_variant_id"] = forms.ChoiceField(choices=targets, label="Общий вариант")


class MatchReviewForm(forms.Form):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    approve = forms.BooleanField(required=False, label="Одобрить")
    identity_confirmed = forms.BooleanField(required=False, label="Подтверждаю идентичность модели, характеристик, комплектации, состояния и единицы")
    reason = forms.CharField(max_length=1024, label="Решение", widget=forms.Textarea)


class SuggestionForm(forms.Form):
    kind = forms.ChoiceField(choices=(("category", "Категория"), ("attribute", "Характеристика"), ("common", "Общая карточка")))
    target_id = forms.UUIDField(required=False, label="Идентификатор цели")
    text = forms.CharField(max_length=2000, label="Предложение", widget=forms.Textarea)

    def __init__(self, *args, targets=(), **kwargs):
        super().__init__(*args, **kwargs)
        if targets:
            self.fields["target_id"] = forms.ChoiceField(choices=targets, required=False, label="Цель")


class SuggestionReviewForm(forms.Form):
    suggestion_id = forms.UUIDField(widget=forms.HiddenInput)
    response = forms.CharField(max_length=2000, label="Ответ", widget=forms.Textarea)
