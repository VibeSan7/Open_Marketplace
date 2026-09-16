import re
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pyotp
from django.apps import apps
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from open_marketplace.access import public as access_public
from open_marketplace.audit import public as audit_public
from open_marketplace.common.errors import AuthenticationDenied, InvalidState, PermissionDenied
from open_marketplace.common.types import OperationContext
from open_marketplace.identity import public as identity_public
from open_marketplace.outbox import public as outbox_public
from open_marketplace.seller_onboarding import public as seller_public


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class FullFlowTests(TestCase):
    password = "Correct Horse Battery Staple 42!"
    new_password = "Another Strong Password 73!"
    draft = {
        "business_form": "sole_proprietor",
        "display_name": "Test shop",
        "official_name": "Test business",
        "registration_identifier": "TEST-123",
        "contact_email": "owner@example.com",
        "test_data_attested": "on",
    }

    def _context(self, *, actor=None, session=None, source="html", now=None):
        return OperationContext(
            actor_account_id=actor,
            session_id=session,
            request_id=uuid4(),
            source=source,
            source_address="198.51.100.17" if actor else "203.0.113.10",
            now=now or timezone.now(),
        )

    def _anonymous(self, *, source="html", now=None):
        return self._context(source=source, now=now)

    def _client_context(self, client, *, source="html", now=None):
        session = client.session
        return self._context(
            actor=UUID(session["account_id"]),
            session=UUID(session["session_id"]),
            source=source,
            now=now,
        )

    def _csrf_post(self, client, route, data=None, *, kwargs=None):
        url = reverse(route, kwargs=kwargs or {})
        response = client.get(url)
        if response.status_code != 200:
            self.assertEqual(response.status_code, 405)
            response = client.get(reverse("security"))
        self.assertEqual(response.status_code, 200)
        return client.post(
            url,
            {"csrfmiddlewaretoken": client.cookies["csrftoken"].value, **(data or {})},
        )

    def _deliver_link(self, message_type):
        mail.outbox.clear()
        call_command("run_outbox_worker", "--once")
        messages = [
            message
            for message in mail.outbox
            if message.extra_headers.get("X-Open-Marketplace-Message-Type") == message_type
        ]
        self.assertEqual(len(messages), 1)
        return re.search(r"https?://[^\s]+", messages[0].body).group(0).rstrip(".")

    def _register(self, email):
        identity_public.register_account(
            email=email,
            password=self.password,
            context=self._anonymous(),
        )
        return self._deliver_link("identity.email_verification")

    def _verify_email(self, client, link):
        self.assertEqual(client.get(link).status_code, 303)
        response = self._csrf_post(client, "verify-email-complete")
        self.assertEqual(response.status_code, 200)
        return response

    def _login(self, client, email, password=None, *, second_factor=""):
        password = password or self.password
        response = client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        response = client.post(
            reverse("login"),
            {
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
                "email": email,
                "password": password,
                "second_factor": second_factor,
                "next": reverse("security"),
            },
        )
        return response

    def _register_and_login(self, email):
        client = Client(enforce_csrf_checks=True)
        link = self._register(email)
        self._verify_email(client, link)
        response = self._login(client, email)
        self.assertEqual(response.status_code, 303)
        return client, UUID(client.session["account_id"])

    def _logout(self, client):
        response = client.get(reverse("security"))
        self.assertEqual(response.status_code, 200)
        response = client.post(
            reverse("logout"),
            {"csrfmiddlewaretoken": client.cookies["csrftoken"].value},
        )
        self.assertEqual(response.status_code, 303)

    def _staff_from_invitation(self, link, email, *, password=None):
        password = password or self.password
        setup = access_public.begin_staff_invitation_acceptance(
            raw_token=self._token_from_link(link),
            password=password,
            context=self._anonymous(),
        )
        code = pyotp.TOTP(setup.totp_setup.manual_secret).at(timezone.now())
        result = access_public.accept_staff_invitation(
            acceptance_id=setup.acceptance_id,
            raw_token=self._token_from_link(link),
            totp_code=code,
            context=self._anonymous(),
        )
        return {
            "account_id": setup.account_id,
            "email": email,
            "password": password,
            "secret": setup.totp_setup.manual_secret,
            "raw_token": self._token_from_link(link),
            "recovery_codes": result.recovery_codes,
        }

    def _token_from_link(self, link):
        return link.rstrip("/").rsplit("/", 1)[-1]

    def _bootstrap_staff(self, email=None):
        email = email or f"admin-{uuid4().hex}@example.com"
        output = StringIO()
        call_command("bootstrap_security_admin", "--email", email, stdout=output)
        invitation_id = UUID(re.search(r"[0-9a-f-]{36}", output.getvalue()).group(0))
        link = self._deliver_link("access.staff_invitation")
        staff = self._staff_from_invitation(link, email)
        staff["invitation_id"] = invitation_id
        return staff

    def _login_staff(self, staff):
        client = Client(enforce_csrf_checks=True)
        response = self._login(
            client,
            staff["email"],
            staff["password"],
            second_factor=pyotp.TOTP(staff["secret"]).at(timezone.now() + timedelta(seconds=30)),
        )
        self.assertEqual(response.status_code, 303)
        staff["client"] = client
        return client

    def _invite_staff(self, admin, email, role):
        invitation_id = access_public.invite_staff_member(
            email=email,
            role=role,
            context=self._client_context(admin["client"], source="admin"),
        )
        link = self._deliver_link("access.staff_invitation")
        staff = self._staff_from_invitation(link, email)
        staff["invitation_id"] = invitation_id
        return staff

    def _admin_post(self, client, route, data=None, *, kwargs=None):
        response = client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        return client.post(
            reverse(route, kwargs=kwargs or {}),
            {"csrfmiddlewaretoken": client.cookies["csrftoken"].value, **(data or {})},
        )

    def _make_reviewers(self):
        admin = self._bootstrap_staff()
        self._login_staff(admin)
        reviewer = self._invite_staff(
            admin,
            f"reviewer-{uuid4().hex}@example.com",
            "seller_reviewer",
        )
        self._login_staff(reviewer)
        return admin, reviewer

    def _create_submitted_application(self, owner_client, *, display_name="Test shop"):
        response = self._csrf_post(owner_client, "seller-application-create")
        self.assertEqual(response.status_code, 303)
        application_id = UUID(re.search(r"[0-9a-f-]{36}", response["Location"]).group(0))
        data = {**self.draft, "display_name": display_name}
        response = self._csrf_post(
            owner_client,
            "seller-application-edit",
            data,
            kwargs={"application_id": application_id},
        )
        self.assertEqual(response.status_code, 303)
        response = self._csrf_post(
            owner_client,
            "seller-application-submit",
            kwargs={"application_id": application_id},
        )
        self.assertEqual(response.status_code, 303)
        return application_id

    def _review(self, reviewer_client, application_id, action, reason):
        response = self._admin_post(
            reviewer_client,
            action,
            {"reason": reason} if reason else {},
            kwargs={"application_id": application_id},
        )
        self.assertEqual(response.status_code, 303)

    def _approve_application(self, owner_client, reviewer_client, application_id):
        response = self._csrf_post(owner_client, "totp-setup", {"current_password": self.password})
        setup = response.context["setup"]
        enabled = owner_client.post(
            reverse("totp-setup"),
            {
                "csrfmiddlewaretoken": owner_client.cookies["csrftoken"].value,
                "setup_id": str(setup.setup_id),
                "code": pyotp.TOTP(setup.manual_secret).now(),
            },
        )
        self.assertEqual(enabled.status_code, 200)
        self._review(reviewer_client, application_id, "admin:seller-application-start-review", "")
        self._review(
            reviewer_client,
            application_id,
            "admin:seller-application-approve",
            "Evidence checked.",
        )
        owner_context = self._client_context(owner_client)
        profile = seller_public.get_seller_profile_for_owner(context=owner_context)
        self.assertIsNotNone(profile)
        return profile

    def test_registration_email_confirmation_and_login(self):
        email = f"owner-{uuid4().hex}@example.com"
        client = Client(enforce_csrf_checks=True)
        link = self._register(email)

        self._verify_email(client, link)
        response = self._login(client, email)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(identity_public.get_account_snapshot(UUID(client.session["account_id"])).state, "active")

    def test_expired_and_reused_links_are_rejected(self):
        email = f"expired-{uuid4().hex}@example.com"
        link = self._register(email)
        client = Client(enforce_csrf_checks=True)
        future = timezone.now() + timedelta(days=2)
        with patch("open_marketplace.web.sensitive_links.timezone.now", return_value=future), patch(
            "open_marketplace.web.identity_views.timezone.now", return_value=future
        ):
            self.assertEqual(client.get(link).status_code, 303)
            response = self._csrf_post(client, "verify-email-complete")
        self.assertContains(response, "Не удалось выполнить этот запрос.")

        email = f"reused-{uuid4().hex}@example.com"
        link = self._register(email)
        client = Client(enforce_csrf_checks=True)
        self._verify_email(client, link)
        replay = Client(enforce_csrf_checks=True)
        self.assertEqual(replay.get(link).status_code, 303)
        replay_response = self._csrf_post(replay, "verify-email-complete")
        self.assertContains(replay_response, "Не удалось выполнить этот запрос.")

    def test_password_reset_revokes_previous_sessions(self):
        email = f"reset-{uuid4().hex}@example.com"
        first, account_id = self._register_and_login(email)
        second = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(second, email).status_code, 303)

        identity_public.request_password_reset(email=email, context=self._anonymous())
        link = self._deliver_link("identity.password_reset")
        reset = Client(enforce_csrf_checks=True)
        self.assertEqual(reset.get(link).status_code, 303)
        response = self._csrf_post(reset, "password-reset-confirm", {"new_password": self.new_password})
        self.assertContains(response, "Пароль изменён.")

        self.assertEqual(first.get(reverse("security")).status_code, 303)
        self.assertEqual(second.get(reverse("security")).status_code, 303)
        self.assertEqual(identity_public.get_account_snapshot(account_id).state, "active")

    def test_totp_and_recovery_code_work_and_recovery_replay_fails(self):
        email = f"totp-{uuid4().hex}@example.com"
        client, account_id = self._register_and_login(email)
        response = self._csrf_post(client, "totp-setup", {"current_password": self.password})
        setup = response.context["setup"]
        code = pyotp.TOTP(setup.manual_secret).now()
        enabled = client.post(
            reverse("totp-setup"),
            {
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
                "setup_id": str(setup.setup_id),
                "code": code,
            },
        )
        recovery_code = enabled.context["recovery_codes"][0]
        self._logout(client)

        totp_client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            self._login(
                totp_client,
                email,
                second_factor=pyotp.TOTP(setup.manual_secret).at(timezone.now() + timedelta(seconds=30)),
            ).status_code,
            303,
        )
        self._logout(totp_client)

        recovery_client = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(recovery_client, email, second_factor=recovery_code).status_code, 303)
        self._logout(recovery_client)
        replay = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(replay, email, second_factor=recovery_code).status_code, 200)
        self.assertTrue(identity_public.get_account_snapshot(account_id).totp_enabled)

    def test_email_access_alone_cannot_disable_mandatory_totp(self):
        admin = self._bootstrap_staff()
        identity_public.request_password_reset(email=admin["email"], context=self._anonymous())
        link = self._deliver_link("identity.password_reset")
        reset = Client(enforce_csrf_checks=True)
        reset.get(link)
        self._csrf_post(reset, "password-reset-confirm", {"new_password": self.new_password})

        without_totp = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(without_totp, admin["email"], self.new_password).status_code, 200)
        self.assertTrue(identity_public.get_account_snapshot(admin["account_id"]).totp_enabled)
        with_totp = Client(enforce_csrf_checks=True)
        self.assertEqual(
            self._login(
                with_totp,
                admin["email"],
                self.new_password,
                second_factor=pyotp.TOTP(admin["secret"]).at(timezone.now() + timedelta(seconds=30)),
            ).status_code,
            303,
        )

    def test_initial_security_admin_bootstrap_only_once(self):
        admin = self._bootstrap_staff()
        self.assertEqual(identity_public.get_account_snapshot(admin["account_id"]).kind, "service")
        with self.assertRaises((InvalidState, PermissionDenied)):
            call_command(
                "bootstrap_security_admin",
                "--email",
                f"second-{uuid4().hex}@example.com",
                stdout=StringIO(),
            )

    def test_one_time_staff_invitation_grants_only_named_role(self):
        admin = self._bootstrap_staff()
        self._login_staff(admin)
        reviewer_email = f"named-{uuid4().hex}@example.com"
        invitation_id = access_public.invite_staff_member(
            email=reviewer_email,
            role="seller_reviewer",
            context=self._client_context(admin["client"], source="admin"),
        )
        link = self._deliver_link("access.staff_invitation")
        reviewer = self._staff_from_invitation(link, reviewer_email)
        roles = access_public.list_active_roles(
            account_id=reviewer["account_id"],
            context=self._client_context(admin["client"], source="admin"),
        )
        self.assertEqual(tuple(role.role for role in roles), ("seller_reviewer",))
        self.assertEqual(reviewer["account_id"], access_public.list_active_roles(
            account_id=reviewer["account_id"],
            context=self._client_context(admin["client"], source="admin"),
        )[0].account_id)
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            access_public.begin_staff_invitation_acceptance(
                raw_token=reviewer["raw_token"],
                password=self.password,
                context=self._anonymous(),
            )
        self.assertIsNotNone(invitation_id)

    def test_draft_submit_changes_requested_new_version_approve(self):
        owner, owner_id = self._register_and_login(f"seller-{uuid4().hex}@example.com")
        _, reviewer = self._make_reviewers()
        application_id = self._create_submitted_application(owner)
        self._review(reviewer["client"], application_id, "admin:seller-application-start-review", "")
        self._review(reviewer["client"], application_id, "admin:seller-application-request-changes", "Correct the official name.")
        self.assertEqual(
            self._csrf_post(
                owner,
                "seller-application-edit",
                {**self.draft, "display_name": "Corrected shop"},
                kwargs={"application_id": application_id},
            ).status_code,
            303,
        )
        self.assertEqual(
            self._csrf_post(owner, "seller-application-submit", kwargs={"application_id": application_id}).status_code,
            303,
        )
        self._approve_application(owner, reviewer["client"], application_id)
        application, versions = seller_public.get_own_seller_application(
            application_id=application_id,
            context=self._client_context(owner),
        )
        self.assertEqual(application.state, "approved")
        self.assertEqual(application.current_version, 2)
        self.assertEqual(tuple(version.version_number for version in versions), (1, 2))
        self.assertEqual(application.applicant_id, owner_id)

    def test_repeated_approve_creates_no_second_seller(self):
        owner, _ = self._register_and_login(f"repeat-{uuid4().hex}@example.com")
        _, reviewer = self._make_reviewers()
        application_id = self._create_submitted_application(owner)
        profile = self._approve_application(owner, reviewer["client"], application_id)
        with self.assertRaises(InvalidState):
            seller_public.approve_seller_application(
                application_id=application_id,
                reason="Duplicate request.",
                context=self._client_context(reviewer["client"], source="admin"),
            )
        self.assertEqual(
            seller_public.get_seller_profile_for_owner(context=self._client_context(owner)).id,
            profile.id,
        )

    def test_reject_leaves_ordinary_account_active(self):
        owner, owner_id = self._register_and_login(f"reject-{uuid4().hex}@example.com")
        _, reviewer = self._make_reviewers()
        application_id = self._create_submitted_application(owner)
        self._review(reviewer["client"], application_id, "admin:seller-application-start-review", "")
        self._review(reviewer["client"], application_id, "admin:seller-application-reject", "Not eligible.")
        self.assertEqual(identity_public.get_account_snapshot(owner_id).state, "active")
        self.assertEqual(owner.get(reverse("security")).status_code, 200)

    def test_reject_or_withdraw_allows_separate_history_and_one_unfinished_application(self):
        owner, _ = self._register_and_login(f"history-{uuid4().hex}@example.com")
        _, reviewer = self._make_reviewers()
        rejected = self._create_submitted_application(owner, display_name="Rejected shop")
        self._review(reviewer["client"], rejected, "admin:seller-application-start-review", "")
        self._review(reviewer["client"], rejected, "admin:seller-application-reject", "Rejected for test.")
        replacement = self._create_submitted_application(owner, display_name="Replacement shop")
        self._review(reviewer["client"], replacement, "admin:seller-application-start-review", "")
        self._review(reviewer["client"], replacement, "admin:seller-application-reject", "Rejected again.")
        withdrawn = self._csrf_post(owner, "seller-application-create")
        withdrawn_id = UUID(re.search(r"[0-9a-f-]{36}", withdrawn["Location"]).group(0))
        self.assertEqual(
            self._csrf_post(owner, "seller-application-withdraw", kwargs={"application_id": withdrawn_id}).status_code,
            303,
        )
        new_id = UUID(
            re.search(
                r"[0-9a-f-]{36}",
                self._csrf_post(owner, "seller-application-create")["Location"],
            ).group(0)
        )
        applications = seller_public.list_own_seller_applications(context=self._client_context(owner))
        unfinished = [application for application in applications if application.state in {"draft", "submitted", "under_review", "changes_requested"}]
        self.assertEqual(len(unfinished), 1)
        self.assertEqual(unfinished[0].id, new_id)
        self.assertNotEqual(rejected, replacement)

    def test_security_admin_suspends_restores_seller_without_blocking_owner(self):
        owner, owner_id = self._register_and_login(f"suspend-{uuid4().hex}@example.com")
        admin = self._bootstrap_staff()
        self._login_staff(admin)
        application_id = self._create_submitted_application(owner)
        reviewer = self._invite_staff(admin, f"review-{uuid4().hex}@example.com", "seller_reviewer")
        self._login_staff(reviewer)
        profile = self._approve_application(owner, reviewer["client"], application_id)
        self._admin_post(admin["client"], "admin:seller-profile-suspend", {"reason": "Risk review."}, kwargs={"seller_id": profile.id})
        self.assertContains(owner.get(reverse("seller-status")), "приостановлен")
        self._admin_post(admin["client"], "admin:seller-profile-restore", {"reason": "Risk cleared."}, kwargs={"seller_id": profile.id})
        self.assertContains(owner.get(reverse("seller-status")), "активен")
        self.assertEqual(identity_public.get_account_snapshot(owner_id).state, "active")

    def test_forbidden_staff_operation_is_denied_and_audited(self):
        admin = self._bootstrap_staff()
        self._login_staff(admin)
        reviewer = self._invite_staff(admin, f"forbidden-{uuid4().hex}@example.com", "seller_reviewer")
        self._login_staff(reviewer)
        target = self._register_and_login(f"target-{uuid4().hex}@example.com")[1]
        response = self._admin_post(
            reviewer["client"],
            "admin:account-block",
            {"reason": "Denied operation."},
            kwargs={"account_id": target},
        )
        self.assertEqual(response.status_code, 403)
        audit_entries = apps.get_model("audit", "AuditEntry").objects.filter(
            action="access.permission_denied",
            object_type="account",
            result="denied",
        )
        self.assertTrue(audit_entries.exists())

    def test_outbox_retry_and_expired_lease_reclaim_do_not_repeat_domain_change(self):
        email = f"outbox-{uuid4().hex}@example.com"
        identity_public.register_account(email=email, password=self.password, context=self._anonymous())
        now = timezone.now()
        first = outbox_public.claim_ready_messages(
            worker_id="acceptance-worker-1",
            now=now,
            lease_seconds=1,
            limit=10,
        )[0]
        outbox_public.schedule_message_retry(
            message_id=first.id,
            worker_id="acceptance-worker-1",
            attempt_number=first.attempt_number,
            now=now,
            safe_error="smtp_failure",
        )
        retry = outbox_public.claim_ready_messages(
            worker_id="acceptance-worker-2",
            now=now + timedelta(seconds=61),
            lease_seconds=1,
            limit=10,
        )[0]
        reclaimed = outbox_public.claim_ready_messages(
            worker_id="acceptance-worker-3",
            now=now + timedelta(seconds=63),
            lease_seconds=1,
            limit=10,
        )[0]
        outbox_public.mark_message_succeeded(
            message_id=reclaimed.id,
            worker_id="acceptance-worker-3",
            attempt_number=reclaimed.attempt_number,
            now=now + timedelta(seconds=63),
        )
        self.assertEqual(retry.id, reclaimed.id)
        self.assertEqual(apps.get_model("identity", "Account").objects.filter(email=email).count(), 1)
        self.assertEqual(
            outbox_public.get_outbox_message_snapshot(idempotency_key=first.idempotency_key).state,
            "succeeded",
        )

    def test_audit_reconstructs_action_chain_without_secrets(self):
        owner, _ = self._register_and_login(f"audit-{uuid4().hex}@example.com")
        _, reviewer = self._make_reviewers()
        application_id = self._create_submitted_application(owner)
        self._review(reviewer["client"], application_id, "admin:seller-application-start-review", "")
        self._review(reviewer["client"], application_id, "admin:seller-application-approve", "Approved.")
        entries = audit_public.query_audit_entries(
            query=audit_public.AuditQuery(
                from_at=None,
                to_at=None,
                actor_id=None,
                action=None,
                object_type="seller_application",
                object_id=str(application_id),
                result="success",
                limit=100,
                cursor=None,
            ),
            context=self._client_context(reviewer["client"], source="admin"),
            authorize=lambda context, permission: access_public.authorize(
                context=context,
                permission=permission,
            ),
        )
        actions = [entry.action for entry in reversed(entries)]
        self.assertEqual(
            actions,
            [
                "seller_onboarding.application_created",
                "seller_onboarding.application_updated",
                "seller_onboarding.application_submitted",
                "seller_onboarding.application_review_started",
                "seller_onboarding.application_decided",
            ],
        )
        rendered = repr(entries)
        self.assertNotIn(self.password, rendered)
        self.assertNotIn("manual_secret", rendered)
        self.assertNotIn("token", rendered.casefold())

    def test_account_block_revokes_sessions(self):
        email = f"blocked-{uuid4().hex}@example.com"
        owner, owner_id = self._register_and_login(email)
        second = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(second, email).status_code, 303)
        admin = self._bootstrap_staff()
        self._login_staff(admin)
        response = self._admin_post(
            admin["client"],
            "admin:account-block",
            {"reason": "Account security event."},
            kwargs={"account_id": owner_id},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(owner.get(reverse("security")).status_code, 303)
        self.assertEqual(identity_public.get_account_snapshot(owner_id).state, "blocked")

    def test_restore_verification_command_contract_is_safe(self):
        marker = f"acceptance{uuid4().hex[:10]}"
        output = StringIO()
        call_command("seed_restore_probe", "--marker", marker, stdout=output)
        call_command("verify_restore_probe", "--marker", marker, stdout=output)
        rendered = output.getvalue()
        self.assertIn(f"restore_verification_complete marker={marker}", rendered)
        self.assertIn("row_kind=seller_profile", rendered)
        self.assertNotIn("password", rendered.casefold())
        self.assertNotIn("manual_secret", rendered)
        self.assertNotRegex(rendered, r"[A-Za-z0-9_-]{40,}")
