from functools import wraps

from django.core.exceptions import ObjectDoesNotExist
from django.urls import path, reverse
from django.views.decorators.http import require_GET, require_POST

import open_marketplace.seller_onboarding.public as seller_public
from open_marketplace.common.errors import ApplicationError, PermissionDenied
from open_marketplace.staff_admin.site import (
    action_response,
    expected_error_response,
    forbidden_response,
    operation_context,
    optional_uuid,
    render_admin,
)


def _bind(site, view):
    @wraps(view)
    def bound(request, *args, **kwargs):
        return view(request, site, *args, **kwargs)

    return site.admin_view(bound)


@require_GET
def application_list(request, site):
    requested_state = request.GET.get("state")
    states = (
        (requested_state,)
        if requested_state
        else ("submitted", "under_review", "changes_requested")
    )
    try:
        query = seller_public.SellerReviewQuery(
            states=states,
            reviewer_id=optional_uuid(request.GET.get("reviewer_id"), name="reviewer_id"),
            limit=100,
            cursor=optional_uuid(request.GET.get("cursor"), name="cursor"),
        )
        applications = seller_public.list_seller_review_queue(
            query=query,
            context=operation_context(request),
        )
    except PermissionDenied:
        return forbidden_response()
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    rows = tuple(
        {
            "values": (
                application.id,
                application.applicant_id,
                application.state,
                application.current_version,
            ),
            "detail_url": reverse(
                "admin:seller-application-detail",
                kwargs={"application_id": application.id},
            ),
        }
        for application in applications
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": "Seller application queue",
            "headers": ("ID", "Applicant", "State", "Version"),
            "rows": rows,
        },
    )


@require_GET
def application_detail(request, site, application_id):
    try:
        application, versions = seller_public.get_seller_application_for_review(
            application_id=application_id,
            context=operation_context(request),
        )
    except PermissionDenied:
        return forbidden_response()
    except ObjectDoesNotExist:
        return render_admin(
            site,
            request,
            "admin/error.html",
            {"title": "Not found", "message": "The application was not found."},
            status=404,
        )
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    fields = (
        ("ID", application.id),
        ("Applicant", application.applicant_id),
        ("State", application.state),
        ("Current version", application.current_version),
        ("Reviewer", application.reviewer_id),
        ("Decision", application.decision),
        ("Reason", application.reason),
        ("Versions", len(versions)),
    )
    actions = (
        (
            "Start review",
            reverse(
                "admin:seller-application-start-review",
                kwargs={"application_id": application.id},
            ),
            False,
        ),
        (
            "Request changes",
            reverse(
                "admin:seller-application-request-changes",
                kwargs={"application_id": application.id},
            ),
            True,
        ),
        (
            "Approve",
            reverse(
                "admin:seller-application-approve",
                kwargs={"application_id": application.id},
            ),
            True,
        ),
        (
            "Reject",
            reverse(
                "admin:seller-application-reject",
                kwargs={"application_id": application.id},
            ),
            True,
        ),
    )
    return render_admin(
        site,
        request,
        "admin/detail.html",
        {"title": "Seller application", "fields": fields, "actions": actions},
    )


def _application_action(site, request, application_id, operation, *, reason=False):
    def invoke():
        values = {
            "application_id": application_id,
            "context": operation_context(request),
        }
        if reason:
            values["reason"] = request.POST.get("reason", "")
        return operation(**values)

    return action_response(
        site,
        request,
        invoke,
        reverse(
            "admin:seller-application-detail",
            kwargs={"application_id": application_id},
        ),
    )


@require_POST
def application_start_review(request, site, application_id):
    return _application_action(
        site,
        request,
        application_id,
        seller_public.start_seller_application_review,
    )


@require_POST
def application_request_changes(request, site, application_id):
    return _application_action(
        site,
        request,
        application_id,
        seller_public.request_seller_application_changes,
        reason=True,
    )


@require_POST
def application_approve(request, site, application_id):
    return _application_action(
        site,
        request,
        application_id,
        seller_public.approve_seller_application,
        reason=True,
    )


@require_POST
def application_reject(request, site, application_id):
    return _application_action(
        site,
        request,
        application_id,
        seller_public.reject_seller_application,
        reason=True,
    )


