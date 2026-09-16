from django.db import models


class DemoContentInstallation(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    manifest_digest = models.CharField(max_length=64)
    counts = models.JSONField(default=dict)
    created_at = models.DateTimeField()
