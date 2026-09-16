import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from uuid import UUID

from django.conf import settings
from django.db import transaction

from open_marketplace.catalog.public import UNITS, stock_value, get_demo_offer_snapshot, get_demo_participant
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.seller_onboarding.public import get_public_sellers, get_seller_profile_for_owner

from .models import DemoInventory, DemoOrder, DemoOrderEvent


_UNAVAILABLE = "Заказ недоступен."
_QUANTITY_PATTERN = re.compile(r"[0-9]+(?:[.,][0-9]+)?\Z")
_ACTIONS = {"simulate_success", "simulate_decline", "hand_over", "complete", "cancel"}
_STATE_LABELS = dict(DemoOrder.State.choices)


def _enabled(*, write=False):
    if write and not settings.DEMO_ORDERS_ENABLED:
        raise PermissionDenied(_UNAVAILABLE)


def _uuid(value, message):
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise InputRejected(message)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise InputRejected(message) from None
    if str(parsed) != value:
        raise InputRejected(message)
    return parsed


def _ordinary_account(context):
    account = get_demo_participant(context=context)
    if account.kind != "ordinary":
        raise PermissionDenied(_UNAVAILABLE)
    return account


def _quantity(raw, unit):
    if isinstance(raw, str):
        text = raw.strip()
        if not _QUANTITY_PATTERN.fullmatch(text):
            raise InputRejected("Количество должно быть обычным десятичным числом.")
        places = 0 if unit == "pc" else 3
        fractional = text.replace(",", ".").partition(".")[2]
        if len(fractional) > places:
            raise InputRejected(f"Для единицы {UNITS[unit]} допустимо не более {places} дробных знаков.")
    elif isinstance(raw, Decimal):
        if not raw.is_finite() or raw.as_tuple().exponent < -(0 if unit == "pc" else 3):
            raise InputRejected("Количество содержит слишком много дробных знаков.")
    try:
        value = stock_value(raw, unit)
    except (InputRejected, InvalidOperation):
        raise InputRejected("Укажите корректное количество.") from None
    if value <= 0:
        raise InputRejected("Количество должно быть больше нуля.")
    return value


def _active_seller(context):
    profile = get_seller_profile_for_owner(context=context)
    if profile is not None and get_public_sellers(seller_ids=(profile.id,)):
        return profile
    return None


def _dto(order, *, viewer_role="buyer"):
    inventory = DemoInventory.objects.filter(variant_id=order.variant_id).values_list("quantity", flat=True).first()
    result = {
        "id": str(order.id),
        "intent_id": str(order.intent_id),
        "title": order.title,
        "variant_label": order.variant_label,
        "seller_name": order.seller_display_name,
        "seller_display_name": order.seller_display_name,
        "unit": order.unit,
        "unit_label": UNITS[order.unit],
        "unit_price": order.unit_price,
        "quantity": order.quantity,
        "total": order.total,
        "state": order.state,
        "state_label": _STATE_LABELS[order.state],
        "simulated_payment_status": order.simulated_payment_status,
        "simulated_remaining_quantity": (inventory or Decimal("0")) if viewer_role == "seller" else None,
        "events": tuple(
            {
                "state": event.state,
                "action": event.action,
                "occurred_at": event.occurred_at,
            }
            for event in order.events.all()
        ),
    }
    result["viewer_role"] = viewer_role
    actions = []
    if order.state == DemoOrder.State.PENDING and viewer_role == "buyer":
        actions.extend(("simulate_success", "simulate_decline"))
    if order.state in (DemoOrder.State.PENDING, DemoOrder.State.PAID):
        actions.append("cancel")
    if order.state == DemoOrder.State.PAID and viewer_role == "seller":
        actions.append("hand_over")
    if order.state == DemoOrder.State.HANDED_OVER and viewer_role == "buyer":
        actions.append("complete")
    result["available_actions"] = tuple(actions)
    result["payment_label"] = dict(DemoOrder.PaymentStatus.choices)[order.simulated_payment_status]
    for event in result["events"]:
        event["state_label"] = _STATE_LABELS[event["state"]]
    return result


