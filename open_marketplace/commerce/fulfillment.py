import base64
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from django.db import transaction
from django.db.models import Q
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


_QUANTITY_PATTERN = re.compile(r"(?:0|[1-9]\d*)(?:\.\d+)?\Z")


def _quantity_precision(line):
    try:
        unit = line["unit"]
    except (KeyError, TypeError):
        raise InputRejected("Снимок заказа содержит неверную единицу товара.") from None
    if unit == "pc":
        return 0
    if unit in {"kg", "m"}:
        return 3
    raise InputRejected("Снимок заказа содержит неподдерживаемую единицу товара.")


def _normalized_quantity(value, *, line):
    if not isinstance(value, str) or _QUANTITY_PATTERN.fullmatch(value) is None:
        raise InputRejected("Количество товара в упаковке указано неверно.")
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        raise InputRejected("Количество товара в упаковке указано неверно.") from None
    if quantity <= 0 or -quantity.as_tuple().exponent > _quantity_precision(line):
        raise InputRejected("Количество товара в упаковке указано неверно.")
    return quantity, format(quantity.normalize(), "f")


def _validated_package_items(value, *, lines):
    if type(value) is not list or not value:
        raise InputRejected("У каждой упаковки должна быть позиция заказа.")
    totals = [Decimal("0") for _ in lines]
    seen = set()
    normalized = []
    for item in value:
        if type(item) is not dict or set(item) != {"line_index", "quantity"}:
            raise InputRejected("Позиция упаковки содержит неподдерживаемые данные.")
        line_index = item["line_index"]
        if type(line_index) is not int or line_index < 0 or line_index >= len(lines) or line_index in seen:
            raise InputRejected("Указана неверная позиция заказа в упаковке.")
        quantity, normalized_quantity = _normalized_quantity(item["quantity"], line=lines[line_index])
        seen.add(line_index)
        totals[line_index] += quantity
        normalized.append({"line_index": line_index, "quantity": normalized_quantity})
    normalized.sort(key=lambda item: item["line_index"])
    return normalized, totals


def _validated_packages(value, *, lines):
    if type(value) is not list or len(value) > 32:
        raise InputRejected("Укажите список упаковок отгрузки.")
    if type(lines) is not list or not lines:
        raise InputRejected("Снимок отгрузки не содержит позиций заказа.")
    fields = ("weight_grams", "length_cm", "width_cm", "height_cm")
    totals = [Decimal("0") for _ in lines]
    result = []
    for package in value:
        if type(package) is not dict or set(package) != {*fields, "items"}:
            raise InputRejected("Упаковка содержит неподдерживаемые данные.")
        normalized = {}
        for field in fields:
            amount = package[field]
            if type(amount) is not int or amount <= 0:
                raise InputRejected("Вес и размеры упаковки должны быть положительными целыми числами.")
            normalized[field] = amount
        items, package_totals = _validated_package_items(package["items"], lines=lines)
        normalized["items"] = items
        totals = [total + package_total for total, package_total in zip(totals, package_totals)]
        result.append(normalized)
    if result:
        for line, total in zip(lines, totals):
            try:
                expected = Decimal(line["quantity"])
            except (InvalidOperation, KeyError, TypeError):
                raise InputRejected("Снимок заказа содержит неверное количество товара.") from None
            if total != expected:
                raise InputRejected("Количество товара в упаковках не совпадает с заказом.")
    return result


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
        "packages": deepcopy(shipment.packages),
        "state": shipment.state,
        "created_at": shipment.created_at.isoformat(),
        "updated_at": shipment.updated_at.isoformat(),
    }


def _snapshot_for_actor(shipment, *, actor_id):
    result = _snapshot(shipment)
    if actor_id != shipment.seller_account_id:
        result.pop("packages")
    return result


def _record(shipment, *, context):
    FulfillmentEvent.objects.create(
        shipment=shipment,
        state=shipment.state,
        action="planned",
        sequence=1,
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
                packages=[],
                state=FulfillmentShipment.State.PENDING,
                created_at=now,
                updated_at=now,
            )
            _record(shipment, context=context)
            result.append(_snapshot(shipment))
        return tuple(result)


def set_fulfillment_packages(*, shipment_id, packages, context):
    shipment_id = _uuid(shipment_id, "Неверный идентификатор отгрузки.")
    if context is None or context.actor_account_id is None:
        raise PermissionDenied(_UNAVAILABLE)
    with transaction.atomic():
        order = CommerceOrder.objects.select_for_update().filter(shipments__id=shipment_id).first()
        if order is None:
            raise PermissionDenied(_UNAVAILABLE)
        shipment = FulfillmentShipment.objects.select_for_update().filter(
            pk=shipment_id,
            order=order,
        ).first()
        if shipment is None or shipment.seller_account_id != context.actor_account_id:
            raise PermissionDenied(_UNAVAILABLE)
        if shipment.state != FulfillmentShipment.State.PENDING:
            raise InvalidState("Упаковку можно изменить только для ожидающей отгрузки.")
        normalized = _validated_packages(packages, lines=shipment.lines)
        if shipment.packages == normalized:
            return _snapshot_for_actor(shipment, actor_id=context.actor_account_id)
        shipment.packages = normalized
        shipment.updated_at = context.now
        shipment.save(update_fields=("packages", "updated_at"))
        return _snapshot_for_actor(shipment, actor_id=context.actor_account_id)


