import base64
from copy import deepcopy
from uuid import UUID, uuid5

from django.db import transaction
from django.utils import timezone

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied

from .models import CommerceOrder, FulfillmentEvent, FulfillmentShipment


_REFERENCE_NAMESPACE = UUID("c8a4e5cc-1fc2-4a1c-8f1d-9a8e5b6d2c40")
_UNAVAILABLE = "Заказ недоступен."
_MODES = frozenset(FulfillmentShipment.DeliveryMode.values)


def _uuid(value, message):
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise InputRejected(message)
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError):
        raise InputRejected(message) from None
    if str(parsed) != value:
        raise InputRejected(message)
    return parsed


def _seller_groups(lines):
    if not isinstance(lines, list) or not lines:
        raise InputRejected("В заказе нет позиций для отгрузки.")
    groups = {}
    for line in lines:
        if not isinstance(line, dict):
            raise InputRejected("Снимок заказа содержит неверную позицию.")
        try:
            seller_account_id = _uuid(line["seller_account_id"], "Неверный продавец в заказе.")
            seller_profile_id = _uuid(line["seller_profile_id"], "Неверный профиль продавца в заказе.")
        except KeyError:
            raise InputRejected("Снимок заказа не содержит продавца.") from None
        key = str(seller_account_id)
        group = groups.setdefault(
            key,
            {"seller_account_id": key, "seller_profile_id": str(seller_profile_id), "lines": []},
        )
        if group["seller_profile_id"] != str(seller_profile_id):
            raise InputRejected("Один продавец связан с несколькими профилями.")
        group["lines"].append(deepcopy(line))
    return tuple(groups[key] for key in sorted(groups))


def _delivery_modes(value, seller_ids):
    if type(value) is not dict:
        raise InputRejected("Укажите способ доставки для каждого продавца.")
    normalized = {}
    for raw_seller_id, mode in value.items():
        seller_id = str(_uuid(raw_seller_id, "Неверный продавец в способах доставки."))
        if mode not in _MODES:
            raise InputRejected("Указан неподдерживаемый способ доставки.")
        if seller_id in normalized:
            raise InputRejected("Продавец указан несколько раз.")
        normalized[seller_id] = mode
    if set(normalized) != set(seller_ids):
        raise InputRejected("Укажите способ доставки ровно для продавцов этого заказа.")
    return normalized


def _reference(order_id, seller_account_id):
    value = uuid5(_REFERENCE_NAMESPACE, f"{order_id}:{seller_account_id}")
    return base64.b32encode(value.bytes).decode("ascii").rstrip("=")


def _snapshot(shipment):
    return {
        "id": str(shipment.id),
        "order_id": str(shipment.order_id),
        "seller_account_id": str(shipment.seller_account_id),
        "seller_profile_id": str(shipment.seller_profile_id),
        "delivery_mode": shipment.delivery_mode,
        "client_reference": shipment.client_reference,
        "lines": deepcopy(shipment.lines),
        "state": shipment.state,
        "created_at": shipment.created_at.isoformat(),
        "updated_at": shipment.updated_at.isoformat(),
    }


def _record(shipment, *, context):
    FulfillmentEvent.objects.create(
        shipment=shipment,
        state=shipment.state,
        action="planned",
        actor_id=context.actor_account_id if context is not None else None,
        occurred_at=context.now if context is not None else timezone.now(),
    )


def _same_plan(existing, groups, modes):
    expected = {
        group["seller_account_id"]: (modes[group["seller_account_id"]], group["lines"])
        for group in groups
    }
    return all(
        (shipment.delivery_mode, shipment.lines) == expected.get(str(shipment.seller_account_id))
        for shipment in existing
    ) and {str(shipment.seller_account_id) for shipment in existing} == set(expected)


def create_fulfillment_plan(*, order_id, delivery_modes, context=None):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    with transaction.atomic():
        order = CommerceOrder.objects.select_for_update().filter(pk=order_id).first()
        if order is None:
            raise PermissionDenied(_UNAVAILABLE)
        if context is not None and context.actor_account_id is not None and order.buyer_id != context.actor_account_id:
            raise PermissionDenied(_UNAVAILABLE)
        groups = _seller_groups(order.lines)
        modes = _delivery_modes(delivery_modes, {group["seller_account_id"] for group in groups})
        existing = list(
            FulfillmentShipment.objects.select_for_update()
            .filter(order=order)
            .order_by("seller_account_id", "id")
        )
        if existing:
            if not _same_plan(existing, groups, modes):
                raise ConcurrentConflict("План отгрузки уже создан с другими данными.")
            return tuple(_snapshot(shipment) for shipment in existing)
        if order.state != CommerceOrder.State.PAID:
            raise InvalidState("Отгрузку можно планировать только после подтверждённой оплаты.")
        now = context.now if context is not None else timezone.now()
        result = []
        for group in groups:
            shipment = FulfillmentShipment.objects.create(
                order=order,
                seller_account_id=group["seller_account_id"],
                seller_profile_id=group["seller_profile_id"],
                delivery_mode=modes[group["seller_account_id"]],
                client_reference=_reference(order.id, group["seller_account_id"]),
                lines=group["lines"],
                state=FulfillmentShipment.State.PENDING,
                created_at=now,
                updated_at=now,
            )
            _record(shipment, context=context)
            result.append(_snapshot(shipment))
        return tuple(result)


__all__ = ("create_fulfillment_plan",)
