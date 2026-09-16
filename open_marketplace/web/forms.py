from django import forms


class RegisterForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Электронная почта")
    password = forms.CharField(
        max_length=128,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput,
    )


class LoginForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Электронная почта")
    password = forms.CharField(
        max_length=128,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput,
    )
    second_factor = forms.CharField(
        max_length=64,
        label="Код второго фактора",
        help_text="Необязательно: код из приложения-аутентификатора или резервный код.",
        required=False,
        strip=False,
    )
    next = forms.CharField(max_length=2048, required=False, widget=forms.HiddenInput)


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Электронная почта")


class SellerApplicationForm(forms.Form):
    business_form = forms.ChoiceField(
        choices=(
            ("sole_proprietor", "Индивидуальный предприниматель"),
            ("legal_entity", "Юридическое лицо"),
            ("self_employed", "Самозанятый"),
        ),
        label="Форма ведения деятельности",
    )
    display_name = forms.CharField(max_length=256, label="Название в каталоге")
    official_name = forms.CharField(max_length=256, label="Официальное название")
    registration_identifier = forms.CharField(max_length=128, label="Регистрационный номер")
    contact_email = forms.EmailField(max_length=254, label="Контактная почта")
    test_data_attested = forms.BooleanField(
        label="Я использую только тестовые данные",
        help_text="Для этой демонстрации продавец допускается только с тестовыми данными.",
    )


class PasswordResetConfirmForm(forms.Form):
    new_password = forms.CharField(
        max_length=128,
        label="Новый пароль",
        strip=False,
        widget=forms.PasswordInput,
    )


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        max_length=128,
        label="Текущий пароль",
        strip=False,
        widget=forms.PasswordInput,
    )
    new_password = forms.CharField(
        max_length=128,
        label="Новый пароль",
        strip=False,
        widget=forms.PasswordInput,
    )


class ReauthenticateForm(forms.Form):
    password = forms.CharField(
        max_length=128,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput,
    )
    second_factor = forms.CharField(
        max_length=64,
        label="Код второго фактора",
        help_text="Необязательно, если для этой операции код не запрашивается.",
        required=False,
        strip=False,
    )


class TotpBeginForm(forms.Form):
    current_password = forms.CharField(
        max_length=128,
        label="Текущий пароль",
        strip=False,
        widget=forms.PasswordInput,
    )


class TotpConfirmForm(forms.Form):
    setup_id = forms.UUIDField(widget=forms.HiddenInput)
    code = forms.RegexField(
        regex=r"^[0-9]{6}$",
        max_length=6,
        label="Шестизначный код",
        help_text="Введите код из приложения-аутентификатора.",
    )


class TotpDisableForm(forms.Form):
    password = forms.CharField(
        max_length=128,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput,
    )
    second_factor = forms.CharField(
        max_length=64,
        label="Код второго фактора",
        help_text="Введите код из приложения-аутентификатора или резервный код.",
        strip=False,
    )


class RecoveryCodesReplaceForm(forms.Form):
    password = forms.CharField(
        max_length=128,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput,
    )
    second_factor = forms.CharField(
        max_length=64,
        label="Код второго фактора",
        help_text="Введите код из приложения-аутентификатора или резервный код.",
        strip=False,
    )


class MandatoryTotpBeginForm(forms.Form):
    current_password = forms.CharField(
        max_length=128,
        label="Текущий пароль",
        strip=False,
        widget=forms.PasswordInput,
    )


class MandatoryTotpCompleteForm(forms.Form):
    code = forms.RegexField(
        regex=r"^[0-9]{6}$",
        max_length=6,
        label="Шестизначный код",
        help_text="Введите код из приложения-аутентификатора.",
    )


class StaffInvitationBeginForm(forms.Form):
    password = forms.CharField(
        max_length=128,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput,
    )


class StaffInvitationCompleteForm(forms.Form):
    totp_code = forms.RegexField(
        regex=r"^[0-9]{6}$",
        max_length=6,
        label="Шестизначный код",
        help_text="Введите код из приложения-аутентификатора.",
    )
