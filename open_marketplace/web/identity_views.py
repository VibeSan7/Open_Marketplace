from functools import wraps
from urllib.parse import urlencode
from uuid import UUID

from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_http_methods

from open_marketplace.common.errors import ApplicationError
from open_marketplace.common.types import OperationContext
from open_marketplace.identity import public as identity_public
from open_marketplace.web.errors import (
    EXPECTED_ERROR_MESSAGE,
    NEUTRAL_EMAIL_MESSAGE,
    secure_render,
    secure_response,
)
from open_marketplace.web.forms import (
    LoginForm,
    MandatoryTotpBeginForm,
    MandatoryTotpCompleteForm,
    PasswordChangeForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    ReauthenticateForm,
    RecoveryCodesReplaceForm,
    RegisterForm,
    TotpBeginForm,
    TotpConfirmForm,
    TotpDisableForm,
)
from open_marketplace.web.sensitive_links import (
    SensitiveLinkRejected,
    consume_continuation,
    consume_initial,
    store_continuation,
    store_initial,
)
from open_marketplace.workflows.totp import enable_totp_and_activate_waiting_seller


def _context(request, *, anonymous=False):
    actor_id = None
    session_id = None
    if not anonymous and getattr(request.user, "is_authenticated", False):
        actor_id = request.user.pk
        raw_session_id = request.session.get("session_id")
        try:
            session_id = UUID(str(raw_session_id))
        except (TypeError, ValueError, AttributeError):
            session_id = None
    return OperationContext(
        actor_account_id=actor_id,
        session_id=session_id,
        request_id=request.request_id,
        source="html",
        source_address=request.META.get("REMOTE_ADDR"),
        now=timezone.now(),
    )


