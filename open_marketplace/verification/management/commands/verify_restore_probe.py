"""Read-only verification of the restore-probe graph.

The command consumes public query/snapshot interfaces and framework
migration records only; it never writes domain rows.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.identity.public import AccountQuery, get_account_snapshot, query_accounts
from open_marketplace.outbox.public import get_outbox_message_snapshot
from open_marketplace.seller_onboarding.public import (
    get_own_seller_application,
    get_own_seller_review_decision,
    get_seller_profile_for_owner,
    list_own_seller_applications,
)
from open_marketplace.verification._probe import (
    command_context,
    find_probe_session,
    make_service_authorize,
    probe_email,
    require_marker,
)


class Command(BaseCommand):
    help = "Verify the restore-probe graph exists and is linked after a PostgreSQL restore."

    def add_arguments(self, parser):
        parser.add_argument("--marker", required=True, help="Deterministic restore marker.")

    def handle(self, *args, **options):
        try:
            marker = require_marker(options["marker"])
        except ValueError as error:
            raise CommandError(str(error)) from None
        authorize = make_service_authorize(read_only=True)
        failures: list[str] = []

        def record(*, name: str, ok: bool, detail: str = "") -> None:
            if not ok:
                failures.append(f"{name}: {detail}" if detail else name)
            self.stdout.write(f"row_kind={name} ok={'yes' if ok else 'no'} {detail}")

        try:
            self._check_migrations()
            admin_session = find_probe_session(marker, "security_admin")
            reviewer_session = find_probe_session(marker, "seller_reviewer")
            admin_context = command_context(
                actor_account_id=admin_session["account_id"],
                session_id=admin_session["session_id"],
            )
            reviewer_context = command_context(
                actor_account_id=reviewer_session["account_id"],
                session_id=reviewer_session["session_id"],
            )
            authorize(admin_context, "account.read")
            authorize(reviewer_context, "seller_application.review")

            accounts = query_accounts(
                query=AccountQuery(
                    kind=None,
                    state=None,
                    canonical_email=probe_email(marker, "owner"),
                    limit=10,
                    cursor=None,
                ),
                context=admin_context,
                authorize=authorize,
            )
            record(name="account_owner", ok=len(accounts) == 1)
            owner_snapshot = accounts[0] if accounts else None
            if owner_snapshot is not None:
                record(
                    name="account_owner_state",
                    ok=(
                        owner_snapshot.kind == "ordinary"
                        and owner_snapshot.state == "active"
                        and owner_snapshot.email_verified_at is not None
                    ),
                )
                self.stdout.write(f"row_kind=account id={owner_snapshot.id}")
            admin_snapshot = get_account_snapshot(admin_session["account_id"])
            reviewer_snapshot = get_account_snapshot(reviewer_session["account_id"])
            record(
                name="account_service_staff",
                ok=(
                    admin_snapshot.kind == "service"
                    and admin_snapshot.state == "active"
                    and reviewer_snapshot.kind == "service"
                    and reviewer_snapshot.state == "active"
                ),
            )

            owner_context = command_context(
                actor_account_id=owner_snapshot.id if owner_snapshot else None,
            )
            applications = list_own_seller_applications(context=owner_context) if owner_snapshot else ()
            record(name="seller_application", ok=len(applications) == 1)
            if len(applications) == 1:
                application = applications[0]
                self.stdout.write(f"row_kind=seller_application id={application.id}")
                versions = get_own_seller_application(
                    application_id=application.id,
                    context=owner_context,
                )[1]
                record(
                    name="seller_application_terminal",
                    ok=(
                        application.state == "approved"
                        and application.decision == "approve"
                        and len(versions) >= 1
                    ),
                )
                self.stdout.write(f"row_kind=seller_application_version count={len(versions)}")
                review_decision = get_own_seller_review_decision(
                    application_id=application.id,
                    version_number=application.current_version,
                    context=owner_context,
                )
                record(
                    name="seller_review_decision",
                    ok=(
                        review_decision is not None
                        and review_decision.application_id == application.id
                        and review_decision.version_number == application.current_version
                        and review_decision.decision == "approve"
                        and review_decision.reviewer_id == application.reviewer_id
                        and review_decision.reviewer_id
                        == reviewer_context.actor_account_id
                    ),
                )
                audits = query_audit_entries(
                    query=AuditQuery(
                        from_at=None,
                        to_at=None,
                        actor_id=None,
                        action="seller_onboarding.application_decided",
                        object_type="seller_application",
                        object_id=str(application.id),
                        result=None,
                        limit=10,
                        cursor=None,
                    ),
                    context=reviewer_context,
                    authorize=authorize,
                )
                record(name="audit_decision", ok=len(audits) == 1)
                outbox_message = get_outbox_message_snapshot(
                    idempotency_key=(
                        f"seller_onboarding.application_decision:"
                        f"{application.id}:{application.current_version}"
                    )
                )
                record(
                    name="outbox_application_decision",
                    ok=(
                        outbox_message is not None
                        and outbox_message.message_type
                        == "seller_onboarding.application_decision"
                    ),
                )
                profile = get_seller_profile_for_owner(context=owner_context)
                record(
                    name="seller_profile",
                    ok=(
                        profile is not None
                        and profile.application_id == application.id
                        and profile.state in ("active", "awaiting_owner_totp")
                    ),
                )
                if profile is not None:
                    self.stdout.write(f"row_kind=seller_profile id={profile.id}")
        except CommandError:
            raise
        except Exception:  # noqa: BLE001 - emit only a bounded safe failure code
            failures.append("probe_graph")

        if failures:
            raise CommandError("restore verification failed: " + "; ".join(failures[:10]))
        self.stdout.write(f"restore_verification_complete marker={marker}")

    def _check_migrations(self) -> None:
        loader = MigrationLoader(connection)
        missing = sorted(
            f"{app}:{name}"
            for app, name in loader.graph.leaf_nodes()
            if (app, name) not in loader.applied_migrations
        )
        for app, name in loader.graph.leaf_nodes():
            self.stdout.write(f"migration_leaf app={app} name={name}")
        if missing:
            raise CommandError("restore verification failed: missing migrations: " + ", ".join(missing))
