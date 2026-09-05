from functools import wraps
from uuid import UUID

from django.http import HttpResponseNotAllowed
from django.urls import reverse

from open_marketplace.common.errors import ApplicationError
from open_marketplace.seller_onboarding import public as seller_public
from open_marketplace.web.errors import EXPECTED_ERROR_MESSAGE, secure_render, secure_response
from open_marketplace.web.forms import SellerApplicationForm
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303


def _method_guard(methods):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return secure_response(HttpResponseNotAllowed(methods))
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def _neutral(request, *, status=200):
    return secure_render(
        request,
        "seller/error.html",
        {"message": EXPECTED_ERROR_MESSAGE},
        status=status,
    )


def _draft_initial(draft):
    if draft is None:
        return {}
    return {
        "business_form": draft.business_form,
        "display_name": draft.display_name,
        "official_name": draft.official_name,
        "registration_identifier": draft.registration_identifier,
        "contact_email": draft.contact_email,
        "test_data_attested": draft.test_data_attested,
    }


@_method_guard(("GET", "POST"))
@_login_required
def seller_application_create(request):
    if request.method == "GET":
        return secure_render(request, "seller/application_create.html")
    try:
        application_id = seller_public.create_seller_application(
            context=_context(request)
        )
    except ApplicationError:
        return _neutral(request)
    return _redirect_303(
        reverse("seller-application-edit", kwargs={"application_id": application_id})
    )


@_method_guard(("GET", "POST"))
@_login_required
def seller_application_edit(request, *, application_id: UUID):
    if request.method == "GET":
        try:
            draft = seller_public.get_own_seller_application_draft(
                application_id=application_id,
                context=_context(request),
            )
        except ApplicationError:
            return _neutral(request)
        return secure_render(
            request,
            "seller/application_edit.html",
            {"form": SellerApplicationForm(initial=_draft_initial(draft))},
        )

    form = SellerApplicationForm(request.POST)
    if not form.is_valid():
        return secure_render(
            request,
            "seller/application_edit.html",
            {"form": SellerApplicationForm(), "message": EXPECTED_ERROR_MESSAGE},
        )
    try:
        seller_public.update_seller_application_draft(
            application_id=application_id,
            data=seller_public.SellerDraftData(**form.cleaned_data),
            context=_context(request),
        )
    except ApplicationError:
        return _neutral(request)
    return _redirect_303(
        reverse("seller-application-detail", kwargs={"application_id": application_id})
    )


@_method_guard(("POST",))
@_login_required
def seller_application_submit(request, *, application_id: UUID):
    try:
        seller_public.submit_seller_application(
            application_id=application_id,
            context=_context(request),
        )
    except ApplicationError:
        return _neutral(request)
    return _redirect_303(
        reverse("seller-application-detail", kwargs={"application_id": application_id})
    )


@_method_guard(("POST",))
@_login_required
def seller_application_withdraw(request, *, application_id: UUID):
    try:
        seller_public.withdraw_seller_application(
            application_id=application_id,
            context=_context(request),
        )
    except ApplicationError:
        return _neutral(request)
    return _redirect_303(reverse("seller-applications"))


@_method_guard(("GET",))
@_login_required
def seller_applications(request):
    try:
        applications = seller_public.list_own_seller_applications(
            context=_context(request)
        )
    except ApplicationError:
        return _neutral(request)
    return secure_render(
        request,
        "seller/applications.html",
        {"applications": applications},
    )


@_method_guard(("GET",))
@_login_required
def seller_application_detail(request, *, application_id: UUID):
    try:
        application, versions = seller_public.get_own_seller_application(
            application_id=application_id,
            context=_context(request),
        )
    except ApplicationError:
        return _neutral(request)
    return secure_render(
        request,
        "seller/application_detail.html",
        {"application": application, "versions": versions},
    )


@_method_guard(("GET",))
@_login_required
def seller_status(request):
    try:
        profile = seller_public.get_seller_profile_for_owner(context=_context(request))
    except ApplicationError:
        return _neutral(request)
    return secure_render(request, "seller/status.html", {"profile": profile})
