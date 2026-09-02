from uuid import uuid4

from django.db import models
from django.db.models import F, Q


class RoleAssignment(models.Model):
    class Role(models.TextChoices):
        SELLER_REVIEWER = "seller_reviewer", "Seller reviewer"
        SECURITY_ADMIN = "security_admin", "Security admin"

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account_id = models.UUIDField(db_index=True)
    role = models.CharField(max_length=32, choices=Role.choices)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    assigned_by_id = models.UUIDField(null=True)
    assigned_reason = models.TextField()
    active_from = models.DateTimeField()
    revoked_by_id = models.UUIDField(null=True)
    revoked_reason = models.TextField(null=True)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "access_role_assignment"
        constraints = (
            models.UniqueConstraint(
                fields=("account_id", "role"),
                condition=Q(state="active"),
                name="access_one_active_role_assignment",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="active",
                        revoked_by_id__isnull=True,
                        revoked_reason__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | Q(
                        state="revoked",
                        revoked_by_id__isnull=False,
                        revoked_reason__isnull=False,
                        revoked_at__isnull=False,
                    )
                ),
                name="access_role_assignment_revocation_state",
            ),
            models.CheckConstraint(
                condition=Q(revoked_at__isnull=True) | Q(revoked_at__gte=F("active_from")),
                name="access_role_assignment_revoked_after_start",
            ),
            models.CheckConstraint(
                condition=Q(role__in=("seller_reviewer", "security_admin")),
                name="access_role_assignment_known_role",
            ),
            models.CheckConstraint(
                condition=~Q(assigned_reason=""),
                name="access_role_assignment_reason_present",
            ),
            models.CheckConstraint(
                condition=Q(revoked_reason__isnull=True) | ~Q(revoked_reason=""),
                name="access_role_revocation_reason_present",
            ),
        )
        indexes = (
            models.Index(
                fields=("account_id", "state", "role"),
                name="access_role_owner_idx",
            ),
        )
