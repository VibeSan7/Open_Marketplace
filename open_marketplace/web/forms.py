from django import forms


class RegisterForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)


class LoginForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)
    second_factor = forms.CharField(max_length=64, required=False, strip=False)
    next = forms.CharField(max_length=2048, required=False, widget=forms.HiddenInput)


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(max_length=254)


class PasswordResetConfirmForm(forms.Form):
    new_password = forms.CharField(
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )
    new_password = forms.CharField(
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )


class ReauthenticateForm(forms.Form):
    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)
    second_factor = forms.CharField(max_length=64, required=False, strip=False)


class TotpBeginForm(forms.Form):
    current_password = forms.CharField(
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )


class TotpConfirmForm(forms.Form):
    setup_id = forms.UUIDField(widget=forms.HiddenInput)
    code = forms.RegexField(regex=r"^[0-9]{6}$", max_length=6)


class TotpDisableForm(forms.Form):
    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)
    second_factor = forms.CharField(max_length=64, strip=False)


class RecoveryCodesReplaceForm(forms.Form):
    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)
    second_factor = forms.CharField(max_length=64, strip=False)


class MandatoryTotpBeginForm(forms.Form):
    current_password = forms.CharField(
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )


class MandatoryTotpCompleteForm(forms.Form):
    code = forms.RegexField(regex=r"^[0-9]{6}$", max_length=6)


class StaffInvitationBeginForm(forms.Form):
    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)


class StaffInvitationCompleteForm(forms.Form):
    totp_code = forms.RegexField(regex=r"^[0-9]{6}$", max_length=6)
