import json
import re
import time
import urllib.request
from importlib import import_module
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import override_settings

from open_marketplace.outbox.tests.test_outbox import OutboxTestCase


EXPECTED_REGISTRY = {
    ("identity.email_verification", 1),
    ("identity.password_reset", 1),
    ("identity.mandatory_totp_recovery", 1),
    ("access.staff_invitation", 1),
    ("seller_onboarding.application_submitted", 1),
    ("seller_onboarding.application_decision", 1),
    ("identity.protected_account_change", 1),
    ("seller_onboarding.admission_change", 1),
}

EXPECTED_SUBJECTS = {
    "identity.email_verification": "Confirm your Open Marketplace email",
    "identity.password_reset": "Reset your Open Marketplace password",
    "identity.mandatory_totp_recovery": "Recover your Open Marketplace TOTP",
    "access.staff_invitation": "Open Marketplace staff invitation",
    "seller_onboarding.application_decision": "Open Marketplace seller application decision",
    "identity.protected_account_change": "Open Marketplace protected account change",
}


class MailDeliveryTests(OutboxTestCase):
    def test_handler_registry_is_closed_to_the_exact_eight_type_version_pairs(self):
        delivery = import_module("open_marketplace.outbox.mail_delivery")

        self.assertEqual(set(delivery.HANDLER_REGISTRY), EXPECTED_REGISTRY)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_each_smtp_type_sends_one_deterministic_message_with_only_its_allowed_link(self):
        smtp_cases = {
            message_type: case
            for case in self.message_cases()[:6]
            for message_type in (case[0],)
        }

        for message_type, (registered_type, payload, delivery) in smtp_cases.items():
            with self.subTest(message_type=message_type):
                self.assertEqual(message_type, registered_type)
                subjects = []
                for _ in range(2):
                    mail.outbox = []
                    message_id = self.enqueue(
                        message_type=message_type,
                        payload=payload,
                        delivery=delivery,
                    )

                    call_command("run_outbox_worker", "--once")

                    self.assertEqual(len(mail.outbox), 1)
                    sent = mail.outbox[0]
                    subjects.append(sent.subject)
                    self.assertEqual(sent.to, [delivery["recipient"]])
                    self.assertEqual(sent.subject, EXPECTED_SUBJECTS[message_type])
                    self.assertEqual(
                        sent.extra_headers["X-Open-Marketplace-Message-Type"],
                        message_type,
                    )
                    self.assertEqual(
                        self.model_class().objects.get(pk=message_id).state,
                        "succeeded",
                    )
                    if "absolute_token_url" in delivery:
                        self.assertIn(delivery["absolute_token_url"], sent.body)
                    else:
                        self.assertNotIn("https://example.com/", sent.body)
                self.assertEqual(subjects[0], subjects[1])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_local_events_validate_and_complete_without_email_or_subject_module_calls(self):
        local_cases = self.message_cases()[6:]

        with patch("django.core.mail.message.EmailMessage.send") as send:
            for message_type, payload, delivery in local_cases:
                with self.subTest(message_type=message_type):
                    message_id = self.enqueue(
                        message_type=message_type,
                        payload=payload,
                        delivery=delivery,
                    )
                    call_command("run_outbox_worker", "--once")

                    self.assertEqual(
                        self.model_class().objects.get(pk=message_id).state,
                        "succeeded",
                    )

        send.assert_not_called()
        self.assertEqual(getattr(mail, "outbox", []), [])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_smtp_failure_does_not_log_delivery_or_exception_secrets(self):
        recipient = "sentinel-recipient@example.com"
        token_url = "https://example.com/secret/SENTINEL_TOKEN_URL"
        password = "SENTINEL_PASSWORD"
        totp_secret = "SENTINEL_TOTP_SECRET"
        stdout = StringIO()
        stderr = StringIO()
        message_id = self.enqueue(
            delivery={"recipient": recipient, "absolute_token_url": token_url}
        )
        ciphertext = bytes(
            self.model_class().objects.get(pk=message_id).encrypted_delivery
        ).decode("ascii")
        secrets = (
            recipient,
            token_url,
            password,
            totp_secret,
            settings.OUTBOX_ENCRYPTION_KEY,
            settings.LINK_EXCHANGE_ENCRYPTION_KEY,
            ciphertext,
        )
        exception_text = " ".join(secrets)

        with self.assertLogs("open_marketplace", level="INFO") as logs:
            with patch(
                "django.core.mail.message.EmailMessage.send",
                side_effect=RuntimeError(exception_text),
            ):
                call_command(
                    "run_outbox_worker",
                    "--once",
                    stdout=stdout,
                    stderr=stderr,
                )

        output = "\n".join(logs.output) + stdout.getvalue() + stderr.getvalue()
        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "retry_wait")
        self.assertIsNotNone(message.next_attempt_at)
        self.assertRegex(message.last_safe_error, r"^[a-z0-9_.-]{1,128}$")
        for secret in (*secrets, exception_text):
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, message.last_safe_error)
        self.assertNotRegex(output, re.compile(r"SENTINEL|recipient=|url="))

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="mailpit",
        EMAIL_PORT=1025,
    )
    def test_real_mailpit_delivery_has_recipient_subject_and_type_without_token_link(self):
        api_url = "http://mailpit:8025/api/v1/messages"
        urllib.request.urlopen(
            urllib.request.Request(api_url, method="DELETE"),
            timeout=5,
        ).close()
        recipient = f"task18-{uuid4().hex}@example.test"
        message_id = self.enqueue(
            message_type="seller_onboarding.application_decision",
            payload={"application_id": str(uuid4()), "decision": "approve"},
            delivery={"recipient": recipient},
        )

        try:
            call_command("run_outbox_worker", "--once")
            listing = None
            for _ in range(20):
                with urllib.request.urlopen(api_url, timeout=5) as response:
                    listing = json.loads(response.read().decode("utf-8"))
                if listing["total"] == 1:
                    break
                time.sleep(0.05)

            self.assertEqual(listing["total"], 1)
            received = listing["messages"][0]
            self.assertEqual(received["To"][0]["Address"], recipient)
            self.assertEqual(
                received["Subject"],
                EXPECTED_SUBJECTS["seller_onboarding.application_decision"],
            )
            with urllib.request.urlopen(
                f"{api_url[:-1]}/{received['ID']}/raw",
                timeout=5,
            ) as response:
                raw_message = response.read().decode("utf-8")
            self.assertIn(
                "X-Open-Marketplace-Message-Type: seller_onboarding.application_decision",
                raw_message,
            )
            self.assertNotIn("http://", raw_message)
            self.assertNotIn("https://", raw_message)
            self.assertNotIn("token", raw_message.casefold())
            self.assertEqual(self.model_class().objects.get(pk=message_id).state, "succeeded")
        finally:
            urllib.request.urlopen(
                urllib.request.Request(api_url, method="DELETE"),
                timeout=5,
            ).close()
