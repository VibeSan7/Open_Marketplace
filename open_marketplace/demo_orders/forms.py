from uuid import UUID

from django import forms


class DemoOrderForm(forms.Form):
    intent_id = forms.CharField(widget=forms.HiddenInput)
    quantity = forms.CharField(
        label="Количество",
        max_length=128,
        help_text="Укажите количество в целых единицах для штук или до 3 знаков для кг/м.",
    )

    def clean_intent_id(self):
        value = self.cleaned_data["intent_id"]
        try:
            parsed = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise forms.ValidationError("Неверный идентификатор намерения.") from None
        if str(parsed) != value:
            raise forms.ValidationError("Идентификатор намерения должен быть в каноническом формате.")
        return parsed


class DemoOrderActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=(
            ("simulate_success", "Симулировать успешную оплату"),
            ("simulate_decline", "Симулировать отказ оплаты"),
            ("hand_over", "Симулировать передачу"),
            ("complete", "Симулировать завершение"),
            ("cancel", "Отменить тестовый заказ"),
        ),
        widget=forms.HiddenInput,
    )
