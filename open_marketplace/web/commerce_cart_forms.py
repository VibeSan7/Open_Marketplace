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

    def clean_intent_id(self):
        value = self.cleaned_data["intent_id"]
        try:
            parsed = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise forms.ValidationError("Неверный идентификатор корзины.") from None
        if str(parsed) != value:
            raise forms.ValidationError("Идентификатор корзины должен быть в каноническом формате.")
        return parsed
