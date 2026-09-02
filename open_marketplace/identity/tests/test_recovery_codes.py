from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

import pyotp
from django.test import TestCase

from open_marketplace.common.crypto import hash_one_time_token
from open_marketplace.common.errors import AuthenticationDenied
from open_marketplace.identity.models import AccountSession
from open_marketplace.identity.tests.test_totp import TotpTestCase


class RecoveryCodeTests(TotpTestCase, TestCase):
    def enabled_account(self):
        models = self.models()
        account = self.create_account()
        registry = self.create_registry(account)
        view = self.begin(registry)
        codes = self.enable(registry, view)
        credential = models.TotpCredential.objects.get(account=account)
        return models, account, registry, view, codes, credential

    def test_codes_have_128_random_bits_are_returned_once_and_stored_only_as_hashes(self):
        models, account, _, view, codes, _ = self.enabled_account()

        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        self.assertTrue(all(len(code) == 22 for code in codes))
        self.assertTrue(all(code.replace("-", "A").replace("_", "A").isalnum() for code in codes))
        rows = list(models.RecoveryCode.objects.filter(account=account))
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row.set_id for row in rows}), 1)
        self.assertTrue(all(row.code_digest == hash_one_time_token(code) for row, code in zip(sorted(rows, key=lambda row: row.code_digest), sorted(codes, key=hash_one_time_token))))
        self.assertTrue(all(row.used_at is None and row.revoked_at is None for row in rows))
        serialized = repr(rows)
        self.assertNotIn(view.manual_secret, serialized)
        for code in codes:
            self.assertNotIn(code, serialized)

    def test_recovery_login_consumes_code_once_and_audits_without_secret(self):
        models, account, _, _, codes, _ = self.enabled_account()
        code = codes[0]
        before_sessions = AccountSession.objects.count()
        login_now = self.now + timedelta(seconds=30)

        result = self.authenticate(account, second_factor=code, now=login_now)

        self.assertEqual(result.account_id, account.id)
        self.assertEqual(AccountSession.objects.count(), before_sessions + 1)
        row = models.RecoveryCode.objects.get(code_digest=hash_one_time_token(code))
        self.assertEqual(row.used_at, login_now)
        with self.assertRaises(AuthenticationDenied):
            self.authenticate(
                account,
                second_factor=code,
                now=login_now + timedelta(seconds=30),
            )
        actions = [entry.action for entry in self.audit_entries()]
        self.assertIn("identity.recovery_code_used", actions)
        self.assertNotIn(code, repr(self.audit_entries()))

    def test_replace_revokes_whole_set_and_accepts_totp_or_one_time_recovery(self):
        models, account, registry, view, first_codes, credential = self.enabled_account()
        public = self.public_module()
        first_rows = list(models.RecoveryCode.objects.filter(account=account))
        first_set_id = first_rows[0].set_id
        first_replace_at = self.now + timedelta(seconds=30)

        second_codes = public.replace_recovery_codes(
            password=self.password,
            second_factor=pyotp.TOTP(view.manual_secret).at(first_replace_at),
            context=self.context(registry, now=first_replace_at),
        )

        self.assertEqual(len(second_codes), 10)
        for row in first_rows:
            row.refresh_from_db()
            self.assertEqual(row.revoked_at, first_replace_at)
        second_rows = list(
            models.RecoveryCode.objects.filter(account=account, revoked_at__isnull=True)
        )
        self.assertEqual(len(second_rows), 10)
        self.assertNotEqual(second_rows[0].set_id, first_set_id)

        recovery_factor = second_codes[0]
        second_replace_at = first_replace_at + timedelta(seconds=1)
        third_codes = public.replace_recovery_codes(
            password=self.password,
            second_factor=recovery_factor,
            context=self.context(registry, now=second_replace_at),
        )

        self.assertEqual(len(third_codes), 10)
        used = models.RecoveryCode.objects.get(
            code_digest=hash_one_time_token(recovery_factor)
        )
        self.assertEqual(used.used_at, second_replace_at)
        self.assertIsNone(used.revoked_at)
        self.assertEqual(
            models.RecoveryCode.objects.filter(
                account=account,
                used_at__isnull=True,
                revoked_at__isnull=True,
            ).count(),
            10,
        )
        actions = [entry.action for entry in self.audit_entries()]
        self.assertEqual(actions.count("identity.recovery_codes_replaced"), 2)
        self.assertEqual(actions.count("identity.recovery_code_used"), 1)
        self.assertTrue(first_codes)
        credential.refresh_from_db()
        self.assertEqual(
            credential.last_accepted_counter,
            pyotp.TOTP(view.manual_secret).timecode(first_replace_at),
        )

    def test_disable_optional_totp_preserves_current_and_revokes_other_sessions_and_codes(self):
        models, account, current, view, _, credential = self.enabled_account()
        public = self.public_module()
        other = self.create_registry(account)
        disable_at = self.now + timedelta(seconds=30)

        public.disable_optional_totp(
            password=self.password,
            second_factor=pyotp.TOTP(view.manual_secret).at(disable_at),
            context=self.context(current, now=disable_at),
        )

        credential.refresh_from_db()
        current.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(credential.disabled_at, disable_at)
        self.assertIsNone(current.revoked_at)
        self.assertEqual(current.reauthenticated_at, disable_at)
        self.assertEqual(other.revoked_at, disable_at)
        self.assertEqual(other.revoked_reason, "optional_totp_disabled")
        self.assertFalse(public.get_account_snapshot(account.id).totp_enabled)
        self.assertEqual(
            models.RecoveryCode.objects.filter(
                account=account,
                used_at__isnull=True,
                revoked_at__isnull=True,
            ).count(),
            0,
        )
        messages = [
            message
            for message in self.claim_outbox(now=disable_at)
            if message.message_type == "identity.protected_account_change"
        ]
        self.assertEqual(
            sorted(dict(message.payload)["change"] for message in messages),
            ["totp_disabled", "totp_enabled"],
        )
        actions = [entry.action for entry in self.audit_entries()]
        self.assertIn("identity.totp_disabled", actions)
        self.assertIn("identity.sessions_revoked_for_security_event", actions)

    def test_enable_replace_and_disable_roll_back_on_audit_or_outbox_failure(self):
        models = self.models()
        public = self.public_module()
        account = self.create_account()
        registry = self.create_registry(account)
        original_reauth = registry.reauthenticated_at
        view = self.begin(registry)
        code = pyotp.TOTP(view.manual_secret).at(self.now)

        with patch(
            "open_marketplace.identity.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            self.enable(registry, view, code=code)

        setup = models.TotpSetup.objects.get(pk=view.setup_id)
        registry.refresh_from_db()
        self.assertIsNone(setup.consumed_at)
        self.assertEqual(registry.reauthenticated_at, original_reauth)
        self.assertEqual(models.TotpCredential.objects.count(), 0)
        self.assertEqual(models.RecoveryCode.objects.count(), 0)

        self.enable(registry, view, code=code)
        credential = models.TotpCredential.objects.get()
        rows_before = list(
            models.RecoveryCode.objects.values_list(
                "id", "set_id", "used_at", "revoked_at"
            )
        )
        replace_at = self.now + timedelta(seconds=30)
        with patch(
            "open_marketplace.identity.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            public.replace_recovery_codes(
                password=self.password,
                second_factor=pyotp.TOTP(view.manual_secret).at(replace_at),
                context=self.context(registry, now=replace_at),
            )
        self.assertEqual(
            list(
                models.RecoveryCode.objects.values_list(
                    "id", "set_id", "used_at", "revoked_at"
                )
            ),
            rows_before,
        )

        other = self.create_registry(account)
        disable_at = replace_at
        with patch(
            "open_marketplace.identity.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            public.disable_optional_totp(
                password=self.password,
                second_factor=pyotp.TOTP(view.manual_secret).at(disable_at),
                context=self.context(registry, now=disable_at),
            )
        credential.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNone(credential.disabled_at)
        self.assertIsNone(other.revoked_at)
