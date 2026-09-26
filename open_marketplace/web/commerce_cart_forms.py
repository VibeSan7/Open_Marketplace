from uuid import UUID

from django import forms


class CommerceCartQuantityForm(forms.Form):
    quantity = forms.CharField(
        label="Количество",
        max_length=128,
        help_text="Для штук укажите целое число, для кг и м — до 3 знаков после запятой.",
    )


class CommerceCartCheckoutForm(forms.Form):
    intent_id = forms.CharField(widget=forms.HiddenInput)
    delivery_address_id = forms.CharField(
        label="Адрес доставки",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, address_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["delivery_address_id"].widget.choices = tuple(
            (address["id"], self._address_label(address))
            for address in address_choices
        )

    @staticmethod
    def _address_label(address):
        parts = [
            address.get("label"),
            address["recipient_name"],
            f"{address['city']}, {address['street']}, {address['building']}",
        ]
        if address.get("apartment"):
            parts[-1] += f", кв. {address['apartment']}"
        return " · ".join(part for part in parts if part)

    def clean_intent_id(self):
        value = self.cleaned_data["intent_id"]
        try:
            parsed = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise forms.ValidationError("Неверный идентификатор корзины.") from None
        if str(parsed) != value:
            raise forms.ValidationError("Идентификатор корзины должен быть в каноническом формате.")
        return parsed


class CommerceDeliveryAddressForm(forms.Form):
    label = forms.CharField(label="Название", max_length=80, required=False)
    recipient_name = forms.CharField(label="Получатель", max_length=120)
    phone = forms.CharField(label="Телефон", max_length=16)
    postal_code = forms.CharField(label="Индекс", max_length=6)
    region = forms.CharField(label="Регион", max_length=120)
    city = forms.CharField(label="Город", max_length=120)
    street = forms.CharField(label="Улица", max_length=160)
    building = forms.CharField(label="Дом", max_length=40)
    apartment = forms.CharField(label="Квартира или офис", max_length=40, required=False)
    comment = forms.CharField(label="Комментарий курьеру", max_length=500, required=False)
