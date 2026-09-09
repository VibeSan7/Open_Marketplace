from datetime import UTC, datetime, timedelta
from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.db.migrations.executor import MigrationExecutor

from open_marketplace.access.public import (
    StaffInvitationQuery,
    list_active_roles,
    list_staff_invitations,
)
from open_marketplace.common.types import OperationContext
from open_marketplace.identity.public import (
    get_account_snapshot,
    get_session_security_snapshot,
)
from open_marketplace.seller_onboarding.public import (
    SellerDraftData,
    get_own_seller_application,
    get_seller_profile_for_owner,
)


class MigrationCompatibilityTests(TransactionTestCase):
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql")
        self.executor = MigrationExecutor(connection)
        self.leaf_targets = tuple(sorted(self.executor.loader.graph.leaf_nodes()))
        self.addCleanup(self._restore_leaf_schema)

    def _restore_leaf_schema(self):
        MigrationExecutor(connection).migrate(self.leaf_targets)

    def _migrate_to_leaves(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.leaf_targets)

    def _apps_at(self, app_label, migration_name):
        targets = list(self.leaf_targets)
        targets[targets.index(next(target for target in targets if target[0] == app_label))] = (
            app_label,
            migration_name,
        )
        if app_label == "identity" and migration_name in {
            "0001_initial",
            "0002_onetimetoken",
            "0003_accountsession",
            "0004_recoverycode_totpcredential_totprequirement_and_more",
        }:
            targets[targets.index(next(target for target in targets if target[0] == "access"))] = (
                "access",
                "0001_initial",
            )
        targets = tuple(targets)
        self.executor.migrate(targets)
        return self.executor.loader.project_state(targets).apps

    def _current_apps(self):
        return self.executor.loader.project_state(self.leaf_targets).apps

    def _account(
        self,
        apps,
        *,
        email=None,
        kind="ordinary",
        state="active",
        email_verified_at=None,
    ):
        Account = apps.get_model("identity", "Account")
        return Account.objects.create(
            id=uuid4(),
            email=email or f"account-{uuid4()}@example.com",
            password="!",
            kind=kind,
            state=state,
            email_verified_at=email_verified_at,
        )

    def _token(self, apps, account_id, *, token_id=None):
        Token = apps.get_model("identity", "OneTimeToken")
        return Token.objects.create(
            id=token_id or uuid4(),
            account_id=account_id,
            purpose="email_verification",
            token_digest=uuid4().hex + uuid4().hex,
            created_at=self.now,
            expires_at=self.now + timedelta(hours=1),
        )

    def _session(self, apps, account_id, *, session_id=None, django_key=None):
        Session = apps.get_model("identity", "AccountSession")
        return Session.objects.create(
            id=session_id or uuid4(),
            account_id=account_id,
            django_session_key=django_key or uuid4().hex[:40],
            created_at=self.now,
            last_activity_at=self.now,
            absolute_expires_at=self.now + timedelta(hours=1),
            reauthenticated_at=self.now,
            device_label="migration test",
        )

    def _assert_constraints(self, apps, app_label, model_name):
        model = apps.get_model(app_label, model_name)
        table_name = model._meta.db_table
        with connection.cursor() as cursor:
            self.assertIn(table_name, connection.introspection.table_names(cursor))
            constraints = connection.introspection.get_constraints(cursor, table_name)
        for constraint in model._meta.constraints:
            self.assertIn(constraint.name, constraints)

    def _assert_integrity_error(self, operation):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                operation()

    def _authenticated_context(self, account_id, session_id):
        return OperationContext(
            actor_account_id=account_id,
            session_id=session_id,
            request_id=uuid4(),
            source="html",
            source_address="192.0.2.1",
            now=self.now,
        )

    def test_identity_0002_preserves_account_and_creates_token_schema(self):
        predecessor_apps = self._apps_at("identity", "0001_initial")
        account = self._account(
            predecessor_apps,
            email="buyer@example.com",
            state="pending_email_verification",
        )
        account_id = account.id

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        snapshot = get_account_snapshot(account_id)

        self.assertEqual(snapshot.id, account_id)
        self.assertEqual(snapshot.email, "buyer@example.com")
        self.assertEqual(snapshot.kind, "ordinary")
        self.assertEqual(snapshot.state, "pending_email_verification")
        self.assertIsNone(snapshot.email_verified_at)
        self.assertFalse(snapshot.totp_enabled)
        self.assertEqual(current_apps.get_model("identity", "Account").objects.get(pk=account_id).version, 1)

        self._assert_constraints(current_apps, "identity", "OneTimeToken")
        token = self._token(current_apps, account_id)
        Token = current_apps.get_model("identity", "OneTimeToken")
        self.assertEqual(Token.objects.get(pk=token.id).account_id, account_id)
        self._assert_integrity_error(
            lambda: Token.objects.create(
                id=uuid4(),
                account_id=account_id,
                purpose="email_verification",
                token_digest=token.token_digest,
                created_at=self.now,
                expires_at=self.now + timedelta(hours=1),
            )
        )

    def test_identity_0003_preserves_token_and_creates_session_schema(self):
        predecessor_apps = self._apps_at("identity", "0002_onetimetoken")
        account = self._account(predecessor_apps, email="session@example.com")
        token = self._token(predecessor_apps, account.id)
        session_id = uuid4()
        django_key = uuid4().hex[:40]

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        self._session(
            current_apps,
            account.id,
            session_id=session_id,
            django_key=django_key,
        )
        self.assertEqual(
            current_apps.get_model("identity", "OneTimeToken").objects.get(pk=token.id).account_id,
            account.id,
        )
        session_snapshot = get_session_security_snapshot(
            session_id=session_id,
            account_id=account.id,
        )
        self.assertEqual(session_snapshot.id, session_id)
        self.assertEqual(session_snapshot.account_id, account.id)
        self.assertIsNone(session_snapshot.revoked_at)

        self._assert_constraints(current_apps, "identity", "AccountSession")
        Session = current_apps.get_model("identity", "AccountSession")
        self._assert_integrity_error(
            lambda: Session.objects.create(
                id=uuid4(),
                account_id=account.id,
                django_session_key=uuid4().hex[:40],
                created_at=self.now,
                last_activity_at=self.now + timedelta(hours=1),
                absolute_expires_at=self.now + timedelta(hours=1),
                device_label="invalid migration test",
            )
        )

    def test_identity_0004_preserves_predecessor_and_creates_security_tables(self):
        predecessor_apps = self._apps_at("identity", "0003_accountsession")
        account = self._account(predecessor_apps, email="security@example.com")
        self._token(predecessor_apps, account.id)
        session = self._session(predecessor_apps, account.id)

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        self.assertEqual(get_account_snapshot(account.id).id, account.id)
        self.assertEqual(
            get_session_security_snapshot(
                session_id=session.id,
                account_id=account.id,
            ).id,
            session.id,
        )

        for model_name in (
            "RecoveryCode",
            "TotpCredential",
            "TotpRequirement",
            "TotpSetup",
        ):
            self._assert_constraints(current_apps, "identity", model_name)

        RecoveryCode = current_apps.get_model("identity", "RecoveryCode")
        recovery_code = RecoveryCode.objects.create(
            account_id=account.id,
            set_id=uuid4(),
            code_digest="a" * 64,
            issued_at=self.now,
        )
        self.assertEqual(recovery_code.account_id, account.id)
        self._assert_integrity_error(
            lambda: RecoveryCode.objects.create(
                account_id=account.id,
                set_id=uuid4(),
                code_digest="b" * 64,
                issued_at=self.now,
                used_at=self.now,
                revoked_at=self.now,
            )
        )

        TotpCredential = current_apps.get_model("identity", "TotpCredential")
        TotpCredential.objects.create(
            account_id=account.id,
            encrypted_secret=b"encrypted",
            confirmed_at=self.now,
            last_accepted_counter=0,
        )
        self._assert_integrity_error(
            lambda: TotpCredential.objects.create(
                account_id=account.id,
                encrypted_secret=b"another",
                confirmed_at=self.now,
                last_accepted_counter=0,
            )
        )

        Requirement = current_apps.get_model("identity", "TotpRequirement")
        Requirement.objects.create(
            account_id=account.id,
            source_type="seller_profile",
            source_id=uuid4(),
            created_at=self.now,
        )
        Setup = current_apps.get_model("identity", "TotpSetup")
        setup = Setup.objects.create(
            account_id=account.id,
            session_id=session.id,
            encrypted_secret=b"encrypted",
            created_at=self.now,
            expires_at=self.now + timedelta(hours=1),
        )
        self.assertEqual(setup.session_id, session.id)

    def test_identity_0005_preserves_session_binding_and_adds_account_metadata(self):
        predecessor_apps = self._apps_at(
            "identity",
            "0004_recoverycode_totpcredential_totprequirement_and_more",
        )
        account = self._account(predecessor_apps, email="metadata@example.com")
        token = self._token(predecessor_apps, account.id)
        session = self._session(predecessor_apps, account.id)
        Setup = predecessor_apps.get_model("identity", "TotpSetup")
        setup_id = uuid4()
        Setup.objects.create(
            id=setup_id,
            account_id=account.id,
            session_id=session.id,
            encrypted_secret=b"encrypted",
            created_at=self.now,
            expires_at=self.now + timedelta(hours=1),
        )

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        account_snapshot = get_account_snapshot(account.id)
        self.assertEqual(account_snapshot.id, account.id)
        CurrentAccount = current_apps.get_model("identity", "Account")
        current_account = CurrentAccount.objects.get(pk=account.id)
        self.assertIsNone(current_account.block_audit_id)
        self.assertIsNone(current_account.block_reason)
        self.assertIsNone(current_account.blocked_at)
        self.assertIsNone(current_account.blocked_by_id)

        CurrentSetup = current_apps.get_model("identity", "TotpSetup")
        current_setup = CurrentSetup.objects.get(pk=setup_id)
        self.assertEqual(current_setup.session_id, session.id)
        self.assertIsNone(current_setup.recovery_token_id)
        self.assertEqual(
            current_apps.get_model("identity", "OneTimeToken").objects.get(pk=token.id).account_id,
            account.id,
        )
        self._assert_constraints(current_apps, "identity", "Account")
        self._assert_constraints(current_apps, "identity", "TotpSetup")
        self._assert_integrity_error(
            lambda: CurrentSetup.objects.create(
                account_id=account.id,
                session_id=session.id,
                recovery_token_id=token.id,
                encrypted_secret=b"invalid",
                created_at=self.now,
                expires_at=self.now + timedelta(hours=1),
            )
        )

    def test_identity_0006_preserves_account_and_creates_throttle_schema(self):
        predecessor_apps = self._apps_at(
            "identity",
            "0005_account_administration_and_totp_recovery",
        )
        account = self._account(predecessor_apps, email="throttle@example.com")

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        self.assertEqual(get_account_snapshot(account.id).email, "throttle@example.com")
        self._assert_constraints(current_apps, "identity", "SecurityThrottle")

        Throttle = current_apps.get_model("identity", "SecurityThrottle")
        throttle = Throttle.objects.create(
            scope="login",
            key_kind="account",
            key_hash="a" * 64,
            window_started_at=self.now,
        )
        self.assertEqual(throttle.allowed_attempt_count, 0)
        self.assertIsNone(throttle.blocked_until)
        self._assert_integrity_error(
            lambda: Throttle.objects.create(
                scope="login",
                key_kind="account",
                key_hash="not-a-sha256-digest",
                window_started_at=self.now,
            )
        )

    def test_access_0002_preserves_role_and_creates_invitation_schema(self):
        predecessor_apps = self._apps_at("access", "0001_initial")
        account = self._account(
            predecessor_apps,
            email="staff@example.com",
            kind="service",
            state="active",
            email_verified_at=self.now,
        )
        TotpCredential = predecessor_apps.get_model("identity", "TotpCredential")
        TotpCredential.objects.create(
            account_id=account.id,
            encrypted_secret=b"encrypted",
            confirmed_at=self.now,
            last_accepted_counter=0,
        )
        RoleAssignment = predecessor_apps.get_model("access", "RoleAssignment")
        role_id = uuid4()
        RoleAssignment.objects.create(
            id=role_id,
            account_id=account.id,
            role="security_admin",
            assigned_reason="migration test",
            active_from=self.now,
        )
        django_key = uuid4().hex[:40]
        Sessions = predecessor_apps.get_model("sessions", "Session")
        Sessions.objects.create(
            session_key=django_key,
            session_data="",
            expire_date=self.now + timedelta(hours=1),
        )
        session = self._session(
            predecessor_apps,
            account.id,
            django_key=django_key,
        )
        context = self._authenticated_context(account.id, session.id)

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        roles = list_active_roles(account_id=account.id, context=context)
        self.assertEqual(tuple(role.id for role in roles), (role_id,))
        self.assertEqual(roles[0].account_id, account.id)

        self._assert_constraints(current_apps, "access", "StaffInvitation")
        self._assert_constraints(current_apps, "access", "StaffInvitationAcceptance")
        Invitation = current_apps.get_model("access", "StaffInvitation")
        invitation = Invitation.objects.create(
            email="invite@example.com",
            role="seller_reviewer",
            token_digest="c" * 64,
            created_at=self.now,
            expires_at=self.now + timedelta(hours=1),
        )
        invitations = list_staff_invitations(
            query=StaffInvitationQuery(
                state="pending",
                role="seller_reviewer",
                canonical_email="invite@example.com",
                limit=10,
                cursor=None,
            ),
            context=context,
        )
        self.assertEqual(tuple(item.id for item in invitations), (invitation.id,))
        self.assertEqual(invitations[0].state, "pending")

        Acceptance = current_apps.get_model("access", "StaffInvitationAcceptance")
        Acceptance.objects.create(
            invitation_id=invitation.id,
            token_digest="d" * 64,
            account_id=account.id,
            created_at=self.now,
        )
        self._assert_integrity_error(
            lambda: Acceptance.objects.create(
                invitation_id=invitation.id,
                token_digest="d" * 64,
                account_id=account.id,
                created_at=self.now,
            )
        )

    def test_seller_onboarding_0002_preserves_application_and_creates_profile_schema(self):
        predecessor_apps = self._apps_at("seller_onboarding", "0001_initial")
        account = self._account(
            predecessor_apps,
            email="seller@example.com",
            state="active",
            email_verified_at=self.now,
        )
        Application = predecessor_apps.get_model("seller_onboarding", "SellerApplication")
        application_id = uuid4()
        Application.objects.create(
            id=application_id,
            applicant_id=account.id,
            state="submitted",
            current_version=1,
            created_at=self.now,
            submitted_at=self.now,
        )
        Version = predecessor_apps.get_model("seller_onboarding", "SellerApplicationVersion")
        version_id = uuid4()
        Version.objects.create(
            id=version_id,
            application_id=application_id,
            version_number=1,
            business_form="legal_entity",
            display_name="Migration Shop",
            official_name="Migration Shop LLC",
            registration_identifier="MIG-1",
            contact_email="seller@example.com",
            test_data_attested=True,
            submitted_at=self.now,
        )
        context = OperationContext(
            actor_account_id=account.id,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="192.0.2.2",
            now=self.now,
        )

        self._migrate_to_leaves()
        current_apps = self._current_apps()
        application, versions = get_own_seller_application(
            application_id=application_id,
            context=context,
        )
        self.assertEqual(application.id, application_id)
        self.assertEqual(application.current_version, 1)
        self.assertEqual(versions[0].version_number, 1)
        self.assertEqual(versions[0].data.display_name, "Migration Shop")
        self.assertEqual(versions[0].data, SellerDraftData(
            business_form="legal_entity",
            display_name="Migration Shop",
            official_name="Migration Shop LLC",
            registration_identifier="MIG-1",
            contact_email="seller@example.com",
            test_data_attested=True,
        ))

        self._assert_constraints(current_apps, "seller_onboarding", "SellerProfile")
        self._assert_constraints(current_apps, "seller_onboarding", "SellerReviewDecision")
        Profile = current_apps.get_model("seller_onboarding", "SellerProfile")
        profile_id = uuid4()
        Profile.objects.create(
            id=profile_id,
            owner_id=account.id,
            application_id=application_id,
            approved_version=1,
            state="active",
            created_at=self.now,
            updated_at=self.now,
        )
        profile = get_seller_profile_for_owner(context=context)
        self.assertEqual(profile.id, profile_id)
        self.assertEqual(profile.owner_id, account.id)
        self.assertEqual(profile.application_id, application_id)
        self.assertEqual(profile.approved_version, 1)
        self.assertEqual(profile.state, "active")
        self._assert_integrity_error(
            lambda: Profile.objects.create(
                id=uuid4(),
                owner_id=uuid4(),
                application_id=application_id,
                approved_version=1,
                state="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        Decision = current_apps.get_model("seller_onboarding", "SellerReviewDecision")
        Decision.objects.create(
            application_id=application_id,
            version_number=1,
            decision="approve",
            reason="migration test",
            reviewer_id=uuid4(),
            occurred_at=self.now,
            request_id=uuid4(),
        )
        self._assert_integrity_error(
            lambda: Decision.objects.create(
                application_id=application_id,
                version_number=1,
                decision="reject",
                reason="duplicate migration test",
                reviewer_id=uuid4(),
                occurred_at=self.now,
                request_id=uuid4(),
            )
        )

    def test_migration_graph_is_clean(self):
        self.executor.loader.graph.validate_consistency()
        self.assertTrue(self.leaf_targets)
        self.assertEqual(set(self.leaf_targets), set(self.executor.loader.graph.leaf_nodes()))
