from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

from django.apps import apps
from django.db import close_old_connections
from django.test import TransactionTestCase

from open_marketplace.common.errors import ConcurrentConflict, InvalidState
from open_marketplace.common.types import OperationContext


class SellerApplicationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.public = import_module("open_marketplace.seller_onboarding.public")
        self.models = import_module("open_marketplace.seller_onboarding.models")
        self.Account = apps.get_model("identity", "Account")
        self.now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        self.account = self.Account.objects.create_user(
            email=f"owner-{uuid4()}@example.com",
            password="correct horse battery staple",
            state="active",
            email_verified_at=self.now,
        )

    def context(self):
        return OperationContext(
            actor_account_id=self.account.id,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="192.0.2.12",
            now=self.now,
        )

    def run_parallel(self, operation):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        barrier = Barrier(2)

        def invoke(_):
            close_old_connections()
            try:
                barrier.wait()
                return ("ok", operation())
            except Exception as error:
                return ("error", type(error))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return tuple(executor.map(invoke, range(2)))

    def draft(self, name):
        return self.public.SellerDraftData(
            business_form="sole_proprietor",
            display_name=name,
            official_name=f"{name} business",
            registration_identifier=f"ID-{name}",
            contact_email="owner@example.com",
            test_data_attested=True,
        )

    def test_simultaneous_create_leaves_one_unfinished_application(self):
        results = self.run_parallel(
            lambda: self.public.create_seller_application(context=self.context())
        )
        self.assertEqual(
            self.models.SellerApplication.objects.filter(
                applicant_id=self.account.id,
                state__in=("draft", "submitted", "under_review", "changes_requested"),
            ).count(),
            1,
        )
        self.assertEqual(sum(result[0] == "ok" for result in results), 1)
        self.assertEqual(
            [result[1] for result in results if result[0] == "error"],
            [ConcurrentConflict],
        )

    def test_simultaneous_updates_leave_one_complete_consistent_snapshot(self):
        application_id = self.public.create_seller_application(context=self.context())
        results = self.run_parallel(
            lambda: self.public.update_seller_application_draft(
                application_id=application_id,
                data=self.draft(f"shop-{uuid4().hex}"),
                context=self.context(),
            )
        )
        self.assertEqual(sum(result[0] == "ok" for result in results), 2)
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "draft")
        self.assertTrue(application.display_name)
        self.assertEqual(application.official_name, f"{application.display_name} business")
        self.assertEqual(
            application.registration_identifier,
            f"ID-{application.display_name}",
        )
        self.assertEqual(application.contact_email, "owner@example.com")

    def test_simultaneous_submits_create_one_version_and_one_event(self):
        context = self.context()
        application_id = self.public.create_seller_application(context=context)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft("shop"),
            context=context,
        )
        results = self.run_parallel(
            lambda: self.public.submit_seller_application(
                application_id=application_id,
                context=self.context(),
            )
        )
        self.assertEqual(
            self.models.SellerApplicationVersion.objects.filter(
                application_id=application_id
            ).count(),
            1,
        )
        self.assertEqual(
            apps.get_model("outbox", "OutboxMessage").objects.filter(
                message_type="seller_onboarding.application_submitted"
            ).count(),
            1,
        )
        self.assertEqual(sum(result[0] == "ok" for result in results), 1)
        self.assertEqual(
            [result[1] for result in results if result[0] == "error"],
            [InvalidState],
        )
