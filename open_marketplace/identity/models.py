from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from open_marketplace.identity.domain import canonicalize_email
from open_marketplace.identity.managers import AccountManager


class Account(AbstractBaseUser):
    class Kind(models.TextChoices):
        ORDINARY = "ordinary", "Ordinary"
        SERVICE = "service", "Service"

    class State(models.TextChoices):
        PENDING_EMAIL_VERIFICATION = (
            "pending_email_verification",
            "Pending email verification",
        )
        ACTIVE = "active", "Active"
        BLOCKED = "blocked", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.ORDINARY,
    )
    state = models.CharField(
        max_length=32,
        choices=State.choices,
        default=State.PENDING_EMAIL_VERIFICATION,
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    blocked_at = models.DateTimeField(null=True)
    blocked_by_id = models.UUIDField(null=True, editable=False)
    block_reason = models.TextField(null=True)
    block_audit_id = models.UUIDField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveBigIntegerField(default=1)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "identity_account"
        constraints = (
            models.CheckConstraint(
                condition=(
                    Q(
                        state="blocked",
                        blocked_at__isnull=False,
                        blocked_by_id__isnull=False,
                        block_reason__isnull=False,
                        block_audit_id__isnull=False,
                    )
                    | Q(
                        ~Q(state="blocked"),
                        blocked_at__isnull=True,
                        blocked_by_id__isnull=True,
                        block_reason__isnull=True,
                        block_audit_id__isnull=True,
                    )
                ),
                name="identity_account_block_metadata_state",
            ),
            models.CheckConstraint(
                condition=Q(block_reason__isnull=True) | ~Q(block_reason=""),
                name="identity_account_block_reason_present",
            ),
        )

    @property
    def is_active(self):
        return self.state == self.State.ACTIVE

    @property
    def is_staff(self):
        return self.kind == self.Kind.SERVICE and self.is_active

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        email_will_be_saved = (
            self._state.adding
            or update_fields is None
            or "email" in update_fields
        )
        if email_will_be_saved:
            self.email = canonicalize_email(self.email)

        kind_will_be_saved = not self._state.adding and (
            update_fields is None or "kind" in update_fields
        )
        if kind_will_be_saved:
            query = type(self)._base_manager
            database = kwargs.get("using") or self._state.db
            if database is not None:
                query = query.using(database)
            original_kind = query.values_list("kind", flat=True).get(pk=self.pk)
            if original_kind != self.kind:
                raise ValidationError({"kind": "Account kind is immutable."})

        super().save(*args, **kwargs)


class OneTimeToken(models.Model):
    class Purpose(models.TextChoices):
        EMAIL_VERIFICATION = "email_verification", "Email verification"
        PASSWORD_RESET = "password_reset", "Password reset"
        MANDATORY_TOTP_RECOVERY = (
            "mandatory_totp_recovery",
            "Mandatory TOTP recovery",
        )

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="one_time_tokens",
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    revoked_reason = models.CharField(max_length=64, null=True)

    class Meta:
        db_table = "identity_one_time_token"
        constraints = (
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="identity_token_expiry_after_create",
            ),
            models.CheckConstraint(
                condition=Q(used_at__isnull=True) | Q(revoked_at__isnull=True),
                name="identity_token_not_used_and_revoked",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revoked_at__isnull=True, revoked_reason__isnull=True)
                    | Q(revoked_at__isnull=False, revoked_reason__isnull=False)
                ),
                name="identity_token_revocation_pair",
            ),
        )
        indexes = (
            models.Index(
                fields=("account", "purpose", "created_at", "id"),
                name="identity_token_subject_idx",
            ),
            models.Index(
                fields=("purpose", "expires_at"),
                name="identity_token_expiry_idx",
            ),
        )


class AccountSession(models.Model):
    class RevocationReason(models.TextChoices):
        LOGOUT = "logout", "Logout"
        USER_REVOKED = "user_revoked", "User revoked"
        OTHER_SESSIONS_REVOKED = "other_sessions_revoked", "Other sessions revoked"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        PASSWORD_RESET = "password_reset", "Password reset"
        OPTIONAL_TOTP_DISABLED = "optional_totp_disabled", "Optional TOTP disabled"
        MANDATORY_TOTP_RECOVERED = (
            "mandatory_totp_recovered",
            "Mandatory TOTP recovered",
        )
        ACCOUNT_BLOCKED = "account_blocked", "Account blocked"
        ROLE_CHANGED = "role_changed", "Role changed"
        COMPROMISED = "compromised", "Compromised"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="account_sessions",
    )
    django_session_key = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )
    created_at = models.DateTimeField()
    last_activity_at = models.DateTimeField()
    absolute_expires_at = models.DateTimeField()
    reauthenticated_at = models.DateTimeField(null=True)
    device_label = models.CharField(max_length=200)
    revoked_at = models.DateTimeField(null=True)
    revoked_reason = models.CharField(
        max_length=64,
        choices=RevocationReason.choices,
        null=True,
    )

    class Meta:
        db_table = "identity_account_session"
        constraints = (
            models.CheckConstraint(
                condition=Q(absolute_expires_at__gt=F("created_at")),
                name="identity_session_expiry_after_create",
            ),
            models.CheckConstraint(
                condition=Q(last_activity_at__gte=F("created_at")),
                name="identity_session_activity_after_create",
            ),
            models.CheckConstraint(
                condition=Q(last_activity_at__lt=F("absolute_expires_at")),
                name="identity_session_activity_before_expiry",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revoked_at__isnull=True, revoked_reason__isnull=True)
                    | Q(revoked_at__isnull=False, revoked_reason__isnull=False)
                ),
                name="identity_session_revocation_pair",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revoked_reason__isnull=True)
                    | Q(
                        revoked_reason__in=(
                            "logout",
                            "user_revoked",
                            "other_sessions_revoked",
                            "password_changed",
                            "password_reset",
                            "optional_totp_disabled",
                            "mandatory_totp_recovered",
                            "account_blocked",
                            "role_changed",
                            "compromised",
                        )
                    )
                ),
                name="identity_session_revocation_reason",
            ),
        )
        indexes = (
            models.Index(
                fields=("account", "revoked_at", "absolute_expires_at"),
                name="identity_session_owner_idx",
            ),
        )


