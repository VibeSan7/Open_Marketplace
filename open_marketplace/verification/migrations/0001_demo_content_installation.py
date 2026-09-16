from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="DemoContentInstallation",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("manifest_digest", models.CharField(max_length=64)),
                ("counts", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField()),
            ],
        ),
    ]
