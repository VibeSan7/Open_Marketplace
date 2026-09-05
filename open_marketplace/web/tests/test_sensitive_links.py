import json
import logging
import os
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.common.crypto import generate_one_time_token
from open_marketplace.identity.tests.web_fixtures import Account, OneTimeToken


class SensitiveLinkTests(TestCase):
    password = "Correct Horse Battery Staple 42!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def _account(self, *, state=Account.State.PENDING_EMAIL_VERIFICATION):
        account = Account(
            email="person@example.com",
            kind=Account.Kind.ORDINARY,
            state=state,
            email_verified_at=(timezone.now() if state == Account.State.ACTIVE else None),
        )
        account.set_password(self.password)
        account.save()
        return account

    def _token(self, account, purpose):
        raw_token, digest = generate_one_time_token()
        now = timezone.now()
        token = OneTimeToken.objects.create(
            account=account,
            purpose=purpose,
            token_digest=digest,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        return raw_token, token

    def _csrf_post(self, name, data=None):
        url = reverse(name)
        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        csrf = self.client.cookies["csrftoken"].value
        return self.client.post(
            url,
            {"csrfmiddlewaretoken": csrf, **(data or {})},
        )

    def test_sensitive_entry_routes_exchange_token_for_clean_url_without_mutation(self):
        cases = (
            ("verify-email-entry", "verify-email-complete", "/identity/verify-email/{token}/"),
            ("password-reset-entry", "password-reset-confirm", "/identity/reset-password/{token}/"),
            (
                "mandatory-totp-recovery-entry",
                "mandatory-totp-recovery",
                "/identity/recover-mandatory-totp/{token}/",
            ),
            (
                "staff-invitation-entry",
                "staff-invitation-accept",
                "/access/staff-invitation/{token}/",
            ),
        )
        sentinel = "S" * 43

        for entry_name, clean_name, expected_path in cases:
            with self.subTest(entry_name=entry_name):
                client = Client(enforce_csrf_checks=True)
                entry_path = reverse(entry_name, kwargs={"raw_token": sentinel})
                self.assertEqual(entry_path, expected_path.format(token=sentinel))
                response = client.get(entry_path)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response["Location"], reverse(clean_name))
                self.assertEqual(response["Cache-Control"], "no-store")
                self.assertEqual(response["Referrer-Policy"], "no-referrer")
                self.assertNotIn(sentinel, response.content.decode())
                self.assertNotIn(sentinel, response["Location"])
                self.assertNotIn(sentinel, str(response.headers))
                self.assertNotIn(sentinel, repr(dict(client.session)))

    def test_email_verification_clean_post_consumes_envelope_and_domain_token_once(self):
        account = self._account()
        raw_token, token = self._token(account, OneTimeToken.Purpose.EMAIL_VERIFICATION)
        entry = self.client.get(
            reverse("verify-email-entry", kwargs={"raw_token": raw_token})
        )
        self.assertEqual(entry.status_code, 303)

        response = self._csrf_post("verify-email-complete")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, raw_token)
        account.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(account.state, Account.State.ACTIVE)
        self.assertIsNotNone(token.used_at)

        replay = self._csrf_post("verify-email-complete")
        self.assertEqual(replay.status_code, 200)
        self.assertNotContains(replay, raw_token)

    def test_password_reset_clean_post_consumes_envelope_and_clears_token(self):
        account = self._account(state=Account.State.ACTIVE)
        raw_token, token = self._token(account, OneTimeToken.Purpose.PASSWORD_RESET)
        self.client.get(
            reverse("password-reset-entry", kwargs={"raw_token": raw_token})
        )
        new_password = "Replacement Password 73!"

        response = self._csrf_post(
            "password-reset-confirm",
            {"new_password": new_password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, raw_token)
        self.assertNotContains(response, new_password)
        account.refresh_from_db()
        token.refresh_from_db()
        self.assertTrue(account.check_password(new_password))
        self.assertIsNotNone(token.used_at)

    def test_envelope_is_session_bound_purpose_bound_and_single_use(self):
        account = self._account()
        raw_token, token = self._token(account, OneTimeToken.Purpose.EMAIL_VERIFICATION)
        source = Client(enforce_csrf_checks=True)
        source.get(reverse("verify-email-entry", kwargs={"raw_token": raw_token}))
        source_values = dict(source.session)
        self.assertEqual(len(source_values), 1)

        target = Client(enforce_csrf_checks=True)
        target_session = target.session
        target_session.update(source_values)
        target_session.save()
        clean = target.get(reverse("verify-email-complete"))
        csrf = target.cookies["csrftoken"].value
        cross_session = target.post(
            reverse("verify-email-complete"),
            {"csrfmiddlewaretoken": csrf},
        )
        self.assertEqual(clean.status_code, 200)
        self.assertEqual(cross_session.status_code, 200)

        wrong_purpose = source.get(reverse("password-reset-confirm"))
        csrf = source.cookies["csrftoken"].value
        wrong_purpose = source.post(
            reverse("password-reset-confirm"),
            {"csrfmiddlewaretoken": csrf, "new_password": "Another Password 82!"},
        )
        self.assertEqual(wrong_purpose.status_code, 200)
        token.refresh_from_db()
        self.assertIsNone(token.used_at)

    def test_initial_envelope_expires_after_ten_minutes(self):
        account = self._account()
        raw_token, token = self._token(account, OneTimeToken.Purpose.EMAIL_VERIFICATION)
        started = timezone.now()
        with patch("open_marketplace.web.sensitive_links.timezone.now", return_value=started):
            self.client.get(
                reverse("verify-email-entry", kwargs={"raw_token": raw_token})
            )
        self.client.get(reverse("verify-email-complete"))
        csrf = self.client.cookies["csrftoken"].value

        with patch(
            "open_marketplace.web.sensitive_links.timezone.now",
            return_value=started + timedelta(minutes=10),
        ):
            response = self.client.post(
                reverse("verify-email-complete"),
                {"csrfmiddlewaretoken": csrf},
            )

        self.assertEqual(response.status_code, 200)
        token.refresh_from_db()
        self.assertIsNone(token.used_at)

    def test_clean_sensitive_forms_are_no_store_no_referrer_and_csrf_protected(self):
        account = self._account()
        raw_token, token = self._token(account, OneTimeToken.Purpose.EMAIL_VERIFICATION)
        self.client.get(reverse("verify-email-entry", kwargs={"raw_token": raw_token}))

        clean = self.client.get(reverse("verify-email-complete"))
        missing_csrf = self.client.post(reverse("verify-email-complete"))

        self.assertEqual(clean["Cache-Control"], "no-store")
        self.assertEqual(clean["Referrer-Policy"], "no-referrer")
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(missing_csrf["Cache-Control"], "no-store")
        self.assertEqual(missing_csrf["Referrer-Policy"], "no-referrer")
        token.refresh_from_db()
        self.assertIsNone(token.used_at)

    def test_sensitive_route_logging_filter_redacts_path_tokens(self):
        from open_marketplace.web.logging import SensitiveRouteFilter

        raw_token = "T" * 43
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            1,
            f"GET /identity/verify-email/{raw_token}/ returned 500",
            (),
            None,
        )

        self.assertTrue(SensitiveRouteFilter().filter(record))
        rendered = record.getMessage()
        self.assertNotIn(raw_token, rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_logging_filter_redacts_the_domain_generated_staff_invitation_path(self):
        from open_marketplace.web.logging import SensitiveRouteFilter

        raw_token = "I" * 43
        record = logging.LogRecord(
            "django.security.csrf",
            logging.WARNING,
            __file__,
            1,
            f"Forbidden: /access/staff-invitation/{raw_token}/",
            (),
            None,
        )

        self.assertTrue(SensitiveRouteFilter().filter(record))
        self.assertNotIn(raw_token, record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())

    def test_django_parent_logger_uses_only_redacting_handlers(self):
        django_logger = logging.getLogger("django")

        self.assertTrue(django_logger.handlers)
        for handler in django_logger.handlers:
            self.assertIn(
                "SensitiveRouteFilter",
                {type(log_filter).__name__ for log_filter in handler.filters},
            )

    def test_logging_filter_attaches_server_request_id_and_redacts_request_path(self):
        from open_marketplace.web.logging import SensitiveRouteFilter

        raw_token = "R" * 43
        request_id = uuid4()
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            1,
            "Sensitive request failed",
            (),
            None,
        )
        record.request = SimpleNamespace(
            path=f"/identity/reset-password/{raw_token}/",
            request_id=request_id,
        )

        self.assertTrue(SensitiveRouteFilter().filter(record))
        self.assertEqual(record.request_id, str(request_id))
        self.assertNotIn(raw_token, record.safe_path)

    def test_logging_filter_removes_unexpected_exception_details(self):
        from open_marketplace.web.logging import SensitiveRouteFilter

        sentinel = "SENTINEL_SECRET_EXCEPTION_DETAIL"
        try:
            raise RuntimeError(sentinel)
        except RuntimeError:
            exception_info = sys.exc_info()
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            1,
            "Unexpected failure: %s",
            (sentinel,),
            exception_info,
        )
        record.request = SimpleNamespace(path="/register/", request_id=uuid4())

        self.assertTrue(SensitiveRouteFilter().filter(record))
        rendered = logging.Formatter("%(message)s").format(record)
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("Traceback", rendered)
        self.assertIsNone(record.exc_info)

    def test_unexpected_error_page_contains_only_neutral_request_id(self):
        client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        form = client.get(reverse("register"))
        csrf = client.cookies["csrftoken"].value
        sentinel = "SENTINEL_UNEXPECTED_EXCEPTION_DETAIL"

        with patch(
            "open_marketplace.web.identity_views.identity_public.register_account",
            side_effect=RuntimeError(sentinel),
        ):
            response = client.post(
                reverse("register"),
                {
                    "csrfmiddlewaretoken": csrf,
                    "email": "person@example.com",
                    "password": self.password,
                },
            )

        self.assertEqual(form.status_code, 200)
        self.assertEqual(response.status_code, 500)
        request_id = UUID(response["X-Request-ID"])
        self.assertContains(response, str(request_id), status_code=500)
        self.assertNotContains(response, sentinel, status_code=500)
        self.assertNotContains(response, self.password, status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)

    def test_cookie_security_defaults_and_secure_mode(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")

        environment = os.environ.copy()
        environment["DJANGO_SECURE_COOKIES"] = "true"
        code = (
            "import json; from django.conf import settings; "
            "print(json.dumps({"
            "'session': settings.SESSION_COOKIE_SECURE, "
            "'csrf': settings.CSRF_COOKIE_SECURE, "
            "'redirect': settings.SECURE_SSL_REDIRECT, "
            "'hsts': settings.SECURE_HSTS_SECONDS}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertTrue(values["session"])
        self.assertTrue(values["csrf"])
        self.assertTrue(values["redirect"])
        self.assertGreater(values["hsts"], 0)
