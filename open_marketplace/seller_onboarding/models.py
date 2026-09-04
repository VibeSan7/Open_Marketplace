from uuid import uuid4

from django.db import models


class SellerApplication(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    applicant_id = models.UUIDField(db_index=True)
    state = models.CharField(max_length=32, choices=State.choices, default=State.DRAFT)
    current_version = models.PositiveIntegerField(default=0)
    reviewer_id = models.UUIDField(null=True)
    decision = models.CharField(max_length=32, null=True)
    reason = models.TextField(null=True)
    created_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True)
    business_form = models.CharField(max_length=32, null=True, blank=True)
    display_name = models.CharField(max_length=256, null=True, blank=True)
    official_name = models.CharField(max_length=256, null=True, blank=True)
    registration_identifier = models.CharField(max_length=128, null=True, blank=True)
    contact_email = models.EmailField(max_length=254, null=True, blank=True)
    test_data_attested = models.BooleanField(default=False)

    class Meta:
        ordering = ("created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("applicant_id",),
                condition=models.Q(
                    state__in=(
                        "draft",
                        "submitted",
                        "under_review",
                        "changes_requested",
                    )
                ),
                name="seller_one_unfinished_application",
            ),
        )


class SellerApplicationVersionMutationForbidden(RuntimeError):
    pass


class SellerApplicationVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise SellerApplicationVersionMutationForbidden(
            "Submitted application versions are immutable."
        )

    def delete(self):
        raise SellerApplicationVersionMutationForbidden(
            "Submitted application versions are immutable."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise SellerApplicationVersionMutationForbidden(
            "Submitted application versions are immutable."
        )

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        raise SellerApplicationVersionMutationForbidden(
            "Submitted application versions are immutable."
        )


class SellerApplicationVersionManager(models.Manager.from_queryset(SellerApplicationVersionQuerySet)):
    pass


class SellerApplicationVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(
        SellerApplication,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    business_form = models.CharField(max_length=32)
    display_name = models.CharField(max_length=256)
    official_name = models.CharField(max_length=256)
    registration_identifier = models.CharField(max_length=128)
    contact_email = models.EmailField(max_length=254)
    test_data_attested = models.BooleanField()
    submitted_at = models.DateTimeField()

    objects = SellerApplicationVersionManager()

    class Meta:
        ordering = ("version_number", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("application", "version_number"),
                name="seller_application_version_number_unique",
            ),
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise SellerApplicationVersionMutationForbidden(
                "Submitted application versions are immutable."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise SellerApplicationVersionMutationForbidden(
            "Submitted application versions are immutable."
        )


class SellerReviewDecision(models.Model):
    class Decision(models.TextChoices):
        REQUEST_CHANGES = "request_changes", "Request changes"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(
        SellerApplication,
        on_delete=models.PROTECT,
        related_name="review_decisions",
    )
    version_number = models.PositiveIntegerField()
    decision = models.CharField(max_length=32, choices=Decision.choices)
    reason = models.TextField()
    reviewer_id = models.UUIDField()
    occurred_at = models.DateTimeField()
    request_id = models.UUIDField(db_index=True)

    class Meta:
        ordering = ("occurred_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("application", "version_number"),
                name="seller_review_decision_version_unique",
            ),
        )


class SellerProfile(models.Model):
    class State(models.TextChoices):
        AWAITING_OWNER_TOTP = "awaiting_owner_totp", "Awaiting owner TOTP"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner_id = models.UUIDField(unique=True)
    application = models.ForeignKey(
        SellerApplication,
        on_delete=models.PROTECT,
        related_name="seller_profiles",
    )
    approved_version = models.PositiveIntegerField()
    state = models.CharField(max_length=32, choices=State.choices)
    restriction_reason = models.TextField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ("created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("application", "approved_version"),
                name="seller_profile_application_version_unique",
            ),
        )
