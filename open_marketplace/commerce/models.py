from uuid import uuid4

from django.db import models


class CommerceOrder(models.Model):
    class State(models.TextChoices):
        AWAITING_PAYMENT = "awaiting_payment", "Ожидает подтверждения оплаты"
        PAID = "paid", "Оплачено"
        CANCELLED = "cancelled", "Отменено"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    intent_id = models.UUIDField(unique=True, editable=False)
    reservation_id = models.UUIDField(unique=True, editable=False)
    buyer_id = models.UUIDField(db_index=True, editable=False)
    lines = models.JSONField()
    total = models.DecimalField(max_digits=40, decimal_places=2)
    currency = models.CharField(max_length=3, default="RUB")
    state = models.CharField(
        max_length=24,
        choices=State.choices,
        default=State.AWAITING_PAYMENT,
        db_index=True,
    )
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = (
            models.CheckConstraint(
                condition=models.Q(total__gte=0),
                name="commerce_order_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(currency="RUB"),
                name="commerce_order_currency_rub",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=("awaiting_payment", "paid", "cancelled")
                ),
                name="commerce_order_state_valid",
            ),
        )


class CommerceOrderEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    order = models.ForeignKey(
        CommerceOrder,
        on_delete=models.PROTECT,
        related_name="events",
    )
    state = models.CharField(max_length=24)
    action = models.CharField(max_length=32)
    actor_id = models.UUIDField(null=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("occurred_at", "id")


class PaymentIntent(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Ожидает оплаты"
        AUTHORIZED = "authorized", "Авторизовано"
        CONFIRMED = "confirmed", "Подтверждено"
        REJECTED = "rejected", "Отклонено"
        REVERSED = "reversed", "Отменено провайдером"
        REFUNDED = "refunded", "Возвращено провайдером"
        PARTIAL_REFUNDED = "partial_refund", "Частично возвращено провайдером"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    order = models.OneToOneField(
        CommerceOrder,
        on_delete=models.PROTECT,
        related_name="payment_intent",
    )
    provider = models.CharField(max_length=32, default="tbank_safe_deal")
    provider_order_id = models.CharField(max_length=64, unique=True)
    deal_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    payment_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    amount_kopecks = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="RUB")
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = (
            models.CheckConstraint(
                condition=models.Q(provider="tbank_safe_deal"),
                name="payment_intent_provider_tbank",
            ),
            models.CheckConstraint(
                condition=models.Q(currency="RUB"),
                name="payment_intent_currency_rub",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_kopecks__gt=0),
                name="payment_intent_amount_positive",
            ),
        )


class PaymentEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    payment = models.ForeignKey(
        PaymentIntent,
        on_delete=models.PROTECT,
        related_name="events",
    )
    fingerprint = models.CharField(max_length=64, unique=True)
    provider_status = models.CharField(max_length=32)
    amount_kopecks = models.PositiveBigIntegerField()
    payload = models.JSONField()
    received_at = models.DateTimeField()

    class Meta:
        ordering = ("received_at", "id")


class FulfillmentShipment(models.Model):
    class DeliveryMode(models.TextChoices):
        CDEK = "cdek", "СДЭК"
        SELLER = "seller", "Доставка продавцом"

    class State(models.TextChoices):
        PENDING = "pending", "Ожидает планирования"
        READY = "ready", "Готово к передаче"
        IN_TRANSIT = "in_transit", "В пути"
        DELIVERED = "delivered", "Доставлено"
        CANCELLED = "cancelled", "Отменено"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    order = models.ForeignKey(
        CommerceOrder,
        on_delete=models.PROTECT,
        related_name="shipments",
    )
    seller_account_id = models.UUIDField(db_index=True)
    seller_profile_id = models.UUIDField(db_index=True)
    delivery_mode = models.CharField(max_length=6, choices=DeliveryMode.choices)
    client_reference = models.CharField(max_length=30, unique=True)
    lines = models.JSONField()
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("order", "seller_account_id"),
                name="commerce_one_shipment_per_seller",
            ),
        )
        ordering = ("seller_account_id", "id")


class FulfillmentEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    shipment = models.ForeignKey(
        FulfillmentShipment,
        on_delete=models.PROTECT,
        related_name="events",
    )
    state = models.CharField(max_length=16)
    action = models.CharField(max_length=32)
    sequence = models.PositiveBigIntegerField()
    actor_id = models.UUIDField(null=True)
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("shipment", "sequence"),
                name="commerce_fulfillment_event_sequence_unique",
            ),
        )
        ordering = ("shipment_id", "sequence")


class CommerceCart(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    buyer_id = models.UUIDField(unique=True, db_index=True)
    revision = models.PositiveBigIntegerField(default=0)
    intent_id = models.UUIDField(unique=True)
    items = models.JSONField(default=list)
    updated_at = models.DateTimeField()


class CommerceCartCheckoutReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    cart = models.ForeignKey(CommerceCart, on_delete=models.PROTECT, related_name="checkout_receipts")
    intent_id = models.UUIDField()
    revision = models.PositiveBigIntegerField()
    order_ids = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("cart", "intent_id"),
                name="commerce_cart_intent_unique",
            ),
        )
