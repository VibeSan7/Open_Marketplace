import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SellerApplication",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("applicant_id", models.UUIDField(db_index=True)),
                ("state", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("under_review", "Under review"), ("changes_requested", "Changes requested"), ("approved", "Approved"), ("rejected", "Rejected"), ("withdrawn", "Withdrawn")], default="draft", max_length=32)),
                ("current_version", models.PositiveIntegerField(default=0)),
                ("reviewer_id", models.UUIDField(null=True)),
                ("decision", models.CharField(max_length=32, null=True)),
                ("reason", models.TextField(null=True)),
                ("created_at", models.DateTimeField()),
                ("submitted_at", models.DateTimeField(null=True)),
                ("business_form", models.CharField(blank=True, max_length=32, null=True)),
                ("display_name", models.CharField(blank=True, max_length=256, null=True)),
                ("official_name", models.CharField(blank=True, max_length=256, null=True)),
                ("registration_identifier", models.CharField(blank=True, max_length=128, null=True)),
                ("contact_email", models.EmailField(blank=True, max_length=254, null=True)),
                ("test_data_attested", models.BooleanField(default=False)),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.CreateModel(
            name="SellerApplicationVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version_number", models.PositiveIntegerField()),
                ("business_form", models.CharField(max_length=32)),
                ("display_name", models.CharField(max_length=256)),
                ("official_name", models.CharField(max_length=256)),
                ("registration_identifier", models.CharField(max_length=128)),
                ("contact_email", models.EmailField(max_length=254)),
                ("test_data_attested", models.BooleanField()),
                ("submitted_at", models.DateTimeField()),
                ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="seller_onboarding.sellerapplication")),
            ],
            options={"ordering": ("version_number", "id")},
        ),
        migrations.AddConstraint(
            model_name="sellerapplication",
            constraint=models.UniqueConstraint(condition=models.Q(("state__in", ("draft", "submitted", "under_review", "changes_requested"))), fields=("applicant_id",), name="seller_one_unfinished_application"),
        ),
        migrations.AddConstraint(
            model_name="sellerapplicationversion",
            constraint=models.UniqueConstraint(fields=("application", "version_number"), name="seller_application_version_number_unique"),
        ),
    ]
