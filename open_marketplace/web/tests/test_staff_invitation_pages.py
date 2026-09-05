from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pyotp
from cryptography.fernet import Fernet
from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.access.tests.web_fixtures import (
    RoleAssignment,
    StaffInvitation,
    StaffInvitationAcceptance,
)
from open_marketplace.common.crypto import generate_one_time_token
from open_marketplace.identity.tests.web_fixtures import (
    Account,
    AccountSession,
    TotpCredential,
)


class StaffInvitationPageTests(TestCase):
    password = "Correct Horse Battery Staple 42!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def _invitation(self, email, role="seller_reviewer"):
        raw_token, digest = generate_one_time_token()
        now = timezone.now()
        invitation = StaffInvitation.objects.create(
            email=email,
            role=role,
            created_by_id=uuid4(),
            token_digest=digest,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        return raw_token, invitation

    def _entry(self, raw_token):
        return self.client.get(
            reverse("staff-invitation-entry", kwargs={"raw_token": raw_token})
        )

    def _csrf(self):
        response = self.client.get(reverse("staff-invitation-accept"))
        self.assertEqual(response.status_code, 200)
        return self.client.cookies["csrftoken"].value

    def _active_service_account(self, email="existing@example.com"):
        account = Account(
            email=email,
            kind=Account.Kind.SERVICE,
            state=Account.State.ACTIVE,
            email_verified_at=timezone.now(),
        )
        account.set_password(self.password)
        account.save()
        secret = pyotp.random_base32(length=32)
        TotpCredential.objects.create(
            account=account,
            encrypted_secret=Fernet(
                settings.TOTP_ENCRYPTION_KEY.encode("ascii")
            ).encrypt(secret.encode("ascii")),
            confirmed_at=timezone.now(),
            last_accepted_counter=0,
        )
        session = self.client.session
        session["seed"] = "authenticated"
        session.save()
        now = timezone.now()
        registry = AccountSession.objects.create(
            account=account,
            django_session_key=session.session_key,
            created_at=now,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(hours=12),
            reauthenticated_at=now,
            device_label="Service browser",
        )
        session["account_id"] = str(account.id)
        session["session_id"] = str(registry.id)
        session.save()
        return account, registry, secret

    def test_staff_invitation_entry_is_token_free_and_accept_post_requires_csrf(self):
        raw_token, invitation = self._invitation("new@example.com")

        entry = self._entry(raw_token)
        missing = self.client.post(
            reverse("staff-invitation-accept"),
            {"password": self.password},
        )

        self.assertEqual(entry.status_code, 303)
        self.assertEqual(entry["Location"], reverse("staff-invitation-accept"))
        self.assertNotIn(raw_token, entry["Location"])
        self.assertNotIn(raw_token, repr(dict(self.client.session)))
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing["Cache-Control"], "no-store")
        self.assertEqual(missing["Referrer-Policy"], "no-referrer")
        self.assertFalse(
            StaffInvitationAcceptance.objects.filter(invitation=invitation).exists()
        )
        self.assertFalse(RoleAssignment.objects.exists())

    def test_new_service_account_gets_no_role_until_final_totp_post(self):
        raw_token, invitation = self._invitation("new@example.com", "security_admin")
        self._entry(raw_token)
        csrf = self._csrf()

        begin = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "password": self.password},
        )

        self.assertEqual(begin.status_code, 200)
        setup = begin.context["setup"]
        self.assertIsNotNone(setup)
        self.assertContains(begin, setup.manual_secret)
        self.assertFalse(RoleAssignment.objects.exists())
        self.assertNotIn(raw_token, begin.content.decode())
        self.assertNotIn(raw_token, repr(dict(self.client.session)))

        code = pyotp.TOTP(setup.manual_secret).at(timezone.now())
        finish = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "totp_code": code},
        )

        self.assertEqual(finish.status_code, 200)
        self.assertContains(finish, "Recovery codes")
        self.assertEqual(len(finish.context["recovery_codes"]), 10)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        acceptance = StaffInvitationAcceptance.objects.get(invitation=invitation)
        self.assertIsNotNone(acceptance.consumed_at)
        self.assertTrue(
            RoleAssignment.objects.filter(
                account_id=acceptance.account_id,
                role="security_admin",
                state="active",
            ).exists()
        )

        replay = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "totp_code": code},
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(RoleAssignment.objects.count(), 1)

    def test_existing_service_account_authenticates_then_adds_role_without_new_codes(self):
        account, _, secret = self._active_service_account()
        raw_token, invitation = self._invitation(account.email)
        self._entry(raw_token)
        csrf = self._csrf()

        begin = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "password": self.password},
        )

        self.assertEqual(begin.status_code, 200)
        self.assertIsNone(begin.context["setup"])
        self.assertFalse(RoleAssignment.objects.exists())

        code = pyotp.TOTP(secret).at(timezone.now())
        finish = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "totp_code": code},
        )

        self.assertEqual(finish.status_code, 303)
        self.assertEqual(finish["Location"], reverse("security"))
        self.assertNotIn("recovery_codes", finish.context or {})
        self.assertTrue(
            RoleAssignment.objects.filter(
                account_id=account.id,
                role="seller_reviewer",
                state="active",
            ).exists()
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)

    def test_staff_continuation_expires_after_five_minutes_without_role(self):
        raw_token, invitation = self._invitation("new@example.com")
        self._entry(raw_token)
        csrf = self._csrf()
        started = timezone.now()
        with patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=started,
        ):
            begin = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "password": self.password},
            )
        setup = begin.context["setup"]
        code = pyotp.TOTP(setup.manual_secret).at(timezone.now())

        with patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=started + timedelta(minutes=5),
        ):
            finish = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "totp_code": code},
            )

        self.assertEqual(finish.status_code, 200)
        self.assertFalse(RoleAssignment.objects.exists())
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
