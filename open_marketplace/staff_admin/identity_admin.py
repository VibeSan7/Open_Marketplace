from functools import wraps

from django.core.exceptions import ObjectDoesNotExist
from django.urls import path, reverse
from django.views.decorators.http import require_GET, require_POST

import open_marketplace.access.public as access_public
import open_marketplace.identity.public as identity_public
from open_marketplace.common.errors import ApplicationError, PermissionDenied
from open_marketplace.staff_admin.site import (
    action_response,
    authorize,
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
def account_list(request, site):
    try:
        query = identity_public.AccountQuery(
            kind=request.GET.get("kind") or None,
            state=request.GET.get("state") or None,
            canonical_email=request.GET.get("email") or None,
            limit=100,
            cursor=optional_uuid(request.GET.get("cursor"), name="cursor"),
        )
        accounts = identity_public.query_accounts(
            query=query,
            context=operation_context(request),
            authorize=authorize,
        )
    except PermissionDenied:
        return forbidden_response()
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    rows = tuple(
        {
            "values": (
                account.email,
                account.kind,
                account.state,
                "yes" if account.totp_enabled else "no",
            ),
            "detail_url": reverse(
                "admin:account-detail",
                kwargs={"account_id": account.id},
            ),
        }
        for account in accounts
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": "Accounts",
            "headers": ("Email", "Kind", "State", "TOTP"),
            "rows": rows,
        },
    )


@require_GET
def account_detail(request, site, account_id):
    try:
        context = operation_context(request)
        access_public.check_permission(permission="account.read", context=context)
        account = identity_public.get_account_snapshot(account_id)
        roles = access_public.list_active_roles(account_id=account_id, context=context)
    except PermissionDenied:
        return forbidden_response()
    except ObjectDoesNotExist:
        return render_admin(
            site,
            request,
            "admin/error.html",
            {"title": "Not found", "message": "The requested account was not found."},
            status=404,
        )
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    fields = (
        ("ID", account.id),
        ("Email", account.email),
        ("Kind", account.kind),
        ("State", account.state),
        ("Email verified", account.email_verified_at),
        ("TOTP enabled", account.totp_enabled),
        ("Active roles", ", ".join(role.role for role in roles) or "none"),
    )
    actions = (
        (
            "Block",
            reverse("admin:account-block", kwargs={"account_id": account.id}),
            True,
        ),
        (
            "Unblock",
            reverse("admin:account-unblock", kwargs={"account_id": account.id}),
            True,
        ),
        (
            "Recover mandatory TOTP",
            reverse("admin:account-recover-totp", kwargs={"account_id": account.id}),
            True,
        ),
    )
    return render_admin(
        site,
        request,
        "admin/detail.html",
        {
            "title": "Account",
            "fields": fields,
            "actions": actions,
            "role_list_url": reverse(
                "admin:role-list",
                kwargs={"account_id": account.id},
            ),
        },
    )


def _account_action(site, request, account_id, operation):
    return action_response(
        site,
        request,
        lambda: operation(
            account_id=account_id,
            reason=request.POST.get("reason", ""),
            context=operation_context(request),
            authorize=authorize,
        ),
        reverse("admin:account-detail", kwargs={"account_id": account_id}),
    )


@require_POST
def account_block(request, site, account_id):
    return _account_action(site, request, account_id, identity_public.block_account)


@require_POST
def account_unblock(request, site, account_id):
    return _account_action(site, request, account_id, identity_public.unblock_account)


@require_POST
def account_recover_totp(request, site, account_id):
    return _account_action(
        site,
        request,
        account_id,
        identity_public.recover_mandatory_totp,
    )


def get_urls(site):
    return [
        path("accounts/", _bind(site, account_list), name="account-list"),
        path(
            "accounts/<uuid:account_id>/",
            _bind(site, account_detail),
            name="account-detail",
        ),
        path(
            "accounts/<uuid:account_id>/block/",
            _bind(site, account_block),
            name="account-block",
        ),
        path(
            "accounts/<uuid:account_id>/unblock/",
            _bind(site, account_unblock),
            name="account-unblock",
        ),
        path(
            "accounts/<uuid:account_id>/recover-totp/",
            _bind(site, account_recover_totp),
            name="account-recover-totp",
        ),
    ]
