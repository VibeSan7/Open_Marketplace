import re
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.common.errors import InputRejected
from open_marketplace.identity.public import NeutralAccepted
from open_marketplace.identity.tests.web_fixtures import Account, AccountSession
from open_marketplace.outbox.tests.web_fixtures import OutboxMessage


class IdentityPageTests(TestCase):
    password = "Correct Horse Battery Staple 42!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def _active_account(self, email="owner@example.com"):
        account = Account(
            email=email,
            kind=Account.Kind.ORDINARY,
            state=Account.State.ACTIVE,
            email_verified_at=timezone.now(),
        )
        account.set_password(self.password)
        account.save()
        return account

    def _csrf_post(self, name, data=None, **extra):
        url = reverse(name)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        token = self.client.cookies["csrftoken"].value
        payload = {"csrfmiddlewaretoken": token, **(data or {})}
        return self.client.post(url, payload, **extra)

    def _authenticated_client(self, account=None):
        account = account or self._active_account()
        session = self.client.session
        session["preexisting"] = "rotated-session"
        session.save()
        registry = AccountSession.objects.create(
            account=account,
            django_session_key=session.session_key,
            created_at=timezone.now(),
            last_activity_at=timezone.now(),
            absolute_expires_at=timezone.now() + timedelta(days=30),
            reauthenticated_at=timezone.now(),
            device_label="Test browser",
        )
        session["account_id"] = str(account.id)
        session["session_id"] = str(registry.id)
        session.save()
        return account, registry

    def test_public_identity_get_routes_render_html_without_mutation(self):
        before = OutboxMessage.objects.count()

        for name in ("register", "login", "password-reset-request"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Type"].startswith("text/html"))
                UUID(response["X-Request-ID"])

        self.assertEqual(OutboxMessage.objects.count(), before)

    def test_registration_post_requires_csrf(self):
        response = self.client.post(
            reverse("register"),
            {"email": "new@example.com", "password": self.password},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Account.objects.filter(email="new@example.com").exists())

    def test_registration_uses_server_context_and_does_not_echo_secrets(self):
        supplied_request_id = str(uuid4())
        with patch(
            "open_marketplace.web.identity_views.identity_public.register_account",
            return_value=NeutralAccepted(accepted=True),
        ) as operation:
            response = self._csrf_post(
                "register",
                {"email": "new@example.com", "password": self.password},
                REMOTE_ADDR="198.51.100.17",
                HTTP_X_FORWARDED_FOR="203.0.113.99",
                HTTP_X_REQUEST_ID=supplied_request_id,
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.password)
        self.assertNotContains(response, "new@example.com")
        request_id = UUID(response["X-Request-ID"])
        self.assertNotEqual(str(request_id), supplied_request_id)
        context = operation.call_args.kwargs["context"]
        self.assertEqual(context.request_id, request_id)
        self.assertEqual(context.source, "html")
        self.assertEqual(context.source_address, "198.51.100.17")
        self.assertIsNone(context.actor_account_id)
        self.assertIsNone(context.session_id)

    def test_expected_registration_error_is_neutral_and_bounded(self):
        sentinel = "SENTINEL_INTERNAL_VALIDATION_DETAIL"
        with patch(
            "open_marketplace.web.identity_views.identity_public.register_account",
            side_effect=InputRejected(sentinel),
        ):
            response = self._csrf_post(
                "register",
                {"email": "new@example.com", "password": self.password},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, sentinel)
        self.assertNotContains(response, self.password)
        self.assertLess(len(response.content), 16_384)

    def test_login_post_requires_csrf(self):
        account = self._active_account()

        response = self.client.post(
            reverse("login"),
            {"email": account.email, "password": self.password},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AccountSession.objects.count(), 0)

    def test_login_rotates_and_binds_a_server_side_session(self):
        account = self._active_account()
        session = self.client.session
        session["preexisting"] = "anonymous"
        session.save()
        old_key = session.session_key

        response = self._csrf_post(
            "login",
            {
                "email": account.email,
                "password": self.password,
                "second_factor": "",
                "next": reverse("sessions"),
            },
            HTTP_USER_AGENT="  Browser\u0000   on   desktop  ",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("sessions"))
        session = self.client.session
        self.assertNotEqual(session.session_key, old_key)
        self.assertEqual(session["account_id"], str(account.id))
        registry = AccountSession.objects.get(pk=UUID(session["session_id"]))
        self.assertEqual(registry.account_id, account.id)
        self.assertEqual(registry.django_session_key, session.session_key)
        self.assertEqual(registry.device_label, "Browser on desktop")
        self.assertNotIn(session.session_key, response.content.decode())
        self.assertNotIn(session.session_key, str(response.headers))

    def test_login_rejects_external_next_target(self):
        account = self._active_account()

        response = self._csrf_post(
            "login",
            {
                "email": account.email,
                "password": self.password,
                "second_factor": "",
                "next": "//evil.example/steal",
            },
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("security"))

    def test_failed_login_is_neutral_and_flushes_anonymous_session(self):
        account = self._active_account()
        session = self.client.session
        session["preexisting"] = "anonymous"
        session.save()
        old_key = session.session_key

        response = self._csrf_post(
            "login",
            {
                "email": account.email,
                "password": "wrong-password",
                "second_factor": "",
                "next": reverse("sessions"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, account.email)
        self.assertNotContains(response, "wrong-password")
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)
        self.assertEqual(AccountSession.objects.count(), 0)

    def test_logout_is_post_only_and_csrf_protected(self):
        _, registry = self._authenticated_client()

        get_response = self.client.get(reverse("logout"))
        post_response = self.client.post(reverse("logout"))

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(post_response.status_code, 403)
        registry.refresh_from_db()
        self.assertIsNone(registry.revoked_at)

    def test_logout_revokes_registry_and_flushes_browser_session(self):
        _, registry = self._authenticated_client()

        security = self.client.get(reverse("security"))
        self.assertEqual(security.status_code, 200)
        csrf = self.client.cookies["csrftoken"].value
        response = self.client.post(
            reverse("logout"),
            {"csrfmiddlewaretoken": csrf},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("login"))
        registry.refresh_from_db()
        self.assertIsNotNone(registry.revoked_at)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)

    def test_password_reset_request_is_csrf_protected_and_neutral(self):
        account = self._active_account()
        missing_csrf = self.client.post(
            reverse("password-reset-request"),
            {"email": account.email},
        )
        self.assertEqual(missing_csrf.status_code, 403)

        known = self._csrf_post("password-reset-request", {"email": account.email})
        unknown = self._csrf_post(
            "password-reset-request",
            {"email": "unknown@example.com"},
        )

        self.assertEqual(known.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        csrf_input = rb'name="csrfmiddlewaretoken" value="[^"]+"'
        self.assertEqual(
            re.sub(csrf_input, b'name="csrfmiddlewaretoken" value="[CSRF]"', known.content),
            re.sub(csrf_input, b'name="csrfmiddlewaretoken" value="[CSRF]"', unknown.content),
        )
        self.assertNotContains(known, account.email)
        self.assertNotContains(unknown, "unknown@example.com")

    def test_password_change_requires_registry_authentication_and_csrf(self):
        unauthenticated = self.client.get(reverse("password-change"))
        self.assertEqual(unauthenticated.status_code, 303)
        self.assertTrue(unauthenticated["Location"].startswith(reverse("login")))

        account, registry = self._authenticated_client()
        missing_csrf = self.client.post(
            reverse("password-change"),
            {"current_password": self.password, "new_password": "Another Strong Password 73!"},
        )
        self.assertEqual(missing_csrf.status_code, 403)
        registry.refresh_from_db()
        self.assertIsNone(registry.revoked_at)
        account.refresh_from_db()
        self.assertTrue(account.check_password(self.password))

    def test_password_change_revokes_and_clears_the_current_session(self):
        account, registry = self._authenticated_client()
        new_password = "Another Strong Password 73!"

        response = self._csrf_post(
            "password-change",
            {"current_password": self.password, "new_password": new_password},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("login"))
        account.refresh_from_db()
        registry.refresh_from_db()
        self.assertTrue(account.check_password(new_password))
        self.assertIsNotNone(registry.revoked_at)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)
