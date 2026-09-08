from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from open_marketplace.identity.models import SecurityThrottle

_BATCH_SIZE = 1000
_EMAIL_SCOPES = (
    SecurityThrottle.Scope.REGISTRATION_EMAIL,
    SecurityThrottle.Scope.PASSWORD_RESET_EMAIL,
    SecurityThrottle.Scope.STAFF_INVITATION_EMAIL,
)


class Command(BaseCommand):
    help = "Delete expired security throttle rows in bounded batches."

    def handle(self, *args, **options):
        now = timezone.now()
        login_cutoff = (
            now
            - settings.LOGIN_THROTTLE_WINDOW
            - timedelta(seconds=max(settings.LOGIN_THROTTLE_DELAYS))
        )
        email_cutoff = now - settings.EMAIL_THROTTLE_WINDOW
        expired = (
            Q(
                scope=SecurityThrottle.Scope.LOGIN,
                window_started_at__lt=login_cutoff,
            )
            | Q(
                scope__in=_EMAIL_SCOPES,
                window_started_at__lt=email_cutoff,
            )
        ) & (Q(blocked_until__isnull=True) | Q(blocked_until__lte=now))

        total = 0
        while True:
            with transaction.atomic():
                row_ids = tuple(
                    SecurityThrottle.objects.filter(expired)
                    .select_for_update(skip_locked=True)
                    .order_by("pk")
                    .values_list("pk", flat=True)[:_BATCH_SIZE]
                )
                if not row_ids:
                    break
                deleted, _ = SecurityThrottle.objects.filter(pk__in=row_ids).delete()
                total += deleted

        self.stdout.write(f"Deleted {total} expired security throttle rows.")
