from uuid import uuid4

from django.db import models

class DemoInventory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    variant = models.OneToOneField("catalog.Variant", on_delete=models.PROTECT, related_name="demo_inventory")
    quantity = models.DecimalField(max_digits=40, decimal_places=3)
    initialized_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_inventory"


class DemoOrder(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Ожидает симуляции"
        PAID = "paid", "Оплачено в симуляции"
        HANDED_OVER = "handed_over", "Передано в симуляции"
        COMPLETED = "completed", "Завершено в симуляции"
        CANCELLED = "cancelled", "Отменено в симуляции"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Ожидает симуляции"
        SUCCESS = "success", "Успешно в симуляции"
        DECLINED = "declined", "Отклонено в симуляции"
        REFUNDED = "refunded", "Возвращено в симуляции"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    intent_id = models.UUIDField()
    buyer_id = models.UUIDField(db_index=True)
    seller_account_id = models.UUIDField(db_index=True)
    seller_profile_id = models.UUIDField()
    product_id = models.UUIDField()
    variant_id = models.UUIDField(db_index=True)
    title = models.CharField(max_length=512)
    variant_label = models.CharField(max_length=512)
    seller_display_name = models.CharField(max_length=256)
    unit = models.CharField(max_length=2)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    total = models.DecimalField(max_digits=40, decimal_places=2)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    simulated_payment_status = models.CharField(
        max_length=16,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    inventory_returned_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_order"
        constraints = (
            models.UniqueConstraint(
                fields=("buyer_id", "intent_id"),
                name="demo_orders_buyer_intent_unique",
            ),
        )
        ordering = ("-created_at", "-id")


class DemoOrderEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    order = models.ForeignKey(DemoOrder, on_delete=models.PROTECT, related_name="events")
    state = models.CharField(max_length=16)
    action = models.CharField(max_length=32)
    actor_id = models.UUIDField()
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_order_event"
        ordering = ("occurred_at", "id")
