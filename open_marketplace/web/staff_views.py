from uuid import UUID

from django.conf import settings
from django.views.decorators.http import require_http_methods

from open_marketplace.access import public as access_public
from open_marketplace.common.errors import ApplicationError
from open_marketplace.web.errors import EXPECTED_ERROR_MESSAGE, secure_render
from open_marketplace.web.forms import (
    StaffInvitationBeginForm,
    StaffInvitationCompleteForm,
)
from open_marketplace.web.identity_views import _context, _redirect_303
from open_marketplace.web.sensitive_links import (
    SensitiveLinkRejected,
    consume_continuation,
    consume_initial,
    store_continuation,
)


@require_http_methods(["GET", "POST"])
def staff_invitation_accept(request):
    message = None
    if request.method == "POST" and "totp_code" in request.POST:
        form = StaffInvitationCompleteForm(request.POST)
        if form.is_valid():
            try:
                raw_token, acceptance_id = consume_continuation(
                    request,
                    purpose="staff_invitation",
                )
                result = access_public.accept_staff_invitation(
                    raw_token=raw_token,
                    acceptance_id=UUID(acceptance_id),
                    totp_code=form.cleaned_data["totp_code"],
                    context=_context(request),
                )
            except (SensitiveLinkRejected, ApplicationError, ValueError):
                message = EXPECTED_ERROR_MESSAGE
            else:
                if result.recovery_codes:
                    return secure_render(
                        request,
                        "identity/recovery_codes.html",
                        {"recovery_codes": result.recovery_codes},
                    )
                return _redirect_303("/security/")
        else:
            message = EXPECTED_ERROR_MESSAGE
    elif request.method == "POST":
        form = StaffInvitationBeginForm(request.POST)
        if form.is_valid():
            try:
                raw_token = consume_initial(request, purpose="staff_invitation")
                setup = access_public.begin_staff_invitation_acceptance(
                    raw_token=raw_token,
                    password=form.cleaned_data["password"],
                    context=_context(request),
                )
                store_continuation(
                    request,
                    purpose="staff_invitation",
                    raw_token=raw_token,
                    identifier=setup.acceptance_id,
                )
            except (SensitiveLinkRejected, ApplicationError):
                message = EXPECTED_ERROR_MESSAGE
            else:
                return secure_render(
                    request,
                    "staff/invitation_accept.html",
                    {
                        "setup": setup.totp_setup,
                        "show_setup_retry_guidance": (
                            setup.mode == "new_service_account"
                            and setup.totp_setup is None
                        ),
                        "setup_lifetime_minutes": int(settings.TOTP_SETUP_TTL.total_seconds() / 60),
                        "form": StaffInvitationCompleteForm(),
                        "message": None,
                    },
                )
        else:
            message = EXPECTED_ERROR_MESSAGE
    if message and getattr(request.user, "is_authenticated", False):
        message = (
            f"{message} Вы уже вошли в аккаунт. Если приглашение предназначено "
            "для другого аккаунта, выйдите и снова откройте ссылку приглашения."
        )
    return secure_render(
        request,
        "staff/invitation_accept.html",
        {
            "setup": None,
            "form": StaffInvitationBeginForm(),
            "message": message,
        },
    )
