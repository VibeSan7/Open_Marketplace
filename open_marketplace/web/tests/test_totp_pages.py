from datetime import timedelta
from uuid import uuid4

import pyotp
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.common.crypto import generate_one_time_token
from open_marketplace.identity.tests.web_fixtures import (
    Account,
    AccountSession,
    OneTimeToken,
    RecoveryCode,
    TotpCredential,
    TotpRequirement,
)


class TotpPageTests(TestCase):
    password = "Correct Horse Battery Staple 42!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.account = Account(
            email="owner@example.com",
            kind=Account.Kind.ORDINARY,
            state=Account.State.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.account.set_password(self.password)
        self.account.save()
        session = self.client.session
        session["seed"] = "authenticated"
        session.save()
        now = timezone.now()
        self.current = AccountSession.objects.create(
            account=self.account,
            django_session_key=session.session_key,
            created_at=now,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(days=30),
            reauthenticated_at=now,
            device_label="Current browser",
        )
        session["account_id"] = str(self.account.id)
        session["session_id"] = str(self.current.id)
        session.save()

    def _csrf_post(self, name, data=None):
        get_response = self.client.get(reverse(name))
        self.assertEqual(get_response.status_code, 200)
        token = self.client.cookies["csrftoken"].value
        return self.client.post(
            reverse(name),
            {"csrfmiddlewaretoken": token, **(data or {})},
        )

    def _begin_totp(self):
        response = self._csrf_post(
            "totp-setup",
            {"current_password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        return response.context["setup"]

    def _enable_totp(self):
        setup = self._begin_totp()
        code = pyotp.TOTP(setup.manual_secret).at(timezone.now())
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            reverse("totp-setup"),
            {
                "csrfmiddlewaretoken": token,
                "setup_id": str(setup.setup_id),
                "code": code,
            },
        )
        return setup, response

    def test_security_and_totp_routes_require_registry_authentication(self):
        anonymous = Client(enforce_csrf_checks=True)

        for name in (
            "security",
            "reauthenticate",
            "totp-setup",
            "totp-disable",
            "recovery-codes-replace",
        ):
            with self.subTest(name=name):
                response = anonymous.get(reverse(name))
                self.assertEqual(response.status_code, 303)
                self.assertTrue(response["Location"].startswith(reverse("login")))

    def test_totp_setup_requires_csrf_and_current_password(self):
        missing = self.client.post(
            reverse("totp-setup"),
            {"current_password": self.password},
        )
        self.assertEqual(missing.status_code, 403)

        rejected = self._csrf_post(
            "totp-setup",
            {"current_password": "wrong-password"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertNotContains(rejected, "wrong-password")
        self.assertFalse(TotpCredential.objects.filter(account=self.account).exists())

    def test_totp_setup_shows_secret_only_until_confirmation_and_codes_once(self):
        setup, response = self._enable_totp()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, setup.manual_secret)
        self.assertContains(response, "Резервные коды")
        codes = tuple(response.context["recovery_codes"])
        self.assertEqual(len(codes), 10)
        self.assertEqual(RecoveryCode.objects.filter(account=self.account).count(), 10)

        later = self.client.get(reverse("security"))
        for code in codes:
            self.assertNotContains(later, code)

    def test_reauthentication_is_csrf_protected_and_updates_registry(self):
        before = self.current.reauthenticated_at
        missing = self.client.post(
            reverse("reauthenticate"),
            {"password": self.password, "second_factor": ""},
        )
        self.assertEqual(missing.status_code, 403)

        response = self._csrf_post(
            "reauthenticate",
            {"password": self.password, "second_factor": ""},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("security"))
        self.current.refresh_from_db()
        self.assertGreaterEqual(self.current.reauthenticated_at, before)

    def test_recovery_code_replacement_shows_only_the_new_set_once(self):
        setup, enabled = self._enable_totp()
        old_codes = tuple(enabled.context["recovery_codes"])
        second_factor = pyotp.TOTP(setup.manual_secret).at(
            timezone.now() + timedelta(seconds=30)
        )

        response = self._csrf_post(
            "recovery-codes-replace",
            {"password": self.password, "second_factor": second_factor},
        )

        self.assertEqual(response.status_code, 200)
        new_codes = tuple(response.context["recovery_codes"])
        self.assertEqual(len(new_codes), 10)
        self.assertNotEqual(new_codes, old_codes)
        later = self.client.get(reverse("security"))
        for code in (*old_codes, *new_codes):
            self.assertNotContains(later, code)

    def test_optional_totp_disable_requires_csrf_and_disables_credential(self):
        setup, _ = self._enable_totp()
        code = pyotp.TOTP(setup.manual_secret).at(
            timezone.now() + timedelta(seconds=30)
        )
        missing = self.client.post(
            reverse("totp-disable"),
            {"password": self.password, "second_factor": code},
        )
        self.assertEqual(missing.status_code, 403)

        response = self._csrf_post(
            "totp-disable",
            {"password": self.password, "second_factor": code},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("security"))
        self.assertFalse(
            TotpCredential.objects.filter(
                account=self.account,
                disabled_at__isnull=True,
            ).exists()
        )

    def test_mandatory_totp_recovery_is_two_step_csrf_protected_and_does_not_login(self):
        target = Account(
            email="recovery@example.com",
            kind=Account.Kind.SERVICE,
            state=Account.State.ACTIVE,
            email_verified_at=timezone.now(),
        )
        target.set_password(self.password)
        target.save()
        raw_token, digest = generate_one_time_token()
        now = timezone.now()
        token = OneTimeToken.objects.create(
            account=target,
            purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
            token_digest=digest,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        TotpRequirement.objects.create(
            account=target,
            source_type=TotpRequirement.SourceType.STAFF_ROLE,
            source_id=uuid4(),
            created_at=now,
        )
        client = Client(enforce_csrf_checks=True)
        entry = client.get(
            reverse(
                "mandatory-totp-recovery-entry",
                kwargs={"raw_token": raw_token},
            )
        )
        self.assertEqual(entry.status_code, 303)
        clean_url = reverse("mandatory-totp-recovery")
        missing = client.post(clean_url, {"current_password": self.password})
        self.assertEqual(missing.status_code, 403)
        clean = client.get(clean_url)
        csrf = client.cookies["csrftoken"].value

        begin = client.post(
            clean_url,
            {"csrfmiddlewaretoken": csrf, "current_password": self.password},
        )

        self.assertEqual(clean.status_code, 200)
        self.assertEqual(begin.status_code, 200)
        setup = begin.context["setup"]
        self.assertContains(begin, setup.manual_secret)
        token.refresh_from_db()
        self.assertIsNone(token.used_at)

        code = pyotp.TOTP(setup.manual_secret).at(timezone.now())
        finish = client.post(
            clean_url,
            {"csrfmiddlewaretoken": csrf, "code": code},
        )

        self.assertEqual(finish.status_code, 200)
        self.assertEqual(len(finish.context["recovery_codes"]), 10)
        token.refresh_from_db()
        self.assertIsNotNone(token.used_at)
        self.assertTrue(
            TotpCredential.objects.filter(
                account=target,
                disabled_at__isnull=True,
            ).exists()
        )
        self.assertNotIn("account_id", client.session)
        self.assertNotIn("session_id", client.session)
