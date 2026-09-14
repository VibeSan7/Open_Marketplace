from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.common.types import OperationContext
from open_marketplace.identity.tests.web_fixtures import Account, AccountSession
from open_marketplace.seller_onboarding.tests.web_fixtures import (
    SellerApplication,
    SellerApplicationVersion,
    SellerProfile,
)


class SellerPageTests(TestCase):
    password = "Correct Horse Battery Staple 42!"
    draft = {
        "business_form": "sole_proprietor",
        "display_name": "Test shop",
        "official_name": "Test business",
        "registration_identifier": "TEST-123",
        "contact_email": "owner@example.com",
        "test_data_attested": "on",
    }

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        from open_marketplace.seller_onboarding import public

        self.public = public

    def _account(self, *, kind=Account.Kind.ORDINARY, state=Account.State.ACTIVE, verified=True):
        create = (
            Account.objects.create_user
            if kind == Account.Kind.ORDINARY
            else Account.objects.create_service_account
        )
        return create(
            email=f"owner-{uuid4().hex}@example.com",
            password=self.password,
            state=state,
            email_verified_at=timezone.now() if verified else None,
        )

    def _bind(self, client, account):
        session = client.session
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
            device_label="Test browser",
        )
        session["account_id"] = str(account.id)
        session["session_id"] = str(registry.id)
        session.save()
        return registry

    def _context(self, account, registry=None, *, source="html"):
        return OperationContext(
            actor_account_id=account.id,
            session_id=registry.id if registry else None,
            request_id=uuid4(),
            source=source,
            source_address="192.0.2.10",
            now=timezone.now(),
        )

    def _csrf_token(self, client, name="seller-application-create", **kwargs):
        response = client.get(reverse(name, kwargs=kwargs))
        self.assertEqual(response.status_code, 200)
        return client.cookies["csrftoken"].value

    def _post(self, client, name, data=None, *, kwargs=None, token=None, **extra):
        kwargs = kwargs or {}
        token = token or self._csrf_token(client)
        return client.post(
            reverse(name, kwargs=kwargs),
            {"csrfmiddlewaretoken": token, **(data or {})},
            **extra,
        )

    def _create_application(self, client=None):
        client = client or self.client
        response = self._post(client, "seller-application-create")
        self.assertEqual(response.status_code, 303)
        return SellerApplication.objects.latest("created_at").id

    def _submit_application(self, client=None, *, data=None):
        client = client or self.client
        application_id = self._create_application(client)
        response = self._post(
            client,
            "seller-application-edit",
            data=data or self.draft,
            kwargs={"application_id": application_id},
        )
        self.assertEqual(response.status_code, 303)
        response = self._post(
            client,
            "seller-application-submit",
            kwargs={"application_id": application_id},
        )
        self.assertEqual(response.status_code, 303)
        return application_id

    def _assert_secure(self, response):
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_named_routes_exist_and_anonymous_access_redirects_to_login(self):
        application_id = uuid4()
        urls = {
            "seller-application-create": {},
            "seller-application-edit": {"application_id": application_id},
            "seller-application-submit": {"application_id": application_id},
            "seller-application-withdraw": {"application_id": application_id},
            "seller-applications": {},
            "seller-application-detail": {"application_id": application_id},
            "seller-status": {},
        }

        for name, kwargs in urls.items():
            with self.subTest(name=name):
                url = reverse(name, kwargs=kwargs)
                response = self.client.get(url)
                if name in {
                    "seller-application-submit",
                    "seller-application-withdraw",
                }:
                    self.assertEqual(response.status_code, 405)
                else:
                    self.assertEqual(response.status_code, 303)
                    self.assertTrue(response["Location"].startswith(reverse("login")))
                self._assert_secure(response)

    def test_only_active_verified_ordinary_registry_sessions_can_mutate(self):
        cases = (
            (
                {"kind": Account.Kind.ORDINARY, "state": Account.State.PENDING_EMAIL_VERIFICATION},
                303,
            ),
            ({"kind": Account.Kind.ORDINARY, "verified": False}, 200),
            ({"kind": Account.Kind.SERVICE}, 200),
        )

        for options, expected_status in cases:
            with self.subTest(options=options):
                client = Client(enforce_csrf_checks=True)
                account = self._account(**options)
                self._bind(client, account)
                before = SellerApplication.objects.filter(applicant_id=account.id).count()
                token = self._csrf_token(client, name="register")

                response = self._post(
                    client,
                    "seller-application-create",
                    token=token,
                )

                self.assertEqual(response.status_code, expected_status)
                self._assert_secure(response)
                self.assertEqual(
                    SellerApplication.objects.filter(applicant_id=account.id).count(),
                    before,
                )

    def test_get_is_read_only_and_all_mutations_are_post_only_and_csrf_protected(self):
        account = self._account()
        registry = self._bind(self.client, account)
        before = SellerApplication.objects.count()

        create_get = self.client.get(reverse("seller-application-create"))
        self.assertEqual(create_get.status_code, 200)
        self.assertEqual(SellerApplication.objects.count(), before)

        missing_csrf = self.client.post(reverse("seller-application-create"))
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(SellerApplication.objects.count(), before)

        application_id = self._create_application()
        application = SellerApplication.objects.get(pk=application_id)

        for name in ("seller-application-submit", "seller-application-withdraw"):
            with self.subTest(name=name):
                url = reverse(name, kwargs={"application_id": application_id})
                response = self.client.get(url)
                missing_csrf = self.client.post(url)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(missing_csrf.status_code, 403)
                application.refresh_from_db()
                self.assertEqual(application.state, SellerApplication.State.DRAFT)

        edit_get = self.client.get(
            reverse("seller-application-edit", kwargs={"application_id": application_id})
        )
        self.assertEqual(edit_get.status_code, 200)
        self.assertEqual(AccountSession.objects.get(pk=registry.id).revoked_at, None)
        self.assertEqual(SellerApplication.objects.get(pk=application_id).current_version, 0)

        csrf = self.client.cookies["csrftoken"].value
        edit_missing_csrf = self.client.post(
            reverse("seller-application-edit", kwargs={"application_id": application_id}),
            self.draft,
        )
        self.assertEqual(edit_missing_csrf.status_code, 403)
        self.assertEqual(SellerApplication.objects.get(pk=application_id).current_version, 0)
        self._assert_secure(edit_get)

    def test_operation_context_uses_registry_request_and_remote_address(self):
        account = self._account()
        registry = self._bind(self.client, account)
        real_operation = self.public.create_seller_application
        supplied_request_id = str(uuid4())

        with patch.object(self.public, "create_seller_application", side_effect=real_operation) as operation:
            response = self._post(
                self.client,
                "seller-application-create",
                REMOTE_ADDR="198.51.100.17",
                HTTP_X_FORWARDED_FOR="203.0.113.99",
                HTTP_X_REQUEST_ID=supplied_request_id,
            )

        self.assertEqual(response.status_code, 303)
        context = operation.call_args.kwargs["context"]
        self.assertEqual(context.actor_account_id, account.id)
        self.assertEqual(context.session_id, registry.id)
        self.assertEqual(context.request_id, UUID(response["X-Request-ID"]))
        self.assertNotEqual(str(context.request_id), supplied_request_id)
        self.assertEqual(context.source, "html")
        self.assertEqual(context.source_address, "198.51.100.17")

    def test_edit_form_contains_only_seller_draft_fields_and_no_future_scope(self):
        account = self._account()
        self._bind(self.client, account)
        application_id = self._create_application()

        response = self.client.get(
            reverse("seller-application-edit", kwargs={"application_id": application_id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            tuple(response.context["form"].fields),
            (
                "business_form",
                "display_name",
                "official_name",
                "registration_identifier",
                "contact_email",
                "test_data_attested",
            ),
        )
        body = response.content.decode().casefold()
        for forbidden in ("upload", "document", "payment", "kyc", "catalog", "production approval"):
            self.assertNotIn(forbidden, body)

    def test_draft_can_be_saved_reopened_submitted_and_then_not_edited(self):
        account = self._account()
        self._bind(self.client, account)
        application_id = self._create_application()

        saved = self._post(
            self.client,
            "seller-application-edit",
            data=self.draft,
            kwargs={"application_id": application_id},
        )
        self.assertEqual(saved.status_code, 303)

        reopened = self.client.get(
            reverse("seller-application-edit", kwargs={"application_id": application_id})
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.context["form"].initial["display_name"], "Test shop")
        self.assertEqual(reopened.context["form"].initial["contact_email"], "owner@example.com")

        submitted = self._post(
            self.client,
            "seller-application-submit",
            kwargs={"application_id": application_id},
        )
        self.assertEqual(submitted.status_code, 303)
        application = SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, SellerApplication.State.SUBMITTED)
        self.assertEqual(application.current_version, 1)
        version = SellerApplicationVersion.objects.get(application_id=application_id)
        self.assertEqual(version.display_name, "Test shop")

        detail = self.client.get(
            reverse("seller-application-detail", kwargs={"application_id": application_id})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Test shop")
        self.assertNotIn("form", detail.context)

        forbidden_edit = self._post(
            self.client,
            "seller-application-edit",
            data={**self.draft, "display_name": "Changed submitted version"},
            kwargs={"application_id": application_id},
        )
        self.assertEqual(forbidden_edit.status_code, 200)
        self.assertNotContains(forbidden_edit, "Changed submitted version")
        version.refresh_from_db()
        self.assertEqual(version.display_name, "Test shop")

    def test_detail_shows_only_actions_allowed_for_the_current_state(self):
        account = self._account()
        self._bind(self.client, account)
        application_id = self._create_application()
        detail_url = reverse(
            "seller-application-detail",
            kwargs={"application_id": application_id},
        )
        edit_url = reverse(
            "seller-application-edit",
            kwargs={"application_id": application_id},
        )
        submit_url = reverse(
            "seller-application-submit",
            kwargs={"application_id": application_id},
        )
        withdraw_url = reverse(
            "seller-application-withdraw",
            kwargs={"application_id": application_id},
        )

        draft_detail = self.client.get(detail_url)
        self.assertContains(draft_detail, edit_url)
        self.assertContains(draft_detail, f'action="{submit_url}"')
        self.assertContains(draft_detail, f'action="{withdraw_url}"')
        self.assertContains(draft_detail, "csrfmiddlewaretoken")

        self.assertEqual(
            self._post(
                self.client,
                "seller-application-edit",
                data=self.draft,
                kwargs={"application_id": application_id},
            ).status_code,
            303,
        )
        self.assertEqual(
            self._post(
                self.client,
                "seller-application-submit",
                kwargs={"application_id": application_id},
            ).status_code,
            303,
        )
        submitted_detail = self.client.get(detail_url)
        self.assertNotContains(submitted_detail, edit_url)
        self.assertNotContains(submitted_detail, f'action="{submit_url}"')
        self.assertContains(submitted_detail, f'action="{withdraw_url}"')

        self.assertEqual(
            self._post(
                self.client,
                "seller-application-withdraw",
                kwargs={"application_id": application_id},
            ).status_code,
            303,
        )
        withdrawn_detail = self.client.get(detail_url)
        self.assertContains(withdrawn_detail, reverse("seller-application-create"))
        self.assertNotContains(withdrawn_detail, f'action="{withdraw_url}"')

    def test_changes_requested_shows_reason_and_resubmission_creates_version_two(self):
        account = self._account()
        self._bind(self.client, account)
        application_id = self._submit_application()
        reason = "Please correct the official name."
        SellerApplication.objects.filter(pk=application_id).update(
            state=SellerApplication.State.CHANGES_REQUESTED,
            decision="request_changes",
            reason=reason,
        )

        detail = self.client.get(
            reverse("seller-application-detail", kwargs={"application_id": application_id})
        )
        self.assertContains(detail, reason)
        edit = self.client.get(
            reverse("seller-application-edit", kwargs={"application_id": application_id})
        )
        self.assertEqual(edit.context["form"].initial["display_name"], "Test shop")

        changed = {**self.draft, "display_name": "Corrected shop"}
        self.assertEqual(
            self._post(
                self.client,
                "seller-application-edit",
                data=changed,
                kwargs={"application_id": application_id},
            ).status_code,
            303,
        )
        self.assertEqual(
            self._post(
                self.client,
                "seller-application-submit",
                kwargs={"application_id": application_id},
            ).status_code,
            303,
        )

        versions = tuple(
            SellerApplicationVersion.objects.filter(application_id=application_id).order_by(
                "version_number"
            )
        )
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].display_name, "Test shop")
        self.assertEqual(versions[1].display_name, "Corrected shop")
        self.assertEqual(SellerApplication.objects.get(pk=application_id).current_version, 2)

    def test_foreign_and_unknown_application_are_the_same_neutral_result(self):
        owner = self._account()
        owner_client = Client(enforce_csrf_checks=True)
        self._bind(owner_client, owner)
        application_id = self._create_application(owner_client)
        self._post(
            owner_client,
            "seller-application-edit",
            data=self.draft,
            kwargs={"application_id": application_id},
        )

        other_client = Client(enforce_csrf_checks=True)
        self._bind(other_client, self._account())
        for name in ("seller-application-detail", "seller-application-edit"):
            with self.subTest(name=name):
                foreign = other_client.get(
                    reverse(name, kwargs={"application_id": application_id})
                )
                missing = other_client.get(
                    reverse(name, kwargs={"application_id": uuid4()})
                )
                self.assertEqual(foreign.status_code, missing.status_code)
                self.assertEqual(foreign.content, missing.content)
                self._assert_secure(foreign)
                self.assertNotContains(foreign, "Test shop")

    def test_rejected_or_withdrawn_application_can_be_replaced_but_only_one_is_unfinished(self):
        for terminal_state in (SellerApplication.State.REJECTED, SellerApplication.State.WITHDRAWN):
            with self.subTest(terminal_state=terminal_state):
                client = Client(enforce_csrf_checks=True)
                self._bind(client, self._account())
                first_id = self._create_application(client)
                if terminal_state == SellerApplication.State.WITHDRAWN:
                    response = self._post(
                        client,
                        "seller-application-withdraw",
                        kwargs={"application_id": first_id},
                    )
                    self.assertEqual(response.status_code, 303)
                else:
                    SellerApplication.objects.filter(pk=first_id).update(
                        state=SellerApplication.State.REJECTED,
                        decision="reject",
                        reason="Not eligible for this test flow.",
                    )

                second_id = self._create_application(client)
                self.assertNotEqual(first_id, second_id)
                self.assertEqual(
                    SellerApplication.objects.filter(
                        applicant_id=SellerApplication.objects.get(pk=second_id).applicant_id,
                        state__in=("draft", "submitted", "under_review", "changes_requested"),
                    ).count(),
                    1,
                )
                conflict = self._post(client, "seller-application-create")
                self.assertEqual(conflict.status_code, 200)
                self.assertEqual(
                    SellerApplication.objects.filter(
                        applicant_id=SellerApplication.objects.get(pk=second_id).applicant_id
                    ).count(),
                    2,
                )

    def test_lists_details_and_status_show_public_state_and_reason_without_draft_data_in_list(self):
        account = self._account()
        self._bind(self.client, account)
        application_id = self._submit_application()
        reason = "Seller profile is temporarily restricted."
        SellerApplication.objects.filter(pk=application_id).update(
            state=SellerApplication.State.CHANGES_REQUESTED,
            decision="request_changes",
            reason=reason,
        )
        now = timezone.now()
        SellerProfile.objects.create(
            owner_id=account.id,
            application_id=application_id,
            approved_version=1,
            state=SellerProfile.State.SUSPENDED,
            restriction_reason=reason,
            created_at=now,
            updated_at=now,
        )

        listing = self.client.get(reverse("seller-applications"))
        detail = self.client.get(
            reverse("seller-application-detail", kwargs={"application_id": application_id})
        )
        status = self.client.get(reverse("seller-status"))

        for response in (listing, detail, status):
            self.assertEqual(response.status_code, 200)
            self._assert_secure(response)
        self.assertContains(listing, "changes_requested")
        self.assertContains(listing, reason)
        self.assertNotContains(listing, "Test shop")
        self.assertContains(detail, "changes_requested")
        self.assertContains(detail, reason)
        self.assertContains(detail, "Test shop")
        self.assertContains(status, "suspended")
        self.assertContains(status, reason)

    def test_invalid_forms_and_application_errors_are_neutral_bounded_and_secure(self):
        account = self._account()
        self._bind(self.client, account)
        application_id = self._create_application()
        invalid = self._post(
            self.client,
            "seller-application-edit",
            data={"display_name": "not enough data"},
            kwargs={"application_id": application_id},
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertNotContains(invalid, "not enough data")
        self.assertLess(len(invalid.content), 16_384)
        self._assert_secure(invalid)

        failed_submit = self._post(
            self.client,
            "seller-application-submit",
            kwargs={"application_id": application_id},
        )
        self.assertEqual(failed_submit.status_code, 200)
        self.assertNotContains(failed_submit, "Seller application data is incomplete")
        self.assertLess(len(failed_submit.content), 16_384)
        self._assert_secure(failed_submit)
