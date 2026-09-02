from uuid import uuid4

from django.db import models

ACTION_MAX_LENGTH = 64
OBJECT_TYPE_MAX_LENGTH = 64
OBJECT_ID_MAX_LENGTH = 128
RESULT_MAX_LENGTH = 64
EFFECTIVE_ROLE_MAX_LENGTH = 64


class AuditMutationForbidden(RuntimeError):
    pass


class AuditEntryQuerySet(models.QuerySet):
    def _reject_mutation(self):
        raise AuditMutationForbidden("Audit entries are append-only.")

    def create(self, **kwargs):
        self._reject_mutation()

    def get_or_create(self, defaults=None, **kwargs):
        self._reject_mutation()

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        self._reject_mutation()

    def bulk_create(self, objs, **kwargs):
        self._reject_mutation()

    def bulk_update(self, objs, fields, batch_size=None):
        self._reject_mutation()

    def update(self, **kwargs):
        self._reject_mutation()

    def delete(self):
        self._reject_mutation()


class AuditEntryManager(models.Manager.from_queryset(AuditEntryQuerySet)):
    use_in_migrations = True

    def append(self, **values):
        entry = self.model(**values)
        models.Model.save(entry, force_insert=True, using=self.db)
        return entry


class AuditEntry(models.Model):
    class Source(models.TextChoices):
        HTML = "html", "HTML"
        ADMIN = "admin", "Admin"
        COMMAND = "command", "Command"
        WORKER = "worker", "Worker"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    occurred_at = models.DateTimeField(db_index=True)
    actor_id = models.UUIDField(null=True, db_index=True)
    effective_role = models.CharField(
        max_length=EFFECTIVE_ROLE_MAX_LENGTH,
        null=True,
    )
    action = models.CharField(max_length=ACTION_MAX_LENGTH, db_index=True)
    object_type = models.CharField(max_length=OBJECT_TYPE_MAX_LENGTH, db_index=True)
    object_id = models.CharField(max_length=OBJECT_ID_MAX_LENGTH, db_index=True)
    result = models.CharField(max_length=RESULT_MAX_LENGTH, db_index=True)
    reason = models.TextField(null=True)
    request_id = models.UUIDField(db_index=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    source = models.CharField(max_length=16, choices=Source.choices)

    objects = AuditEntryManager()

    class Meta:
        ordering = ("-occurred_at", "-id")
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = (
            models.Index(
                fields=("object_type", "object_id", "-occurred_at", "-id"),
                name="audit_object_history_idx",
            ),
        )

    def save(self, *args, **kwargs):
        raise AuditMutationForbidden("Audit entries are append-only.")

    def delete(self, *args, **kwargs):
        raise AuditMutationForbidden("Audit entries are append-only.")
