from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from open_marketplace.catalog.public import (
    buyer,
    commit_inventory,
    release_inventory,
    reserve_inventory,
)
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied

from .models import CommerceOrder, CommerceOrderEvent, PaymentEvent, PaymentIntent


_UNAVAILABLE = "Заказ недоступен."
_MAX_PAYMENT_AMOUNT = 9223372036854775807


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


def _total(lines):
    try:
        with localcontext() as context:
            context.prec = CommerceOrder._meta.get_field("total").max_digits
            total = sum(
                Decimal(line["unit_price"]) * Decimal(line["quantity"])
                for line in lines
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, KeyError, TypeError):
        raise InputRejected("Снимок заказа содержит неверную сумму.") from None
    if total < 0 or total >= Decimal("1e38"):
        raise InputRejected("Сумма заказа выходит за допустимый предел.")
    return total


def _snapshot(order):
    return {
        "id": str(order.id),
        "intent_id": str(order.intent_id),
        "reservation_id": str(order.reservation_id),
        "buyer_id": str(order.buyer_id),
        "lines": deepcopy(order.lines),
        "total": order.total,
        "currency": order.currency,
        "state": order.state,
        "state_label": order.get_state_display(),
    }


def _record(order, *, action, context=None):
    CommerceOrderEvent.objects.create(
        order=order,
        state=order.state,
        action=action,
        actor_id=context.actor_account_id if context is not None else None,
        occurred_at=context.now if context is not None else timezone.now(),
    )


def create_order(*, intent_id, lines, context):
    intent_id = _uuid(intent_id, "Неверный идентификатор намерения.")
    if not isinstance(lines, list) or not lines:
        raise InputRejected("Укажите товары для заказа.")
    account = buyer(context)
    with transaction.atomic():
        reservation = reserve_inventory(
            intent_id=intent_id,
            lines=lines,
            context=context,
        )
        if reservation["state"] != "held":
            raise ConcurrentConflict("Это намерение уже завершено и не может стать новым заказом.")
        existing = CommerceOrder.objects.select_for_update().filter(
            intent_id=intent_id,
        ).first()
        if existing is not None:
            if (
                str(existing.buyer_id) != reservation["buyer_id"]
                or str(existing.reservation_id) != reservation["id"]
                or existing.lines != reservation["lines"]
            ):
                raise ConcurrentConflict("Это намерение уже связано с другим заказом.")
            return _snapshot(existing)
        order = CommerceOrder.objects.create(
            intent_id=intent_id,
            reservation_id=reservation["id"],
            buyer_id=account.id,
            lines=deepcopy(reservation["lines"]),
            total=_total(reservation["lines"]),
            state=CommerceOrder.State.AWAITING_PAYMENT,
            created_at=context.now,
            updated_at=context.now,
        )
        _record(order, action="created", context=context)
        return _snapshot(order)


def get_order(*, order_id, context):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    account = buyer(context)
    order = CommerceOrder.objects.filter(pk=order_id, buyer_id=account.id).first()
    if order is None:
        raise PermissionDenied(_UNAVAILABLE)
    return _snapshot(order)


def list_orders(*, context):
    account = buyer(context)
    return [
        {
            **_snapshot(order),
            "created_at": order.created_at,
        }
        for order in CommerceOrder.objects.filter(buyer_id=account.id)
    ]


def cancel_order(*, order_id, context):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    account = buyer(context)
    with transaction.atomic():
        order = CommerceOrder.objects.select_for_update().filter(
            pk=order_id,
            buyer_id=account.id,
        ).first()
        if order is None:
            raise PermissionDenied(_UNAVAILABLE)
        if order.state == CommerceOrder.State.CANCELLED:
            return _snapshot(order)
        if order.state != CommerceOrder.State.AWAITING_PAYMENT:
            raise ConcurrentConflict(
                "Оплаченный заказ отменяется только через подтверждённую процедуру возврата."
            )
        released = release_inventory(reservation_id=order.reservation_id)
        if released["state"] != "released":
            raise ConcurrentConflict("Резерв заказа уже завершён другим действием.")
        order.state = CommerceOrder.State.CANCELLED
        order.updated_at = context.now
        order.save(update_fields=("state", "updated_at"))
        _record(order, action="cancelled", context=context)
        return _snapshot(order)


def _payment_snapshot(payment):
    return {
        "id": str(payment.id),
        "order_id": str(payment.order_id),
        "provider": payment.provider,
        "provider_order_id": payment.provider_order_id,
        "deal_id": payment.deal_id,
        "payment_id": payment.payment_id,
        "amount_kopecks": payment.amount_kopecks,
        "currency": payment.currency,
        "state": payment.state,
    }


def _provider_reference(value, message):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 64
        or any(ord(char) < 32 for char in value)
    ):
        raise InputRejected(message)
    return value


