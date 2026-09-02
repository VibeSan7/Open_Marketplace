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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveBigIntegerField(default=1)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "identity_account"

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
