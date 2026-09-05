from datetime import timedelta
from uuid import UUID, uuid4

from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.identity.tests.web_fixtures import Account, AccountSession


class SessionPageTests(TestCase):
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
        self.current = self._bind_client(self.account)

    def _bind_client(self, account):
        session = self.client.session
        session["seed"] = "authenticated"
        session.save()
        now = timezone.now()
        registry = AccountSession.objects.create(
            account=account,
            django_session_key=session.session_key,
            created_at=now,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(days=30),
            reauthenticated_at=now,
            device_label="Current browser",
        )
        session["account_id"] = str(account.id)
        session["session_id"] = str(registry.id)
        session.save()
        return registry

    def _other_session(self, *, label="Other browser"):
        django_session = SessionStore()
        django_session["seed"] = "other"
        django_session.save()
        now = timezone.now()
        return AccountSession.objects.create(
            account=self.account,
            django_session_key=django_session.session_key,
            created_at=now,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(days=30),
            reauthenticated_at=now,
            device_label=label,
        )

    def test_sessions_page_requires_registry_authentication(self):
        anonymous = Client(enforce_csrf_checks=True)

        response = anonymous.get(reverse("sessions"))

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response["Location"].startswith(reverse("login")))

    def test_sessions_page_lists_only_live_own_sessions_and_escapes_labels(self):
        hostile_label = '<script>alert("session")</script>'
        other = self._other_session(label=hostile_label)

        response = self.client.get(reverse("sessions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current browser")
        self.assertContains(
            response,
            "&lt;script&gt;alert(&quot;session&quot;)&lt;/script&gt;",
            html=False,
        )
        self.assertNotContains(response, hostile_label)
        self.assertNotContains(response, self.current.django_session_key)
        self.assertNotContains(response, other.django_session_key)

    def test_session_revoke_is_post_only_and_csrf_protected(self):
        other = self._other_session()
        url = reverse("session-revoke", kwargs={"session_id": other.id})

        get_response = self.client.get(url)
        post_response = self.client.post(url)

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(post_response.status_code, 403)
        other.refresh_from_db()
        self.assertIsNone(other.revoked_at)

    def test_revoke_other_session_preserves_current_browser_session(self):
        other = self._other_session()
        sessions_page = self.client.get(reverse("sessions"))
        token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            reverse("session-revoke", kwargs={"session_id": other.id}),
            {"csrfmiddlewaretoken": token},
        )

        self.assertEqual(sessions_page.status_code, 200)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("sessions"))
        other.refresh_from_db()
        self.current.refresh_from_db()
        self.assertIsNotNone(other.revoked_at)
        self.assertIsNone(self.current.revoked_at)
        self.assertEqual(UUID(self.client.session["session_id"]), self.current.id)

    def test_revoke_current_session_flushes_browser_session(self):
        self.client.get(reverse("sessions"))
        token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            reverse("session-revoke", kwargs={"session_id": self.current.id}),
            {"csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("login"))
        self.current.refresh_from_db()
        self.assertIsNotNone(self.current.revoked_at)
        self.assertNotIn("account_id", self.client.session)
        self.assertNotIn("session_id", self.client.session)

    def test_revoke_others_requires_csrf_and_revokes_every_other_session(self):
        first = self._other_session(label="First")
        second = self._other_session(label="Second")
        missing = self.client.post(reverse("sessions-revoke-others"))
        self.assertEqual(missing.status_code, 403)

        self.client.get(reverse("sessions"))
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            reverse("sessions-revoke-others"),
            {"csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], reverse("sessions"))
        first.refresh_from_db()
        second.refresh_from_db()
        self.current.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertIsNotNone(second.revoked_at)
        self.assertIsNone(self.current.revoked_at)

    def test_foreign_or_unknown_session_revoke_is_neutral(self):
        self.client.get(reverse("sessions"))
        token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            reverse("session-revoke", kwargs={"session_id": uuid4()}),
            {"csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "does not exist")
        self.assertNotContains(response, "foreign")
