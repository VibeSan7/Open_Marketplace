from datetime import datetime
from functools import wraps

from django.urls import path
from django.views.decorators.http import require_GET

import open_marketplace.audit.public as audit_public
from open_marketplace.common.errors import ApplicationError, InputRejected, PermissionDenied
from open_marketplace.staff_admin.site import (
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


def _optional_datetime(value, *, name):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError):
        raise InputRejected(f"{name} is invalid.") from None


@require_GET
def audit_list(request, site):
    try:
        query = audit_public.AuditQuery(
            from_at=_optional_datetime(request.GET.get("from"), name="from"),
            to_at=_optional_datetime(request.GET.get("to"), name="to"),
            actor_id=optional_uuid(request.GET.get("actor_id"), name="actor_id"),
            action=request.GET.get("action") or None,
            object_type=request.GET.get("object_type") or None,
            object_id=request.GET.get("object_id") or None,
            result=request.GET.get("result") or None,
            limit=100,
            cursor=optional_uuid(request.GET.get("cursor"), name="cursor"),
        )
        entries = audit_public.query_audit_entries(
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
                entry.occurred_at,
                entry.action,
                entry.object_type,
                entry.object_id,
                entry.result,
            ),
        }
        for entry in entries
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": "Audit",
            "headers": ("Occurred", "Action", "Object type", "Object ID", "Result"),
            "rows": rows,
        },
    )


def get_urls(site):
    return [path("audit/", _bind(site, audit_list), name="audit-list")]
