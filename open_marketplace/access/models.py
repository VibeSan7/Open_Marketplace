from uuid import uuid4

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class StaffInvitation(models.Model):
    class Role(models.TextChoices):
        SELLER_REVIEWER = "seller_reviewer", "Seller reviewer"
        SECURITY_ADMIN = "security_admin", "Security admin"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    email = models.EmailField(max_length=254)
    role = models.CharField(max_length=32, choices=Role.choices)
    created_by_id = models.UUIDField(null=True)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    revoked_by_id = models.UUIDField(null=True)
    revoked_reason = models.TextField(null=True)

    @property
    def state(self):
        if self.revoked_at is not None:
            return "revoked"
        if self.accepted_at is not None:
            return "accepted"
        if timezone.now() >= self.expires_at:
            return "expired"
        return "pending"

    class Meta:
        db_table = "access_staff_invitation"
        constraints = (
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="access_invitation_expiry_after_create",
            ),
            models.CheckConstraint(
                condition=Q(accepted_at__isnull=True) | Q(revoked_at__isnull=True),
                name="access_invitation_one_terminal_state",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revoked_at__isnull=True, revoked_by_id__isnull=True, revoked_reason__isnull=True)
                    | Q(revoked_at__isnull=False, revoked_by_id__isnull=False, revoked_reason__isnull=False)
                ),
                name="access_invitation_revocation_pair",
            ),
            models.CheckConstraint(
                condition=Q(revoked_reason__isnull=True) | ~Q(revoked_reason=""),
                name="access_invitation_revocation_reason_present",
            ),
            models.CheckConstraint(
                condition=Q(role__in=("seller_reviewer", "security_admin")),
                name="access_invitation_known_role",
            ),
        )
        indexes = (
            models.Index(fields=("email", "role", "expires_at"), name="access_invitation_live_idx"),
            models.Index(fields=("created_at", "id"), name="access_invitation_cursor_idx"),
        )


class StaffInvitationAcceptance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    invitation = models.ForeignKey(
        StaffInvitation,
        on_delete=models.PROTECT,
        related_name="acceptances",
    )
    token_digest = models.CharField(max_length=64, editable=False)
    account_id = models.UUIDField()
    totp_setup_id = models.UUIDField(null=True, editable=False)
    created_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    invalidated_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "access_staff_invitation_acceptance"
        constraints = (
            models.UniqueConstraint(
                fields=("invitation", "token_digest"),
                name="access_invitation_acceptance_token_unique",
            ),
            models.CheckConstraint(
                condition=Q(consumed_at__isnull=True) | Q(invalidated_at__isnull=True),
                name="access_invitation_acceptance_one_terminal_state",
            ),
        )
        indexes = (
            models.Index(
                fields=("invitation", "consumed_at", "invalidated_at"),
                name="access_inv_accept_live_idx",
            ),
        )


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