class TotpSetup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="totp_setups",
    )
    session = models.ForeignKey(
        AccountSession,
        on_delete=models.PROTECT,
        related_name="totp_setups",
        null=True,
    )
    recovery_token = models.ForeignKey(
        OneTimeToken,
        on_delete=models.PROTECT,
        related_name="totp_setups",
        null=True,
    )
    encrypted_secret = models.BinaryField(editable=False)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    invalidated_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "identity_totp_setup"
        constraints = (
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="identity_totp_setup_expiry_after_create",
            ),
            models.CheckConstraint(
                condition=Q(consumed_at__isnull=True) | Q(invalidated_at__isnull=True),
                name="identity_totp_setup_one_terminal_state",
            ),
            models.CheckConstraint(
                condition=Q(consumed_at__isnull=True) | Q(consumed_at__gte=F("created_at")),
                name="identity_totp_setup_consumed_after_create",
            ),
            models.CheckConstraint(
                condition=(
                    Q(invalidated_at__isnull=True)
                    | Q(invalidated_at__gte=F("created_at"))
                ),
                name="identity_totp_setup_invalidated_after_create",
            ),
            models.CheckConstraint(
                condition=(
                    Q(session__isnull=False, recovery_token__isnull=True)
                    | Q(session__isnull=True, recovery_token__isnull=False)
                ),
                name="identity_totp_setup_exactly_one_binding",
            ),
        )
        indexes = (
            models.Index(
                fields=("account", "consumed_at", "invalidated_at", "expires_at"),
                name="identity_totp_setup_owner_idx",
            ),
        )


class TotpCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="totp_credentials",
    )
    encrypted_secret = models.BinaryField(editable=False)
    confirmed_at = models.DateTimeField()
    last_accepted_counter = models.PositiveBigIntegerField()
    disabled_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "identity_totp_credential"
        constraints = (
            models.UniqueConstraint(
                fields=("account",),
                condition=Q(disabled_at__isnull=True),
                name="identity_one_active_totp_credential",
            ),
            models.CheckConstraint(
                condition=Q(disabled_at__isnull=True) | Q(disabled_at__gte=F("confirmed_at")),
                name="identity_totp_disabled_after_confirmed",
            ),
        )
        indexes = (
            models.Index(
                fields=("account", "disabled_at"),
                name="identity_totp_cred_owner_idx",
            ),
        )


class RecoveryCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recovery_codes",
    )
    set_id = models.UUIDField(editable=False)
    code_digest = models.CharField(max_length=64, unique=True, editable=False)
    issued_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "identity_recovery_code"
        constraints = (
            models.CheckConstraint(
                condition=Q(used_at__isnull=True) | Q(revoked_at__isnull=True),
                name="identity_recovery_not_used_and_revoked",
            ),
            models.CheckConstraint(
                condition=Q(used_at__isnull=True) | Q(used_at__gte=F("issued_at")),
                name="identity_recovery_used_after_issue",
            ),
            models.CheckConstraint(
                condition=Q(revoked_at__isnull=True) | Q(revoked_at__gte=F("issued_at")),
                name="identity_recovery_revoked_after_issue",
            ),
        )
        indexes = (
            models.Index(
                fields=("account", "set_id", "used_at", "revoked_at"),
                name="identity_recovery_owner_idx",
            ),
        )


class TotpRequirement(models.Model):
    class SourceType(models.TextChoices):
        STAFF_ROLE = "staff_role", "Staff role"
        SELLER_PROFILE = "seller_profile", "Seller profile"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="totp_requirements",
    )
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    source_id = models.UUIDField(editable=False)
    created_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "identity_totp_requirement"
        constraints = (
            models.UniqueConstraint(
                fields=("account", "source_type", "source_id"),
                name="identity_unique_totp_requirement_source",
            ),
            models.CheckConstraint(
                condition=Q(removed_at__isnull=True) | Q(removed_at__gte=F("created_at")),
                name="identity_totp_requirement_removed_after_create",
            ),
        )
        indexes = (
            models.Index(
                fields=("account", "removed_at"),
                name="identity_totp_req_owner_idx",
            ),
        )
