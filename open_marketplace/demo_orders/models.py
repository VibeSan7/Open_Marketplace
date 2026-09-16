from uuid import uuid4

from django.db import models

class DemoInventory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    variant = models.OneToOneField("catalog.Variant", on_delete=models.PROTECT, related_name="demo_inventory")
    quantity = models.DecimalField(max_digits=40, decimal_places=3)
    initialized_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_inventory"


class Cart(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    buyer_id = models.UUIDField(unique=True, db_index=True)
    revision = models.PositiveBigIntegerField(default=0)
    intent_id = models.UUIDField(default=uuid4, unique=True)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_cart"


class CartItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant_id = models.UUIDField(db_index=True)
    product_id = models.UUIDField()
    title = models.CharField(max_length=512)
    variant_label = models.CharField(max_length=512)
    seller_name = models.CharField(max_length=256)
    seller_id = models.UUIDField()
    unit = models.CharField(max_length=2)
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    confirmed_unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_cart_item"
        constraints = (
            models.UniqueConstraint(
                fields=("cart", "variant_id"),
                name="demo_orders_cart_variant_unique",
            ),
        )
        ordering = ("seller_name", "variant_id", "id")


class CartCheckoutReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.PROTECT, related_name="checkout_receipts")
    intent_id = models.UUIDField()
    revision = models.PositiveBigIntegerField()
    order_ids = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "demo_orders_cart_checkout_receipt"
        constraints = (
            models.UniqueConstraint(
                fields=("cart", "intent_id"),
                name="demo_orders_cart_intent_unique",
            ),
        )


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