def prepare_payment(*, order_id, context):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    account = buyer(context)
    with transaction.atomic():
        order = CommerceOrder.objects.select_for_update().filter(
            pk=order_id,
            buyer_id=account.id,
        ).first()
        if order is None:
            raise PermissionDenied(_UNAVAILABLE)
        if order.state != CommerceOrder.State.AWAITING_PAYMENT:
            raise InvalidState("Для этого заказа нельзя подготовить оплату.")
        payment = PaymentIntent.objects.select_for_update().filter(order=order).first()
        amount_kopecks = int(order.total * 100)
        if not 0 < amount_kopecks <= _MAX_PAYMENT_AMOUNT:
            raise InputRejected("Сумма оплаты выходит за допустимый предел.")
        if payment is None:
            payment = PaymentIntent.objects.create(
                order=order,
                provider_order_id=str(order.id),
                amount_kopecks=amount_kopecks,
                currency=order.currency,
                created_at=context.now,
                updated_at=context.now,
            )
        return _payment_snapshot(payment)


def bind_tbank_reference(*, order_id, payment_id, deal_id):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    payment_id = _provider_reference(payment_id, "Неверный идентификатор платежа.")
    deal_id = _provider_reference(deal_id, "Неверный идентификатор сделки.")
    with transaction.atomic():
        payment = PaymentIntent.objects.select_for_update().filter(order_id=order_id).first()
        if payment is None:
            raise PermissionDenied(_UNAVAILABLE)
        if payment.payment_id == payment_id and payment.deal_id == deal_id:
            return _payment_snapshot(payment)
        if payment.payment_id is not None or payment.deal_id is not None:
            raise ConcurrentConflict("Платёж уже связан с другой операцией провайдера.")
        if payment.state != PaymentIntent.State.PENDING:
            raise InvalidState("Нельзя привязать провайдера к завершённому платежу.")
        if PaymentIntent.objects.filter(payment_id=payment_id).exclude(pk=payment.pk).exists():
            raise ConcurrentConflict("Идентификатор платежа уже используется.")
        if PaymentIntent.objects.filter(deal_id=deal_id).exclude(pk=payment.pk).exists():
            raise ConcurrentConflict("Идентификатор сделки уже используется.")
        payment.payment_id = payment_id
        payment.deal_id = deal_id
        payment.updated_at = timezone.now()
        payment.save(update_fields=("payment_id", "deal_id", "updated_at"))
        return _payment_snapshot(payment)


_NOTICE_STATUSES = {
    "AUTHORIZED",
    "CONFIRMED",
    "REVERSED",
    "REFUNDED",
    "PARTIAL_REFUNDED",
    "REJECTED",
    "3DS_CHECKING",
    "DEADLINE_EXPIRED",
}


def _notice_data(notice):
    required = {"order_id", "payment_id", "deal_id", "amount", "status", "success"}
    if type(notice) is not dict or set(notice) != required:
        raise InputRejected("Неверное подтверждённое уведомление платежа.")
    order_id = _provider_reference(notice["order_id"], "Неверный номер заказа провайдера.")
    payment_id = _provider_reference(notice["payment_id"], "Неверный идентификатор платежа.")
    deal_id = _provider_reference(notice["deal_id"], "Неверный идентификатор сделки.")
    if type(notice["amount"]) is not int or notice["amount"] < 0:
        raise InputRejected("Уведомление содержит неверную сумму.")
    status = notice["status"]
    success = notice["success"]
    if not isinstance(status, str) or status not in _NOTICE_STATUSES or type(success) is not bool:
        raise InputRejected("Уведомление содержит неизвестный статус.")
    if status in {"AUTHORIZED", "CONFIRMED"} and not success:
        raise InputRejected("Успешный статус платежа должен иметь успешный результат.")
    if notice["status"] in {"REJECTED", "DEADLINE_EXPIRED"} and notice["success"]:
        raise InputRejected("Отклонённый платеж не может иметь успешный результат.")
    return {
        "order_id": order_id,
        "payment_id": payment_id,
        "deal_id": deal_id,
        "amount": notice["amount"],
        "status": notice["status"],
        "success": notice["success"],
    }


