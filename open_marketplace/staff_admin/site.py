from urllib.parse import urlencode
from uuid import UUID

from django.contrib.admin import AdminSite
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

import open_marketplace.access.public as access_public
import open_marketplace.audit.public as audit_public
from open_marketplace.common.errors import ApplicationError, InputRejected, PermissionDenied
from open_marketplace.common.types import OperationContext


EXPECTED_ERROR_MESSAGE = "The request could not be completed."


def operation_context(request):
    raw_session_id = request.session.get("session_id")
    try:
        session_id = UUID(str(raw_session_id))
    except (TypeError, ValueError, AttributeError):
        session_id = None
    return OperationContext(
        actor_account_id=(
            request.user.pk
            if getattr(request.user, "is_authenticated", False)
            else None
        ),
        session_id=session_id,
        request_id=request.request_id,
        source="admin",
        source_address=request.META.get("REMOTE_ADDR"),
        now=timezone.now(),
    )


def authorize(context, permission):
    return access_public.authorize(context=context, permission=permission)


def optional_uuid(value, *, name):
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise InputRejected(f"{name} is invalid.") from None


def redirect_303(location):
    response = HttpResponse(status=303)
    response["Location"] = location
    return response


def forbidden_response():
    return HttpResponse("Forbidden", status=403)


def render_admin(site, request, template_name, context=None, *, status=200):
    request.current_app = site.name
    rendered_context = {
        **site.each_context(request),
        "nav_links": site.navigation(request),
        **(context or {}),
    }
    return TemplateResponse(
        request,
        template_name,
        rendered_context,
        status=status,
    )


def expected_error_response(site, request):
    return render_admin(
        site,
        request,
        "admin/error.html",
        {"title": "Request failed", "message": EXPECTED_ERROR_MESSAGE},
    )


def action_response(site, request, operation, success_url):
    try:
        operation()
    except PermissionDenied:
        context = operation_context(request)
        if not audit_public.audit_entry_exists(
            request_id=context.request_id,
            action="access.permission_denied",
        ):
            audit_public.append_audit_entry(
                context=context,
                action="access.permission_denied",
                object_type="account",
                object_id=str(context.actor_account_id or context.request_id),
                result="denied",
                reason="permission_denied",
                before={},
                after={},
                effective_role=None,
            )
        return forbidden_response()
    except (ApplicationError, ObjectDoesNotExist, ValueError):
        return expected_error_response(site, request)
    return redirect_303(success_url)


class StaffAdminSite(AdminSite):
    site_header = "Open Marketplace staff"
    site_title = "Open Marketplace staff"
    index_title = "Service operations"

    def get_urls(self):
        from open_marketplace.staff_admin import (
            access_admin,
            audit_admin,
            identity_admin,
            outbox_admin,
            seller_admin,
        )

        custom_urls = [
            path("logout/", self.logout, name="logout"),
            *access_admin.get_urls(self),
            *identity_admin.get_urls(self),
            *seller_admin.get_urls(self),
            *audit_admin.get_urls(self),
            *outbox_admin.get_urls(self),
        ]
        built_in_urls = [url for url in super().get_urls() if url.name != "logout"]
        return custom_urls + built_in_urls

    def has_permission(self, request):
        cached = getattr(request, "_staff_admin_authorization", None)
        if cached is False:
            return False
        if cached is not None:
            return True
        if not getattr(request.user, "is_authenticated", False):
            request._staff_admin_authorization = False
            return False
        try:
            decision = access_public.check_permission(
                permission="audit.read",
                context=operation_context(request),
            )
        except (ApplicationError, ObjectDoesNotExist, ValueError, AttributeError):
            request._staff_admin_authorization = False
            return False
        request._staff_admin_authorization = decision
        return True

    def navigation(self, request):
        decision = getattr(request, "_staff_admin_authorization", None)
        roles = set(getattr(decision, "effective_roles", ()))
        links = []
        if "seller_reviewer" in roles:
            links.append(("Seller applications", reverse("admin:seller-application-list")))
        if "security_admin" in roles:
            links.extend(
                (
                    ("Staff invitations", reverse("admin:staff-invitation-list")),
                    ("Accounts", reverse("admin:account-list")),
                    ("Sellers", reverse("admin:seller-profile-list")),
                    ("Outbox", reverse("admin:outbox-list")),
                )
            )
        if roles:
            links.append(("Audit", reverse("admin:audit-list")))
        return links

    def index(self, request, extra_context=None):
        return render_admin(
            self,
            request,
            "admin/index.html",
            {"title": self.index_title, **(extra_context or {})},
        )

    def _safe_next(self, request):
        value = request.GET.get("next") or request.POST.get("next")
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
        return reverse("admin:index", current_app=self.name)

    @method_decorator(never_cache)
    @method_decorator(login_not_required)
    def login(self, request, extra_context=None):
        if request.method == "GET" and self.has_permission(request):
            return redirect_303(reverse("admin:index", current_app=self.name))
        target = self._safe_next(request)
        query = urlencode({"next": target})
        return redirect_303(f"{reverse('login')}?{query}")

    @method_decorator(never_cache)
    @method_decorator(csrf_protect)
    @method_decorator(login_not_required)
    def logout(self, request, extra_context=None):
        if request.method != "POST":
            return HttpResponse(status=405)
        response = HttpResponse(status=307)
        response["Location"] = reverse("logout")
        return response

    def password_change(self, request, extra_context=None):
        return redirect_303(reverse("password-change"))

    def password_change_done(self, request, extra_context=None):
        return redirect_303(reverse("password-change"))


staff_admin_site = StaffAdminSite(name="admin")
