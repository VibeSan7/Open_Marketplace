from uuid import uuid4

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import models

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