def _event_fingerprint(data):
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _apply_payment_notice(payment, order, data):
    status = data["status"]
    if data["amount"] > payment.amount_kopecks:
        raise InputRejected("Сумма уведомления больше суммы заказа.")
    if status in {"AUTHORIZED", "CONFIRMED"} and data["amount"] != payment.amount_kopecks:
        raise InputRejected("Сумма уведомления не совпадает с заказом.")
    current = payment.state
    if current in {PaymentIntent.State.REJECTED, PaymentIntent.State.REVERSED} and status not in {"REJECTED", "DEADLINE_EXPIRED", "REVERSED"}:
        raise ConcurrentConflict("Завершённый отклонённый платёж нельзя возобновить.")
    if current == PaymentIntent.State.REFUNDED and status != "REFUNDED":
        raise ConcurrentConflict("Возвращённый платёж нельзя возобновить.")
    if current == PaymentIntent.State.PARTIAL_REFUNDED and status not in {"REFUNDED", "PARTIAL_REFUNDED"}:
        raise ConcurrentConflict("Частично возвращённый платёж нельзя возобновить.")
    if status == "CONFIRMED":
        if current != PaymentIntent.State.CONFIRMED:
            if order.state != CommerceOrder.State.AWAITING_PAYMENT:
                raise ConcurrentConflict("Подтверждение пришло после завершения заказа.")
            committed = commit_inventory(reservation_id=order.reservation_id)
            if committed["state"] != "committed":
                raise ConcurrentConflict("Остаток заказа уже завершён другой операцией.")
            order.state = CommerceOrder.State.PAID
            order.updated_at = timezone.now()
            order.save(update_fields=("state", "updated_at"))
            _record(order, action="payment_confirmed")
        payment.state = PaymentIntent.State.CONFIRMED
    elif status == "AUTHORIZED":
        if current == PaymentIntent.State.PENDING:
            payment.state = PaymentIntent.State.AUTHORIZED
    elif status in {"REJECTED", "DEADLINE_EXPIRED", "REVERSED"}:
        if current in {PaymentIntent.State.PENDING, PaymentIntent.State.AUTHORIZED}:
            if order.state != CommerceOrder.State.AWAITING_PAYMENT:
                raise ConcurrentConflict("Отклонение пришло после завершения заказа.")
            released = release_inventory(reservation_id=order.reservation_id)
            if released["state"] != "released":
                raise ConcurrentConflict("Резерв заказа уже завершён другой операцией.")
            order.state = CommerceOrder.State.CANCELLED
            order.updated_at = timezone.now()
            order.save(update_fields=("state", "updated_at"))
            _record(order, action="payment_rejected")
            payment.state = {
                "REVERSED": PaymentIntent.State.REVERSED,
                "REJECTED": PaymentIntent.State.REJECTED,
                "DEADLINE_EXPIRED": PaymentIntent.State.REJECTED,
            }[status]
    elif status in {"REFUNDED", "PARTIAL_REFUNDED"}:
        if current in {PaymentIntent.State.PENDING, PaymentIntent.State.AUTHORIZED}:
            if order.state != CommerceOrder.State.AWAITING_PAYMENT:
                raise ConcurrentConflict("Возврат пришёл после завершения заказа.")
            released = release_inventory(reservation_id=order.reservation_id)
            if released["state"] != "released":
                raise ConcurrentConflict("Резерв заказа уже завершён другой операцией.")
            order.state = CommerceOrder.State.CANCELLED
            order.updated_at = timezone.now()
            order.save(update_fields=("state", "updated_at"))
            _record(order, action="payment_refund_preconfirm")
        if current not in {PaymentIntent.State.REJECTED, PaymentIntent.State.REVERSED}:
            payment.state = (
                PaymentIntent.State.REFUNDED
                if status == "REFUNDED"
                else PaymentIntent.State.PARTIAL_REFUNDED
            )
    payment.updated_at = timezone.now()
    payment.save(update_fields=("state", "updated_at"))


def apply_verified_tbank_notice(*, order_id, notice):
    order_id = _uuid(order_id, "Неверный идентификатор заказа.")
    data = _notice_data(notice)
    fingerprint = _event_fingerprint(data)
    with transaction.atomic():
        payment = PaymentIntent.objects.select_for_update().select_related("order").filter(
            order_id=order_id,
        ).first()
        if payment is None:
            raise PermissionDenied(_UNAVAILABLE)
        order = payment.order
        if (
            data["order_id"] != payment.provider_order_id
            or data["payment_id"] != payment.payment_id
            or data["deal_id"] != payment.deal_id
        ):
            raise InputRejected("Идентификаторы уведомления не совпадают с платежом.")
        existing = PaymentEvent.objects.filter(fingerprint=fingerprint).first()
        if existing is not None:
            return {
                "order_id": str(order.id),
                "payment_state": payment.state,
                "order_state": order.state,
            }
        PaymentEvent.objects.create(
            payment=payment,
            fingerprint=fingerprint,
            provider_status=data["status"],
            amount_kopecks=data["amount"],
            payload=data,
            received_at=timezone.now(),
        )
        _apply_payment_notice(payment, order, data)
        return {
            "order_id": str(order.id),
            "payment_state": payment.state,
            "order_state": order.state,
        }


__all__ = (
    "apply_verified_tbank_notice",
    "bind_tbank_reference",
    "cancel_order",
    "create_order",
    "get_order",
    "prepare_payment",
)
