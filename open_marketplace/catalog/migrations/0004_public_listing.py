from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0003_saved_product"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="public_listing",
            field=models.BooleanField(default=False),
        ),
    ]
