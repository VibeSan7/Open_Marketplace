import uuid

from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0001_initial"),
        ("identity", "0005_account_administration_and_totp_recovery"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffInvitation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254)),
                ("role", models.CharField(choices=[("seller_reviewer", "Seller reviewer"), ("security_admin", "Security admin")], max_length=32)),
                ("created_by_id", models.UUIDField(null=True)),
                ("token_digest", models.CharField(editable=False, max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("accepted_at", models.DateTimeField(null=True)),
                ("revoked_at", models.DateTimeField(null=True)),
                ("revoked_by_id", models.UUIDField(null=True)),
                ("revoked_reason", models.TextField(null=True)),
            ],
            options={
                "db_table": "access_staff_invitation",
                "indexes": [
                    models.Index(fields=["email", "role", "expires_at"], name="access_invitation_live_idx"),
                    models.Index(fields=["created_at", "id"], name="access_invitation_cursor_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(condition=Q(expires_at__gt=F("created_at")), name="access_invitation_expiry_after_create"),
                    models.CheckConstraint(condition=Q(accepted_at__isnull=True) | Q(revoked_at__isnull=True), name="access_invitation_one_terminal_state"),
                    models.CheckConstraint(condition=Q(revoked_at__isnull=True, revoked_by_id__isnull=True, revoked_reason__isnull=True) | Q(revoked_at__isnull=False, revoked_by_id__isnull=False, revoked_reason__isnull=False), name="access_invitation_revocation_pair"),
                    models.CheckConstraint(condition=Q(revoked_reason__isnull=True) | ~Q(revoked_reason=""), name="access_invitation_revocation_reason_present"),
                    models.CheckConstraint(condition=Q(role__in=("seller_reviewer", "security_admin")), name="access_invitation_known_role"),
                ],
            },
        ),
        migrations.CreateModel(
            name="StaffInvitationAcceptance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_digest", models.CharField(editable=False, max_length=64)),
                ("account_id", models.UUIDField()),
                ("totp_setup_id", models.UUIDField(editable=False, null=True)),
                ("created_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(null=True)),
                ("invalidated_at", models.DateTimeField(null=True)),
                ("invitation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acceptances", to="access.staffinvitation")),
            ],
            options={
                "db_table": "access_staff_invitation_acceptance",
                "indexes": [models.Index(fields=["invitation", "consumed_at", "invalidated_at"], name="access_inv_accept_live_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=("invitation", "token_digest"), name="access_invitation_acceptance_token_unique"),
                    models.CheckConstraint(condition=Q(consumed_at__isnull=True) | Q(invalidated_at__isnull=True), name="access_invitation_acceptance_one_terminal_state"),
                ],
            },
        ),
    ]
