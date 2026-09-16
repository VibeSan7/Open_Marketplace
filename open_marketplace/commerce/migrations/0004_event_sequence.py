from django.db import migrations, models


def backfill_sequences(apps, schema_editor):
    event_model = apps.get_model("commerce", "FulfillmentEvent")
    shipment_ids = (
        event_model.objects.order_by()
        .values_list("shipment_id", flat=True)
        .distinct()
    )
    for shipment_id in shipment_ids:
        events = list(
            event_model.objects.filter(shipment_id=shipment_id).order_by("occurred_at", "id")
        )
        for sequence, event in enumerate(events, start=1):
            event.sequence = sequence
        event_model.objects.bulk_update(events, ["sequence"])


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0003_fulfillment"),
    ]

    operations = [
        migrations.AddField(
            model_name="fulfillmentevent",
            name="sequence",
            field=models.PositiveBigIntegerField(null=True),
        ),
        migrations.RunPython(backfill_sequences, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="fulfillmentevent",
            name="sequence",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="fulfillmentevent",
            constraint=models.UniqueConstraint(
                fields=("shipment", "sequence"),
                name="commerce_fulfillment_event_sequence_unique",
            ),
        ),
    ]
