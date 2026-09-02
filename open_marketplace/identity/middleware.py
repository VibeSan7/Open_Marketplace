from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from open_marketplace.identity.models import Account, AccountSession

_ACTIVITY_UPDATE_INTERVAL = timedelta(minutes=1)


class SessionRegistryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = AnonymousUser()
        if not hasattr(request, "session"):
            return self.get_response(request)

        raw_account_id = request.session.get("account_id")
        raw_session_id = request.session.get("session_id")
        if raw_account_id is None and raw_session_id is None:
            return self.get_response(request)

        try:
            account_id = UUID(str(raw_account_id))
            session_id = UUID(str(raw_session_id))
        except (TypeError, ValueError, AttributeError):
            request.session.flush()
            return self.get_response(request)

        django_session_key = request.session.session_key
        now = timezone.now()
        registry = None
        with transaction.atomic():
            candidate = (
                AccountSession.objects.select_for_update()
                .select_related("account")
                .filter(
                    pk=session_id,
                    account_id=account_id,
                    django_session_key=django_session_key,
                )
                .first()
            )
            if candidate is not None and self._is_valid(candidate, now):
                threshold = now - _ACTIVITY_UPDATE_INTERVAL
                if candidate.last_activity_at <= threshold:
                    updated = AccountSession.objects.filter(
                        pk=candidate.id,
                        revoked_at__isnull=True,
                        absolute_expires_at__gt=now,
                        last_activity_at__lte=threshold,
                    ).update(last_activity_at=now)
                    if updated:
                        candidate.last_activity_at = now
                registry = candidate

        if registry is None:
            request.session.flush()
        else:
            request.user = registry.account
        return self.get_response(request)

    @staticmethod
    def _is_valid(registry, now):
        if registry.account.state != Account.State.ACTIVE:
            return False
        if registry.revoked_at is not None or now >= registry.absolute_expires_at:
            return False
        if (
            registry.account.kind == Account.Kind.SERVICE
            and now >= registry.last_activity_at + settings.SERVICE_SESSION_IDLE_TTL
        ):
            return False
        return Session.objects.filter(
            session_key=registry.django_session_key,
            expire_date__gt=now,
        ).exists()