def _authorize_transition(*, shipment, order, target_state, context):
    if context is None or context.actor_account_id is None:
        raise PermissionDenied(_UNAVAILABLE)
    if target_state in {
        FulfillmentShipment.State.READY,
        FulfillmentShipment.State.IN_TRANSIT,
    }:
        allowed = shipment.seller_account_id == context.actor_account_id
    elif target_state == FulfillmentShipment.State.DELIVERED:
        allowed = order.buyer_id == context.actor_account_id
    else:
        allowed = False
    if not allowed:
        raise PermissionDenied(_UNAVAILABLE)


def transition_fulfillment(*, shipment_id, target_state, context):
    shipment_id = _uuid(shipment_id, "Неверный идентификатор отгрузки.")
    if not isinstance(target_state, str) or target_state not in FulfillmentShipment.State.values:
        raise InputRejected("Указано неизвестное состояние отгрузки.")
    with transaction.atomic():
        order = CommerceOrder.objects.select_for_update().filter(shipments__id=shipment_id).first()
        if order is None:
            raise PermissionDenied(_UNAVAILABLE)
        shipment = FulfillmentShipment.objects.select_for_update().filter(
            pk=shipment_id,
            order=order,
        ).first()
        if shipment is None:
            raise PermissionDenied(_UNAVAILABLE)
        _authorize_transition(
            shipment=shipment,
            order=order,
            target_state=target_state,
            context=context,
        )
        if target_state == shipment.state:
            if target_state == FulfillmentShipment.State.PENDING:
                raise InvalidState("Отгрузка ещё не готова к переходу.")
            return _snapshot_for_actor(shipment, actor_id=context.actor_account_id)
        if target_state == FulfillmentShipment.State.READY:
            if shipment.state != FulfillmentShipment.State.PENDING:
                raise InvalidState("Отгрузка может стать готовой только из состояния ожидания.")
        elif target_state == FulfillmentShipment.State.IN_TRANSIT:
            if shipment.delivery_mode == FulfillmentShipment.DeliveryMode.CDEK:
                raise InvalidState("Переход СДЭК должен прийти через проверенное уведомление провайдера.")
            if shipment.state != FulfillmentShipment.State.READY:
                raise InvalidState("В путь можно передать только готовую отгрузку.")
        elif target_state == FulfillmentShipment.State.DELIVERED:
            if shipment.delivery_mode == FulfillmentShipment.DeliveryMode.CDEK:
                raise InvalidState("Получение СДЭК подтверждается отдельной проверкой провайдера.")
            if shipment.state != FulfillmentShipment.State.IN_TRANSIT:
                raise InvalidState("Получение можно подтвердить только для отгрузки в пути.")
        else:
            raise InvalidState("Такой переход состояния отгрузки не поддерживается.")
        shipment.state = target_state
        shipment.updated_at = context.now
        shipment.save(update_fields=("state", "updated_at"))
        last_sequence = FulfillmentEvent.objects.filter(shipment=shipment).order_by("-sequence").values_list("sequence", flat=True).first()
        FulfillmentEvent.objects.create(
            shipment=shipment,
            state=shipment.state,
            action=target_state,
            sequence=last_sequence + 1,
            actor_id=context.actor_account_id,
            occurred_at=context.now,
        )
        return _snapshot_for_actor(shipment, actor_id=context.actor_account_id)


def _authorize_read(*, shipment, order, context):
    if context is None or context.actor_account_id is None:
        raise PermissionDenied(_UNAVAILABLE)
    if context.actor_account_id not in {order.buyer_id, shipment.seller_account_id}:
        raise PermissionDenied(_UNAVAILABLE)


def _available_actions(*, shipment, order, context):
    if context is None or context.actor_account_id is None:
        return ()
    if context.actor_account_id == shipment.seller_account_id:
        if shipment.state == FulfillmentShipment.State.PENDING:
            return (FulfillmentShipment.State.READY,)
        if (
            shipment.state == FulfillmentShipment.State.READY
            and shipment.delivery_mode == FulfillmentShipment.DeliveryMode.SELLER
        ):
            return (FulfillmentShipment.State.IN_TRANSIT,)
    if (
        context.actor_account_id == order.buyer_id
        and shipment.delivery_mode == FulfillmentShipment.DeliveryMode.SELLER
        and shipment.state == FulfillmentShipment.State.IN_TRANSIT
    ):
        return (FulfillmentShipment.State.DELIVERED,)
    return ()


def _view(shipment, *, context):
    result = _snapshot_for_actor(shipment, actor_id=context.actor_account_id)
    result["actions"] = _available_actions(shipment=shipment, order=shipment.order, context=context)
    return result


def list_fulfillment_shipments(*, context):
    if context is None or context.actor_account_id is None:
        raise PermissionDenied(_UNAVAILABLE)
    shipments = (
        FulfillmentShipment.objects.select_related("order")
        .filter(Q(order__buyer_id=context.actor_account_id) | Q(seller_account_id=context.actor_account_id))
        .order_by("-created_at", "-id")
    )
    return tuple(_view(shipment, context=context) for shipment in shipments)


def get_fulfillment_shipment(*, shipment_id, context):
    shipment_id = _uuid(shipment_id, "Неверный идентификатор отгрузки.")
    shipment = FulfillmentShipment.objects.select_related("order").filter(pk=shipment_id).first()
    if shipment is None:
        raise PermissionDenied(_UNAVAILABLE)
    _authorize_read(shipment=shipment, order=shipment.order, context=context)
    return _view(shipment, context=context)


__all__ = (
    "create_fulfillment_plan",
    "get_fulfillment_shipment",
    "list_fulfillment_shipments",
    "set_fulfillment_packages",
    "transition_fulfillment",
)