def _find_seller_profile(request, seller_id):
    cursor = None
    while True:
        page = seller_public.query_seller_profiles(
            query=seller_public.SellerProfileQuery(
                state=None,
                owner_id=None,
                limit=100,
                cursor=cursor,
            ),
            context=operation_context(request),
        )
        for profile in page:
            if profile.id == seller_id:
                return profile
        if len(page) < 100:
            raise ObjectDoesNotExist
        next_cursor = page[-1].id
        if next_cursor == cursor:
            raise ObjectDoesNotExist
        cursor = next_cursor


@require_GET
def profile_list(request, site):
    try:
        query = seller_public.SellerProfileQuery(
            state=request.GET.get("state") or None,
            owner_id=optional_uuid(request.GET.get("owner_id"), name="owner_id"),
            limit=100,
            cursor=optional_uuid(request.GET.get("cursor"), name="cursor"),
        )
        profiles = seller_public.query_seller_profiles(
            query=query,
            context=operation_context(request),
        )
    except PermissionDenied:
        return forbidden_response()
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    rows = tuple(
        {
            "values": (profile.id, profile.owner_id, profile.state, profile.restriction_reason),
            "detail_url": reverse(
                "admin:seller-profile-detail",
                kwargs={"seller_id": profile.id},
            ),
        }
        for profile in profiles
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": "Seller admission",
            "headers": ("ID", "Owner", "State", "Reason"),
            "rows": rows,
        },
    )


@require_GET
def profile_detail(request, site, seller_id):
    try:
        profile = _find_seller_profile(request, seller_id)
    except PermissionDenied:
        return forbidden_response()
    except ObjectDoesNotExist:
        return render_admin(
            site,
            request,
            "admin/error.html",
            {"title": "Not found", "message": "The seller was not found."},
            status=404,
        )
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    fields = (
        ("ID", profile.id),
        ("Owner", profile.owner_id),
        ("Application", profile.application_id),
        ("Approved version", profile.approved_version),
        ("State", profile.state),
        ("Restriction reason", profile.restriction_reason),
    )
    actions = tuple(
        (
            label,
            reverse(name, kwargs={"seller_id": profile.id}),
            True,
        )
        for label, name in (
            ("Suspend", "admin:seller-profile-suspend"),
            ("Restore", "admin:seller-profile-restore"),
            ("Revoke", "admin:seller-profile-revoke"),
        )
    )
    return render_admin(
        site,
        request,
        "admin/detail.html",
        {"title": "Seller", "fields": fields, "actions": actions},
    )


def _profile_action(site, request, seller_id, operation):
    return action_response(
        site,
        request,
        lambda: operation(
            seller_id=seller_id,
            reason=request.POST.get("reason", ""),
            context=operation_context(request),
        ),
        reverse("admin:seller-profile-detail", kwargs={"seller_id": seller_id}),
    )


@require_POST
def profile_suspend(request, site, seller_id):
    return _profile_action(site, request, seller_id, seller_public.suspend_seller)


@require_POST
def profile_restore(request, site, seller_id):
    return _profile_action(site, request, seller_id, seller_public.restore_seller)


@require_POST
def profile_revoke(request, site, seller_id):
    return _profile_action(site, request, seller_id, seller_public.revoke_seller)


def get_urls(site):
    return [
        path(
            "seller-applications/",
            _bind(site, application_list),
            name="seller-application-list",
        ),
        path(
            "seller-applications/<uuid:application_id>/",
            _bind(site, application_detail),
            name="seller-application-detail",
        ),
        path(
            "seller-applications/<uuid:application_id>/start-review/",
            _bind(site, application_start_review),
            name="seller-application-start-review",
        ),
        path(
            "seller-applications/<uuid:application_id>/request-changes/",
            _bind(site, application_request_changes),
            name="seller-application-request-changes",
        ),
        path(
            "seller-applications/<uuid:application_id>/approve/",
            _bind(site, application_approve),
            name="seller-application-approve",
        ),
        path(
            "seller-applications/<uuid:application_id>/reject/",
            _bind(site, application_reject),
            name="seller-application-reject",
        ),
        path("sellers/", _bind(site, profile_list), name="seller-profile-list"),
        path(
            "sellers/<uuid:seller_id>/",
            _bind(site, profile_detail),
            name="seller-profile-detail",
        ),
        path(
            "sellers/<uuid:seller_id>/suspend/",
            _bind(site, profile_suspend),
            name="seller-profile-suspend",
        ),
        path(
            "sellers/<uuid:seller_id>/restore/",
            _bind(site, profile_restore),
            name="seller-profile-restore",
        ),
        path(
            "sellers/<uuid:seller_id>/revoke/",
            _bind(site, profile_revoke),
            name="seller-profile-revoke",
        ),
    ]