def _safe_next(request, value, *, fallback):
    if (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and url_has_allowed_host_and_scheme(
            value,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return value
    return reverse(fallback)


def _redirect_303(location):
    response = HttpResponse(status=303)
    response["Location"] = location
    return secure_response(response)


def _login_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            query = urlencode({"next": request.get_full_path()})
            return _redirect_303(f"{reverse('login')}?{query}")
        return view(request, *args, **kwargs)

    return wrapped


def sensitive_entry(request, *, raw_token, purpose, clean_name):
    if request.method != "GET":
        return HttpResponse(status=405)
    try:
        store_initial(request, purpose=purpose, raw_token=raw_token)
    except SensitiveLinkRejected:
        pass
    return _redirect_303(reverse(clean_name))


@require_http_methods(["GET", "POST"])
def register(request):
    message = None
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                identity_public.register_account(
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password"],
                    context=_context(request, anonymous=True),
                )
                message = NEUTRAL_EMAIL_MESSAGE
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = RegisterForm()
    else:
        form = RegisterForm()
    return secure_render(
        request,
        "registration/register.html",
        {"form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
def login(request):
    message = None
    initial_next = _safe_next(
        request,
        request.GET.get("next"),
        fallback="security",
    )
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            target = _safe_next(
                request,
                form.cleaned_data["next"],
                fallback="security",
            )
            if request.session.session_key is None:
                request.session.create()
            else:
                request.session.cycle_key()
            try:
                result = identity_public.authenticate_account(
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password"],
                    second_factor=form.cleaned_data["second_factor"] or None,
                    django_session_key=request.session.session_key,
                    device_label=request.META.get("HTTP_USER_AGENT", ""),
                    context=_context(request, anonymous=True),
                )
            except ApplicationError:
                request.session.flush()
                message = EXPECTED_ERROR_MESSAGE
                form = LoginForm(initial={"next": target})
            else:
                request.session["account_id"] = str(result.account_id)
                request.session["session_id"] = str(result.session_id)
                return _redirect_303(target)
        else:
            request.session.flush()
            message = EXPECTED_ERROR_MESSAGE
            form = LoginForm(initial={"next": initial_next})
    else:
        form = LoginForm(initial={"next": initial_next})
    return secure_render(
        request,
        "registration/login.html",
        {"form": form, "message": message},
    )


@require_POST
@_login_required
def logout(request):
    try:
        identity_public.log_out_session(context=_context(request))
    except ApplicationError:
        pass
    request.session.flush()
    return _redirect_303(reverse("login"))


@require_http_methods(["GET", "POST"])
def password_reset_request(request):
    message = None
    if request.method == "POST":
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            try:
                identity_public.request_password_reset(
                    email=form.cleaned_data["email"],
                    context=_context(request, anonymous=True),
                )
            except ApplicationError:
                pass
        message = NEUTRAL_EMAIL_MESSAGE
        form = PasswordResetRequestForm()
    else:
        form = PasswordResetRequestForm()
    return secure_render(
        request,
        "registration/password_reset_request.html",
        {"form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
def verify_email_complete(request):
    message = None
    if request.method == "POST":
        try:
            raw_token = consume_initial(request, purpose="email_verification")
            identity_public.verify_email(
                raw_token=raw_token,
                context=_context(request, anonymous=True),
            )
            message = "Email verification completed."
        except (SensitiveLinkRejected, ApplicationError):
            message = EXPECTED_ERROR_MESSAGE
    return secure_render(
        request,
        "registration/verify_email_complete.html",
        {"message": message},
    )


@require_http_methods(["GET", "POST"])
def password_reset_confirm(request):
    message = None
    if request.method == "POST":
        form = PasswordResetConfirmForm(request.POST)
        if form.is_valid():
            try:
                raw_token = consume_initial(request, purpose="password_reset")
                identity_public.reset_password(
                    raw_token=raw_token,
                    new_password=form.cleaned_data["new_password"],
                    context=_context(request, anonymous=True),
                )
                request.session.flush()
                message = "Password reset completed."
            except (SensitiveLinkRejected, ApplicationError):
                message = EXPECTED_ERROR_MESSAGE
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = PasswordResetConfirmForm()
    else:
        form = PasswordResetConfirmForm()
    return secure_render(
        request,
        "registration/password_reset_confirm.html",
        {"form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
@_login_required
def password_change(request):
    message = None
    if request.method == "POST":
        form = PasswordChangeForm(request.POST)
        if form.is_valid():
            try:
                identity_public.change_password(
                    current_password=form.cleaned_data["current_password"],
                    new_password=form.cleaned_data["new_password"],
                    context=_context(request),
                )
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
            else:
                request.session.flush()
                return _redirect_303(reverse("login"))
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = PasswordChangeForm()
    else:
        form = PasswordChangeForm()
    return secure_render(
        request,
        "registration/password_change.html",
        {"form": form, "message": message},
    )


@require_http_methods(["GET"])
@_login_required
def security(request):
    try:
        account = identity_public.get_account_snapshot(request.user.pk)
    except ApplicationError:
        account = None
    return secure_render(
        request,
        "identity/security.html",
        {"account": account},
    )


@require_http_methods(["GET", "POST"])
@_login_required
def reauthenticate(request):
    message = None
    if request.method == "POST":
        form = ReauthenticateForm(request.POST)
        if form.is_valid():
            try:
                identity_public.reauthenticate_session(
                    password=form.cleaned_data["password"],
                    second_factor=form.cleaned_data["second_factor"] or None,
                    context=_context(request),
                )
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
            else:
                return _redirect_303(reverse("security"))
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = ReauthenticateForm()
    else:
        form = ReauthenticateForm()
    return secure_render(
        request,
        "identity/form.html",
        {"title": "Reauthenticate", "form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
@_login_required
def totp_setup(request):
    message = None
    if request.method == "POST" and ("setup_id" in request.POST or "code" in request.POST):
        form = TotpConfirmForm(request.POST)
        if form.is_valid():
            try:
                codes = enable_totp_and_activate_waiting_seller(
                    setup_id=form.cleaned_data["setup_id"],
                    code=form.cleaned_data["code"],
                    context=_context(request),
                )
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
            else:
                return secure_render(
                    request,
                    "identity/recovery_codes.html",
                    {"recovery_codes": codes},
                )
        else:
            message = EXPECTED_ERROR_MESSAGE
        return secure_render(
            request,
            "identity/form.html",
            {"title": "Set up TOTP", "form": TotpBeginForm(), "message": message},
        )
    if request.method == "POST":
        form = TotpBeginForm(request.POST)
        if form.is_valid():
            try:
                setup = identity_public.begin_totp_setup(
                    current_password=form.cleaned_data["current_password"],
                    context=_context(request),
                )
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
            else:
                return secure_render(
                    request,
                    "identity/totp_setup.html",
                    {"setup": setup, "form": TotpConfirmForm(initial={"setup_id": setup.setup_id})},
                )
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = TotpBeginForm()
    else:
        form = TotpBeginForm()
    return secure_render(
        request,
        "identity/form.html",
        {"title": "Set up TOTP", "form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
@_login_required
def totp_disable(request):
    message = None
    if request.method == "POST":
        form = TotpDisableForm(request.POST)
        if form.is_valid():
            try:
                identity_public.disable_optional_totp(
                    password=form.cleaned_data["password"],
                    second_factor=form.cleaned_data["second_factor"],
                    context=_context(request),
                )
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
            else:
                return _redirect_303(reverse("security"))
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = TotpDisableForm()
    else:
        form = TotpDisableForm()
    return secure_render(
        request,
        "identity/form.html",
        {"title": "Disable TOTP", "form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
@_login_required
def recovery_codes_replace(request):
    message = None
    if request.method == "POST":
        form = RecoveryCodesReplaceForm(request.POST)
        if form.is_valid():
            try:
                codes = identity_public.replace_recovery_codes(
                    password=form.cleaned_data["password"],
                    second_factor=form.cleaned_data["second_factor"],
                    context=_context(request),
                )
            except ApplicationError:
                message = EXPECTED_ERROR_MESSAGE
            else:
                return secure_render(
                    request,
                    "identity/recovery_codes.html",
                    {"recovery_codes": codes},
                )
        else:
            message = EXPECTED_ERROR_MESSAGE
        form = RecoveryCodesReplaceForm()
    else:
        form = RecoveryCodesReplaceForm()
    return secure_render(
        request,
        "identity/form.html",
        {"title": "Replace recovery codes", "form": form, "message": message},
    )


@require_http_methods(["GET", "POST"])
def mandatory_totp_recovery(request):
    message = None
    if request.method == "POST" and "code" in request.POST:
        form = MandatoryTotpCompleteForm(request.POST)
        if form.is_valid():
            try:
                raw_token, setup_id = consume_continuation(
                    request,
                    purpose="mandatory_totp_recovery",
                )
                codes = identity_public.complete_mandatory_totp_recovery(
                    raw_token=raw_token,
                    setup_id=UUID(setup_id),
                    code=form.cleaned_data["code"],
                    context=_context(request, anonymous=True),
                )
            except (SensitiveLinkRejected, ApplicationError, ValueError):
                message = EXPECTED_ERROR_MESSAGE
            else:
                request.session.flush()
                return secure_render(
                    request,
                    "identity/recovery_codes.html",
                    {"recovery_codes": codes},
                )
        else:
            message = EXPECTED_ERROR_MESSAGE
    elif request.method == "POST":
        form = MandatoryTotpBeginForm(request.POST)
        if form.is_valid():
            try:
                raw_token = consume_initial(
                    request,
                    purpose="mandatory_totp_recovery",
                )
                setup = identity_public.begin_mandatory_totp_recovery(
                    raw_token=raw_token,
                    current_password=form.cleaned_data["current_password"],
                    context=_context(request, anonymous=True),
                )
                store_continuation(
                    request,
                    purpose="mandatory_totp_recovery",
                    raw_token=raw_token,
                    identifier=setup.setup_id,
                )
            except (SensitiveLinkRejected, ApplicationError):
                message = EXPECTED_ERROR_MESSAGE
            else:
                return secure_render(
                    request,
                    "identity/totp_setup.html",
                    {"setup": setup, "form": MandatoryTotpCompleteForm()},
                )
        else:
            message = EXPECTED_ERROR_MESSAGE
    return secure_render(
        request,
        "identity/form.html",
        {
            "title": "Recover mandatory TOTP",
            "form": MandatoryTotpBeginForm(),
            "message": message,
        },
    )


@require_http_methods(["GET"])
@_login_required
def sessions(request):
    try:
        session_views = identity_public.list_sessions(context=_context(request))
        message = None
    except ApplicationError:
        session_views = ()
        message = EXPECTED_ERROR_MESSAGE
    return secure_render(
        request,
        "identity/sessions.html",
        {"sessions": session_views, "message": message},
    )


@require_POST
@_login_required
def session_revoke(request, *, session_id):
    current_id = request.session.get("session_id")
    try:
        identity_public.revoke_session(
            session_id=session_id,
            context=_context(request),
        )
    except ApplicationError:
        return secure_render(
            request,
            "identity/form.html",
            {"title": "Sessions", "message": EXPECTED_ERROR_MESSAGE},
        )
    if str(session_id) == str(current_id):
        request.session.flush()
        return _redirect_303(reverse("login"))
    return _redirect_303(reverse("sessions"))


@require_POST
@_login_required
def sessions_revoke_others(request):
    try:
        identity_public.revoke_other_sessions(context=_context(request))
    except ApplicationError:
        return secure_render(
            request,
            "identity/form.html",
            {"title": "Sessions", "message": EXPECTED_ERROR_MESSAGE},
        )
    return _redirect_303(reverse("sessions"))
