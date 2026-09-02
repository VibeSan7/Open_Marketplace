from uuid import uuid4

from django.db import models

MESSAGE_TYPE_MAX_LENGTH = 64
IDEMPOTENCY_KEY_MAX_LENGTH = 128
WORKER_ID_MAX_LENGTH = 128
SAFE_ERROR_MAX_LENGTH = 128


class OutboxMessage(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        MANUAL_REVIEW = "manual_review", "Manual review"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    message_type = models.CharField(max_length=MESSAGE_TYPE_MAX_LENGTH)
    format_version = models.PositiveSmallIntegerField()
    payload = models.JSONField()
    encrypted_delivery = models.BinaryField(null=True, editable=False)
    idempotency_key = models.CharField(
        max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
        unique=True,
    )
    created_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, db_index=True)
    claimed_at = models.DateTimeField(null=True)
    leased_by = models.CharField(max_length=WORKER_ID_MAX_LENGTH, null=True)
    lease_expires_at = models.DateTimeField(null=True, db_index=True)
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.PENDING,
        db_index=True,
    )
    last_safe_error = models.CharField(max_length=SAFE_ERROR_MAX_LENGTH, null=True)
    succeeded_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = (
            models.CheckConstraint(
                condition=models.Q(format_version=1),
                name="outbox_format_version_1",
            ),
        )
        indexes = (
            models.Index(
                fields=("state", "next_attempt_at", "created_at", "id"),
                name="outbox_ready_idx",
            ),
            models.Index(
                fields=("state", "lease_expires_at", "created_at", "id"),
                name="outbox_lease_idx",
            ),
        )
