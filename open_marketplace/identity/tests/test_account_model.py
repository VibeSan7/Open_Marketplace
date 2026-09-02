from dataclasses import FrozenInstanceError
from importlib import import_module
from importlib.util import find_spec
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from open_marketplace.identity import domain, models as identity_models


class AccountModelTests(TestCase):
    password = "correct horse battery staple"

    def account_model(self):
        self.assertTrue(hasattr(identity_models, "Account"))
        return identity_models.Account

    def test_email_is_trimmed_and_casefolded(self):
        Account = self.account_model()

        account = Account.objects.create_user(
            email="  User@Example.COM ",
            password=self.password,
        )

        self.assertEqual(account.email, "user@example.com")

    def test_invalid_email_is_rejected_by_django_validation(self):
        self.assertTrue(hasattr(domain, "canonicalize_email"))

        with self.assertRaises(ValidationError):
            domain.canonicalize_email("  not an email  ")

    def test_email_is_unique_without_regard_to_case(self):
        Account = self.account_model()
        Account.objects.create_user(
            email="user@example.com",
            password=self.password,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.create_user(
                email="USER@EXAMPLE.COM",
                password=self.password,
            )

    def test_password_is_hashed(self):
        Account = self.account_model()

        account = Account.objects.create_user(
            email="user@example.com",
            password=self.password,
        )

        self.assertNotEqual(account.password, self.password)
        self.assertTrue(account.check_password(self.password))

    def test_new_account_waits_for_email_verification(self):
        Account = self.account_model()

        account = Account.objects.create_user(
            email="user@example.com",
            password=self.password,
        )

        self.assertEqual(
            account.state,
            Account.State.PENDING_EMAIL_VERIFICATION,
        )
        self.assertIsNone(account.email_verified_at)
        self.assertFalse(account.is_active)

    def test_account_kind_is_immutable(self):
        Account = self.account_model()
        account = Account.objects.create_user(
            email="user@example.com",
            password=self.password,
        )
        account.kind = Account.Kind.SERVICE

        with self.assertRaises(ValidationError):
            account.save(update_fields={"kind"})

        account.refresh_from_db()
        self.assertEqual(account.kind, Account.Kind.ORDINARY)

    def test_manager_creates_separate_account_kinds(self):
        Account = self.account_model()

        ordinary = Account.objects.create_user(
            email="buyer@example.com",
            password=self.password,
        )
        service = Account.objects.create_service_account(
            email="reviewer@example.com",
            password=self.password,
        )

        self.assertEqual(ordinary.kind, Account.Kind.ORDINARY)
        self.assertEqual(service.kind, Account.Kind.SERVICE)

    def test_active_and_staff_flags_derive_from_state_and_kind(self):
        Account = self.account_model()
        ordinary = Account.objects.create_user(
            email="buyer@example.com",
            password=self.password,
        )
        service = Account.objects.create_service_account(
            email="reviewer@example.com",
            password=self.password,
        )

        ordinary.state = Account.State.ACTIVE
        ordinary.save(update_fields={"state", "updated_at"})
        service.state = Account.State.ACTIVE
        service.save(update_fields={"state", "updated_at"})

        self.assertTrue(ordinary.is_active)
        self.assertFalse(ordinary.is_staff)
        self.assertTrue(service.is_active)
        self.assertTrue(service.is_staff)

    def test_account_starts_with_uuid_timestamps_and_version_one(self):
        Account = self.account_model()

        account = Account.objects.create_user(
            email="user@example.com",
            password=self.password,
        )

        self.assertIsInstance(account.id, UUID)
        self.assertIsNotNone(account.created_at)
        self.assertIsNotNone(account.updated_at)
        self.assertEqual(account.version, 1)

    def test_default_superuser_creation_is_rejected(self):
        Account = self.account_model()

        with self.assertRaisesMessage(RuntimeError, "bootstrap_security_admin"):
            Account.objects.create_superuser(
                email="admin@example.com",
                password=self.password,
            )

    def test_custom_account_is_configured_as_the_django_user_model(self):
        Account = self.account_model()

        self.assertEqual(settings.AUTH_USER_MODEL, "identity.Account")
        self.assertIs(get_user_model(), Account)

    def test_public_snapshot_is_immutable_and_not_an_orm_model(self):
        Account = self.account_model()
        module_name = "open_marketplace.identity.public"
        self.assertIsNotNone(find_spec(module_name))
        public = import_module(module_name)
        self.assertTrue(hasattr(public, "get_account_snapshot"))
        account = Account.objects.create_user(
            email="user@example.com",
            password=self.password,
        )

        snapshot = public.get_account_snapshot(account.id)

        self.assertEqual(snapshot.id, account.id)
        self.assertEqual(snapshot.email, "user@example.com")
        self.assertEqual(snapshot.kind, Account.Kind.ORDINARY)
        self.assertEqual(
            snapshot.state,
            Account.State.PENDING_EMAIL_VERIFICATION,
        )
        self.assertIsNone(snapshot.email_verified_at)
        self.assertFalse(snapshot.totp_enabled)
        self.assertNotIsInstance(snapshot, Account)
        with self.assertRaises(FrozenInstanceError):
            snapshot.email = "changed@example.com"
