from functools import wraps

from django.urls import path, reverse
from django.views.decorators.http import require_GET, require_POST

import open_marketplace.access.public as access_public
from open_marketplace.staff_admin.site import (
    action_response,
    expected_error_response,
    forbidden_response,
    operation_context,
    optional_uuid,
    render_admin,
)
from open_marketplace.common.errors import ApplicationError, PermissionDenied


def _bind(site, view):
    @wraps(view)
    def bound(request, *args, **kwargs):
        return view(request, site, *args, **kwargs)

    return site.admin_view(bound)


@require_GET
def invitation_list(request, site):
    try:
        query = access_public.StaffInvitationQuery(
            state=request.GET.get("state") or None,
            role=request.GET.get("role") or None,
            canonical_email=request.GET.get("email") or None,
            limit=100,
            cursor=optional_uuid(request.GET.get("cursor"), name="cursor"),
        )
        invitations = access_public.list_staff_invitations(
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
                invitation.email,
                invitation.role,
                invitation.state,
                invitation.expires_at,
            ),
            "actions": (
                (
                    "Revoke",
                    reverse(
                        "admin:staff-invitation-revoke",
                        kwargs={"invitation_id": invitation.id},
                    ),
                    True,
                ),
            )
            if invitation.state == "pending"
            else (),
        }
        for invitation in invitations
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": "Staff invitations",
            "headers": ("Email", "Role", "State", "Expires"),
            "rows": rows,
            "invitation_create_url": reverse("admin:staff-invitation-create"),
        },
    )


@require_POST
def invitation_create(request, site):
    return action_response(
        site,
        request,
        lambda: access_public.invite_staff_member(
            email=request.POST.get("email", ""),
            role=request.POST.get("role", ""),
            context=operation_context(request),
        ),
        reverse("admin:staff-invitation-list"),
    )


@require_POST
def invitation_revoke(request, site, invitation_id):
    return action_response(
        site,
        request,
        lambda: access_public.revoke_staff_invitation(
            invitation_id=invitation_id,
            reason=request.POST.get("reason", ""),
            context=operation_context(request),
        ),
        reverse("admin:staff-invitation-list"),
    )


@require_GET
def role_list(request, site, account_id):
    try:
        roles = access_public.list_active_roles(
            account_id=account_id,
            context=operation_context(request),
        )
    except PermissionDenied:
        return forbidden_response()
    except (ApplicationError, ValueError):
        return expected_error_response(site, request)

    rows = tuple(
        {
            "values": (role.role, role.active_from),
            "actions": (
                (
                    "Revoke",
                    reverse("admin:role-revoke", kwargs={"assignment_id": role.id}),
                    True,
                ),
            ),
        }
        for role in roles
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": f"Active roles for {account_id}",
            "headers": ("Role", "Active from"),
            "rows": rows,
        },
    )


@require_POST
def role_revoke(request, site, assignment_id):
    return action_response(
        site,
        request,
        lambda: access_public.revoke_staff_role(
            assignment_id=assignment_id,
            reason=request.POST.get("reason", ""),
            context=operation_context(request),
        ),
        reverse("admin:account-list"),
    )


def get_urls(site):
    return [
        path("staff/invitations/", _bind(site, invitation_list), name="staff-invitation-list"),
        path(
            "staff/invitations/create/",
            _bind(site, invitation_create),
            name="staff-invitation-create",
        ),
        path(
            "staff/invitations/<uuid:invitation_id>/revoke/",
            _bind(site, invitation_revoke),
            name="staff-invitation-revoke",
        ),
        path(
            "staff/accounts/<uuid:account_id>/roles/",
            _bind(site, role_list),
            name="role-list",
        ),
        path(
            "staff/roles/<uuid:assignment_id>/revoke/",
            _bind(site, role_revoke),
            name="role-revoke",
        ),
    ]