def _find_owned_order(order_id, context):
    account = _ordinary_account(context)
    order = DemoOrder.objects.filter(pk=order_id).first()
    if order is None or (order.buyer_id != account.id and order.seller_account_id != account.id):
        raise PermissionDenied(_UNAVAILABLE)
    if order.seller_account_id == account.id:
        profile = _active_seller(context)
        if profile is None or profile.id != order.seller_profile_id:
            raise PermissionDenied(_UNAVAILABLE)
    return order, account


def _record(order, *, action, context):
    DemoOrderEvent.objects.create(
        order=order,
        state=order.state,
        action=action,
        actor_id=context.actor_account_id,
        occurred_at=context.now,
    )


def create_order(*, variant_id, quantity, intent_id, context):
    _enabled(write=True)
    variant_id = _uuid(variant_id, "Неверный идентификатор предложения.")
    intent_id = _uuid(intent_id, "Неверный идентификатор намерения.")
    account = _ordinary_account(context)
    with transaction.atomic():
        account = get_demo_participant(context=context, lock=True)
        existing = DemoOrder.objects.filter(buyer_id=account.id, intent_id=intent_id).first()
        if existing is not None:
            if existing.variant_id != variant_id:
                raise ConcurrentConflict("Это намерение уже связано с другим заказом.")
            expected_quantity = _quantity(quantity, existing.unit)
            if existing.quantity != expected_quantity:
                raise ConcurrentConflict("Это намерение уже связано с другим количеством.")
            return _dto(existing)

        offer = get_demo_offer_snapshot(variant_id=variant_id, context=context, lock=True)
        if offer["seller_account_id"] == account.id:
            raise PermissionDenied(_UNAVAILABLE)
        order_quantity = _quantity(quantity, offer["unit"])
        inventory = DemoInventory.objects.filter(variant_id=variant_id).first()
        if inventory is None:
            inventory = DemoInventory.objects.create(
                variant_id=variant_id,
                quantity=offer["initial_quantity"],
                initialized_at=context.now,
            )
        else:
            inventory = DemoInventory.objects.select_for_update().get(pk=inventory.id)
        if inventory.quantity < order_quantity:
            raise InputRejected("В симулированном остатке недостаточно единиц.")
        with localcontext() as precision:
            precision.prec = DemoOrder._meta.get_field("total").max_digits
            total = (offer["unit_price"] * order_quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total >= Decimal("1e38"):
            raise InputRejected("Сумма заказа выходит за допустимый предел.")
        inventory.quantity -= order_quantity
        inventory.save(update_fields=("quantity",))
        order = DemoOrder.objects.create(
            intent_id=intent_id,
            buyer_id=account.id,
            seller_account_id=offer["seller_account_id"],
            seller_profile_id=offer["seller_profile_id"],
            product_id=offer["product_id"],
            variant_id=offer["variant_id"],
            title=offer["title"],
            variant_label=offer["variant_label"],
            seller_display_name=offer["seller_display_name"],
            unit=offer["unit"],
            unit_price=offer["unit_price"],
            quantity=order_quantity,
            total=total,
            state=DemoOrder.State.PENDING,
            simulated_payment_status=DemoOrder.PaymentStatus.PENDING,
            created_at=context.now,
            updated_at=context.now,
        )
        _record(order, action="created", context=context)
        return _dto(order)


def get_offer_preview(*, variant_id, context):
    variant_id = _uuid(variant_id, "Неверный идентификатор предложения.")
    account = _ordinary_account(context)
    offer = get_demo_offer_snapshot(variant_id=variant_id, context=context)
    if offer["seller_account_id"] == account.id:
        raise PermissionDenied(_UNAVAILABLE)
    return {
        "title": offer["title"],
        "variant_label": offer["variant_label"],
        "seller_name": offer["seller_display_name"],
        "unit": offer["unit"],
        "unit_label": UNITS[offer["unit"]],
        "unit_price": offer["unit_price"],
        "simulated_remaining_quantity": None,
        "simulation_notice": "Остаток симуляции создаётся при первом заказе и не является реальным остатком.",
    }


def get_order(*, order_id, context):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    order, account = _find_owned_order(order_id, context)
    role = "buyer" if order.buyer_id == account.id else "seller"
    return _dto(order, viewer_role=role)


def list_orders(*, context):
    account = _ordinary_account(context)
    orders = DemoOrder.objects.filter(buyer_id=account.id)
    profile = _active_seller(context)
    if profile is not None:
        orders = DemoOrder.objects.filter(buyer_id=account.id) | DemoOrder.objects.filter(seller_account_id=account.id)
    return tuple(_dto(order, viewer_role="buyer" if order.buyer_id == account.id else "seller")
                 for order in orders.distinct().prefetch_related("events"))


def _same_action(order, action):
    return (
        (action == "simulate_success" and order.state == DemoOrder.State.PAID)
        or (
            action == "simulate_decline"
            and order.state == DemoOrder.State.PENDING
            and order.simulated_payment_status == DemoOrder.PaymentStatus.DECLINED
        )
        or (action == "hand_over" and order.state == DemoOrder.State.HANDED_OVER)
        or (action == "complete" and order.state == DemoOrder.State.COMPLETED)
        or (action == "cancel" and order.state == DemoOrder.State.CANCELLED)
    )


def act_on_order(*, order_id, action, context):
    _enabled(write=True)
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    if action not in _ACTIONS:
        raise InputRejected("Неизвестное действие заказа.")
    account = _ordinary_account(context)
    with transaction.atomic():
        order = DemoOrder.objects.select_for_update().filter(pk=order_id).first()
        if order is None or (order.buyer_id != account.id and order.seller_account_id != account.id):
            raise PermissionDenied(_UNAVAILABLE)
        is_buyer = order.buyer_id == account.id
        if not is_buyer:
            profile = _active_seller(context)
            if profile is None or profile.id != order.seller_profile_id:
                raise PermissionDenied(_UNAVAILABLE)
        if action in {"simulate_success", "simulate_decline", "complete"} and not is_buyer:
            raise PermissionDenied(_UNAVAILABLE)
        if action == "hand_over" and is_buyer:
            raise PermissionDenied(_UNAVAILABLE)
        if _same_action(order, action):
            return _dto(order, viewer_role="buyer" if is_buyer else "seller")
        if action in {"simulate_success", "simulate_decline"} and order.state != DemoOrder.State.PENDING:
            raise ConcurrentConflict("Переход заказа в этом состоянии невозможен.")
        if action == "hand_over" and order.state != DemoOrder.State.PAID:
            raise ConcurrentConflict("Переход заказа в этом состоянии невозможен.")
        if action == "complete" and order.state != DemoOrder.State.HANDED_OVER:
            raise ConcurrentConflict("Переход заказа в этом состоянии невозможен.")
        if action == "cancel" and order.state not in {DemoOrder.State.PENDING, DemoOrder.State.PAID}:
            raise ConcurrentConflict("Переход заказа в этом состоянии невозможен.")
        if action == "simulate_success":
            order.state = DemoOrder.State.PAID
            order.simulated_payment_status = DemoOrder.PaymentStatus.SUCCESS
        elif action == "simulate_decline":
            order.simulated_payment_status = DemoOrder.PaymentStatus.DECLINED
        elif action == "hand_over":
            order.state = DemoOrder.State.HANDED_OVER
        elif action == "complete":
            order.state = DemoOrder.State.COMPLETED
        elif action == "cancel":
            inventory = DemoInventory.objects.select_for_update().get(variant_id=order.variant_id)
            if order.inventory_returned_at is None:
                inventory.quantity += order.quantity
                inventory.save(update_fields=("quantity",))
                order.inventory_returned_at = context.now
            order.state = DemoOrder.State.CANCELLED
            if order.simulated_payment_status == DemoOrder.PaymentStatus.SUCCESS:
                order.simulated_payment_status = DemoOrder.PaymentStatus.REFUNDED
        order.updated_at = context.now
        order.save(update_fields=("state", "simulated_payment_status", "inventory_returned_at", "updated_at"))
        _record(order, action=action, context=context)
        return _dto(order, viewer_role="buyer" if is_buyer else "seller")


__all__ = ("create_order", "get_offer_preview", "get_order", "list_orders", "act_on_order")
