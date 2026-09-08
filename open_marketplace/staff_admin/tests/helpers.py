from datetime import timedelta
from uuid import uuid4

from django.test import Client
from django.utils import timezone

from open_marketplace.access.tests.test_roles import AccessTestCase


class StaffAdminTestCase(AccessTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def authenticate_staff(
        self,
        *roles,
        kind="service",
        state="active",
        verified=True,
        with_totp=True,
        roles_active=True,
        reauthenticated_at=None,
    ):
        account = self.create_account(
            kind=kind,
            state=state,
            verified=verified,
        )
        if with_totp:
            self.enable_totp(account)
        for role in roles:
            if roles_active:
                self.seed_assignment(account, role)
            else:
                self.seed_assignment(
                    account,
                    role,
                    state="revoked",
                    revoked_by_id=uuid4(),
                    revoked_reason="Test fixture revocation.",
                    revoked_at=timezone.now(),
                )

        browser_session = self.client.session
        browser_session["fixture"] = "bound"
        browser_session.save()
        now = timezone.now()
        registry = self.create_registry(
            account,
            django_key=browser_session.session_key,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(days=1),
            reauthenticated_at=(
                now - timedelta(minutes=1)
                if reauthenticated_at is None
                else reauthenticated_at
            ),
        )
        browser_session["account_id"] = str(account.id)
        browser_session["session_id"] = str(registry.id)
        browser_session.save()
        return account, registry

    def reset_client(self):
        self.client = Client(enforce_csrf_checks=True)

    def csrf_token(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        return self.client.cookies["csrftoken"].value

    def csrf_post(self, name, data=None, *, kwargs=None, **extra):
        from django.urls import reverse

        token = self.csrf_token()
        return self.client.post(
            reverse(name, kwargs=kwargs),
            {"csrfmiddlewaretoken": token, **(data or {})},
            **extra,
        )
