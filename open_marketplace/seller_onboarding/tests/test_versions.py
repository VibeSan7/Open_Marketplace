from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

from django.apps import apps
from django.test import TestCase

from open_marketplace.common.types import OperationContext


class SellerApplicationVersionTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def setUp(self):
        self.public = import_module("open_marketplace.seller_onboarding.public")
        self.models = import_module("open_marketplace.seller_onboarding.models")
        self.Account = apps.get_model("identity", "Account")
        self.account = self.Account.objects.create_user(
            email=f"owner-{uuid4()}@example.com",
            password="correct horse battery staple",
            state="active",
            email_verified_at=self.now,
        )
        self.context = OperationContext(
            actor_account_id=self.account.id,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="192.0.2.11",
            now=self.now,
        )

    def draft(self, name="Shop"):
        return self.public.SellerDraftData(
            business_form="legal_entity",
            display_name=name,
            official_name=f"{name} LLC",
            registration_identifier=f"ID-{name}",
            contact_email="owner@example.com",
            test_data_attested=True,
        )

    def test_version_is_immutable_through_instance_and_queryset_mutations(self):
        application_id = self.public.create_seller_application(context=self.context)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(),
            context=self.context,
        )
        version_id = self.public.submit_seller_application(
            application_id=application_id,
            context=self.context,
        )
        version = self.models.SellerApplicationVersion.objects.get(pk=version_id)
        version.display_name = "changed"
        with self.assertRaises(RuntimeError):
            version.save()
        with self.assertRaises(RuntimeError):
            version.delete()
        with self.assertRaises(RuntimeError):
            self.models.SellerApplicationVersion.objects.filter(pk=version_id).update(display_name="changed")
        with self.assertRaises(RuntimeError):
            self.models.SellerApplicationVersion.objects.bulk_update(
                [version],
                ["display_name"],
            )
        with self.assertRaises(RuntimeError):
            self.models.SellerApplicationVersion.objects.update_or_create(
                id=version_id,
                defaults={"display_name": "changed"},
            )
        with self.assertRaises(RuntimeError):
            self.models.SellerApplicationVersion.objects.filter(pk=version_id).delete()
        version.refresh_from_db()
        self.assertEqual(version.display_name, "Shop")

    def test_submission_versions_are_monotonic_and_unique(self):
        application_id = self.public.create_seller_application(context=self.context)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft("First"),
            context=self.context,
        )
        first_id = self.public.submit_seller_application(
            application_id=application_id,
            context=self.context,
        )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        application.state = "changes_requested"
        application.save(update_fields={"state"})
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft("Second"),
            context=self.context,
        )
        second_id = self.public.submit_seller_application(
            application_id=application_id,
            context=self.context,
        )

        versions = self.models.SellerApplicationVersion.objects.filter(
            application_id=application_id
        ).order_by("version_number")
        self.assertEqual(tuple(version.version_number for version in versions), (1, 2))
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(
            self.models.SellerApplication.objects.get(pk=application_id).current_version,
            2,
        )
