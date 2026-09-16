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
from open_marketplace.web.errors import EXPECTED_ERROR_MESSAGE


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

    def test_staff_invitation_page_uses_russian_copy(self):
        raw_token, _ = self._invitation("copy-check@example.test")
        self._entry(raw_token)

        response = self.client.get(reverse("staff-invitation-accept"))

        self.assertContains(response, "Принять приглашение сотрудника")
        self.assertContains(response, "Продолжить")
        self.assertNotContains(response, "Accept staff invitation")
        self.assertNotContains(response, ">Continue<")

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
        self.assertEqual(missing["Referrer-Policy"], "same-origin")
        self.assertFalse(
            StaffInvitationAcceptance.objects.filter(invitation=invitation).exists()
        )
        self.assertFalse(RoleAssignment.objects.exists())

    def test_signed_in_account_gets_sign_out_guidance_for_another_invitation(self):
        account, registry, _ = self._active_service_account()
        raw_token, invitation = self._invitation("other-staff@example.com")
        self._entry(raw_token)
        csrf = self._csrf()

        response = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "password": self.password},
        )

        self.assertContains(response, EXPECTED_ERROR_MESSAGE)
        self.assertContains(response, "выйдите и снова откройте ссылку приглашения")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIsNone(response.context["setup"])
        self.assertNotIn(raw_token, response.content.decode())
        self.assertNotContains(response, invitation.email)
        self.assertFalse(Account.objects.filter(email=invitation.email).exists())
        self.assertFalse(
            StaffInvitationAcceptance.objects.filter(invitation=invitation).exists()
        )
        self.assertFalse(RoleAssignment.objects.exists())
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
        self.assertIsNone(invitation.revoked_at)
        registry.refresh_from_db()
        self.assertIsNone(registry.revoked_at)
        self.assertEqual(self.client.session["account_id"], str(account.id))
        self.assertEqual(self.client.session["session_id"], str(registry.id))

    def test_invalid_invitation_guidance_depends_only_on_current_sign_in(self):
        for signed_in in (False, True):
            with self.subTest(signed_in=signed_in):
                self.client = Client(enforce_csrf_checks=True)
                if signed_in:
                    self._active_service_account()
                raw_token, _ = generate_one_time_token()
                self._entry(raw_token)
                csrf = self._csrf()

                response = self.client.post(
                    reverse("staff-invitation-accept"),
                    {"csrfmiddlewaretoken": csrf, "password": self.password},
                )

                self.assertContains(response, EXPECTED_ERROR_MESSAGE)
                if signed_in:
                    self.assertContains(
                        response, "выйдите и снова откройте ссылку приглашения"
                    )
                else:
                    self.assertNotContains(response, "sign out")
                self.assertIsNone(response.context["setup"])
                self.assertNotIn(raw_token, response.content.decode())
                self.assertFalse(StaffInvitationAcceptance.objects.exists())
                self.assertFalse(RoleAssignment.objects.exists())

    def test_live_new_service_retry_shows_guidance_without_new_secret_or_role(self):
        raw_token, invitation = self._invitation("live-retry@example.com")
        started = timezone.now()
        with patch(
            "open_marketplace.web.identity_views.timezone.now",
            return_value=started,
        ), patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=started,
        ):
            self._entry(raw_token)
            csrf = self._csrf()
            initial = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "password": self.password},
            )
            self.assertEqual(initial.status_code, 200)
            initial_setup = initial.context["setup"]
            self.assertIsNotNone(initial_setup)
            acceptance = StaffInvitationAcceptance.objects.get(invitation=invitation)
            acceptance_id = acceptance.id

            self.client = Client(enforce_csrf_checks=True)
            self._entry(raw_token)
            csrf = self._csrf()
            repeated = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "password": self.password},
            )

            self.assertContains(repeated, "Настройка приложения для входа уже начата.")
            self.assertContains(repeated, "введите код из него")
            self.assertContains(repeated, "через 10 минут после её начала")
            self.assertContains(repeated, "выйдите из аккаунта")
            self.assertContains(repeated, "снова откройте ссылку приглашения и введите тот же пароль")
            self.assertContains(repeated, "Если приглашение ещё действительно")
            self.assertIsNone(repeated.context["setup"])
            self.assertNotContains(repeated, initial_setup.manual_secret)
            self.assertNotContains(repeated, initial_setup.provisioning_uri)
            self.assertNotIn(raw_token, repeated.content.decode())
            self.assertNotIn(raw_token, repr(dict(self.client.session)))
            self.assertEqual(repeated["Cache-Control"], "no-store")
            self.assertEqual(repeated["Referrer-Policy"], "same-origin")
            acceptance.refresh_from_db()
            invitation.refresh_from_db()
            self.assertEqual(acceptance.id, acceptance_id)
            self.assertEqual(acceptance.totp_setup_id, initial_setup.setup_id)
            self.assertIsNone(acceptance.consumed_at)
            self.assertIsNone(invitation.accepted_at)
            self.assertFalse(RoleAssignment.objects.exists())
            self.assertFalse(TotpCredential.objects.filter(account_id=acceptance.account_id).exists())

            finish = self.client.post(
                reverse("staff-invitation-accept"),
                {
                    "csrfmiddlewaretoken": csrf,
                    "totp_code": pyotp.TOTP(initial_setup.manual_secret).at(started),
                },
            )

        self.assertContains(finish, "Резервные коды")
        invitation.refresh_from_db()
        acceptance.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertIsNotNone(acceptance.consumed_at)
        self.assertTrue(
            RoleAssignment.objects.filter(
                account_id=acceptance.account_id, role="seller_reviewer", state="active"
            ).exists()
        )

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
        self.assertNotContains(begin, "Настройка приложения для входа уже начата.")
        self.assertFalse(RoleAssignment.objects.exists())
        self.assertNotIn(raw_token, begin.content.decode())
        self.assertNotIn(raw_token, repr(dict(self.client.session)))

        code = pyotp.TOTP(setup.manual_secret).at(timezone.now())
        finish = self.client.post(
            reverse("staff-invitation-accept"),
            {"csrfmiddlewaretoken": csrf, "totp_code": code},
        )

        self.assertEqual(finish.status_code, 200)
        self.assertContains(finish, "Резервные коды")
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

    def test_fresh_browser_reopens_expired_new_service_setup_and_accepts_invitation(self):
        raw_token, invitation = self._invitation("expired-web-staff@example.com", "security_admin")
        started = timezone.now()
        with patch(
            "open_marketplace.web.identity_views.timezone.now",
            return_value=started,
        ), patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=started,
        ):
            entry = self._entry(raw_token)
            csrf = self._csrf()
            initial = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "password": self.password},
            )

        self.assertEqual(entry.status_code, 303)
        old_setup = initial.context["setup"]
        self.assertIsNotNone(old_setup)
        expired_at = old_setup.expires_at

        fresh = Client(enforce_csrf_checks=True)
        with patch(
            "open_marketplace.web.identity_views.timezone.now",
            return_value=expired_at,
        ), patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=expired_at,
        ):
            reopened = fresh.get(
                reverse("staff-invitation-entry", kwargs={"raw_token": raw_token})
            )
            csrf_page = fresh.get(reverse("staff-invitation-accept"))
            self.assertEqual(csrf_page.status_code, 200)
            restarted = fresh.post(
                reverse("staff-invitation-accept"),
                {
                    "csrfmiddlewaretoken": fresh.cookies["csrftoken"].value,
                    "password": self.password,
                },
            )

        self.assertEqual(reopened.status_code, 303)
        self.assertEqual(restarted.status_code, 200)
        new_setup = restarted.context["setup"]
        self.assertIsNotNone(new_setup)
        self.assertNotEqual(new_setup.setup_id, old_setup.setup_id)
        self.assertNotContains(restarted, "Настройка приложения для входа уже начата.")
        self.assertNotIn(raw_token, restarted.content.decode())

        with patch(
            "open_marketplace.web.identity_views.timezone.now",
            return_value=expired_at,
        ), patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=expired_at,
        ):
            finish = fresh.post(
                reverse("staff-invitation-accept"),
                {
                    "csrfmiddlewaretoken": fresh.cookies["csrftoken"].value,
                    "totp_code": pyotp.TOTP(new_setup.manual_secret).at(expired_at),
                },
            )

        self.assertEqual(finish.status_code, 200)
        self.assertContains(finish, "Резервные коды")
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

    def test_expired_restart_rate_limit_is_neutral_through_http(self):
        raw_token, invitation = self._invitation("expired-web-throttled@example.com")
        started = timezone.now()
        with patch(
            "open_marketplace.web.identity_views.timezone.now",
            return_value=started,
        ), patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=started,
        ):
            self._entry(raw_token)
            csrf = self._csrf()
            initial = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "password": self.password},
            )
        expired_at = initial.context["setup"].expires_at

        with patch(
            "open_marketplace.web.identity_views.timezone.now",
            return_value=expired_at,
        ), patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=expired_at,
        ):
            for _ in range(settings.LOGIN_THROTTLE_THRESHOLD):
                self._entry(raw_token)
                failed = self.client.post(
                    reverse("staff-invitation-accept"),
                    {
                        "csrfmiddlewaretoken": csrf,
                        "password": f"Wrong password {uuid4().hex}",
                    },
                )
                self.assertEqual(failed.status_code, 200)

            self._entry(raw_token)
            limited = self.client.post(
                reverse("staff-invitation-accept"),
                {"csrfmiddlewaretoken": csrf, "password": self.password},
            )

        self.assertEqual(limited.status_code, 200)
        self.assertContains(limited, EXPECTED_ERROR_MESSAGE)
        self.assertIsNone(limited.context["setup"])
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
        acceptance = StaffInvitationAcceptance.objects.get(invitation=invitation)
        self.assertIsNone(acceptance.consumed_at)

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
        self.assertNotContains(begin, "Настройка приложения для входа уже начата.")
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
