from functools import wraps

from django.urls import path, reverse
from django.views.decorators.http import require_GET, require_POST

import open_marketplace.outbox.public as outbox_public
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
def outbox_list(request, site):
    try:
        query = outbox_public.OutboxQuery(
            state="manual_review",
            message_type=request.GET.get("message_type") or None,
            limit=100,
            cursor=optional_uuid(request.GET.get("cursor"), name="cursor"),
        )
        messages = outbox_public.query_manual_review_messages(
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
                message.id,
                message.message_type,
                message.attempts,
                message.last_safe_error,
                message.created_at,
            ),
            "actions": (
                (
                    "Retry",
                    reverse("admin:outbox-retry", kwargs={"message_id": message.id}),
                    True,
                ),
            ),
        }
        for message in messages
    )
    return render_admin(
        site,
        request,
        "admin/list.html",
        {
            "title": "Manual outbox review",
            "headers": ("ID", "Type", "Attempts", "Safe error", "Created"),
            "rows": rows,
        },
    )


@require_POST
def outbox_retry(request, site, message_id):
    return action_response(
        site,
        request,
        lambda: outbox_public.retry_message_from_manual_review(
            message_id=message_id,
            reason=request.POST.get("reason", ""),
            context=operation_context(request),
            authorize=authorize,
        ),
        reverse("admin:outbox-list"),
    )


def get_urls(site):
    return [
        path("outbox/", _bind(site, outbox_list), name="outbox-list"),
        path(
            "outbox/<uuid:message_id>/retry/",
            _bind(site, outbox_retry),
            name="outbox-retry",
        ),
    ]
