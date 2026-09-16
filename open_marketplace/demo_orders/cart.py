import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from uuid import UUID, uuid4, uuid5

from django.conf import settings
from django.db import transaction

from open_marketplace.catalog.public import UNITS, get_demo_offer_snapshot, get_demo_participant, stock_value
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied

from . import public as orders_public
from .models import Cart, CartCheckoutReceipt, CartItem, DemoOrder


_UNAVAILABLE = "Заказ недоступен."
_QUANTITY_PATTERN = re.compile(r"[0-9]+(?:[.,][0-9]+)?\Z")
_CART_NAMESPACE = UUID("0e4ce45e-4cb8-4a1e-9f3b-bf606b7d2a0b")


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
        if len(text.replace(",", ".").partition(".")[2]) > places:
            raise InputRejected(f"Для единицы {UNITS[unit]} допустимо не более {places} дробных знаков.")
    elif not isinstance(raw, Decimal):
        raise InputRejected("Количество должно быть обычным десятичным числом.")
    elif not raw.is_finite() or raw.as_tuple().exponent < -(0 if unit == "pc" else 3):
        raise InputRejected("Количество содержит слишком много дробных знаков.")
    try:
        value = stock_value(raw, unit)
    except (InputRejected, InvalidOperation):
        raise InputRejected("Укажите корректное количество.") from None
    if value <= 0:
        raise InputRejected("Количество должно быть больше нуля.")
    return value


def _line_total(price, quantity):
    with localcontext() as precision:
        precision.prec = DemoOrder._meta.get_field("total").max_digits
        total = (price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if total >= Decimal("1e38"):
        raise InputRejected("Сумма корзины выходит за допустимый предел.")
    return total


def _order_quantity(quantity, unit):
    return quantity.quantize(Decimal("1") if unit == "pc" else Decimal("0.001"))


def _new_cart(account, context):
    cart_id = uuid4()
    return Cart.objects.create(
        id=cart_id,
        buyer_id=account.id,
        intent_id=uuid5(_CART_NAMESPACE, f"{cart_id}:0"),
        updated_at=context.now,
    )


def _locked_cart(account, context):
    cart = Cart.objects.select_for_update().filter(buyer_id=account.id).first()
    return cart or _new_cart(account, context)


def _touch(cart, context):
    cart.revision += 1
    cart.intent_id = uuid5(_CART_NAMESPACE, f"{cart.id}:{cart.revision}")
    cart.updated_at = context.now
    cart.save(update_fields=("revision", "intent_id", "updated_at"))


def _offer_for_change(variant_id, quantity, account, context):
    offer = get_demo_offer_snapshot(variant_id=variant_id, context=context, lock=True)
    if offer["seller_account_id"] == account.id:
        raise PermissionDenied(_UNAVAILABLE)
    value = _quantity(quantity, offer["unit"])
    if offer["initial_quantity"] < value:
        raise InputRejected("В доступном остатке недостаточно единиц.")
    _line_total(offer["unit_price"], value)
    return offer, value


def _item_dto(item, *, offer=None, message=None):
    current_price = offer["unit_price"] if offer is not None else None
    row_message = message
    if offer is not None and current_price != item.confirmed_unit_price:
        row_message = "Цена изменилась. Обновите строку и подтвердите новую цену перед оформлением."
    return {
        "variant_id": str(item.variant_id),
        "product_id": str(item.product_id),
        "title": item.title,
        "variant_label": item.variant_label,
        "seller_name": item.seller_name,
        "seller_id": str(item.seller_id),
        "quantity": item.quantity.quantize(Decimal("1")) if item.unit == "pc" else item.quantity,
        "unit": item.unit,
        "unit_label": UNITS[item.unit],
        "unit_price": item.confirmed_unit_price,
        "current_unit_price": current_price,
        "total": _line_total(item.confirmed_unit_price, item.quantity),
        "product_url": f"/catalog/p/{item.product_id}/?variant={item.variant_id}",
        "available": offer is not None,
        "message": row_message,
    }


def _cart_dto(cart, context, *, enabled=None):
    enabled = settings.DEMO_ORDERS_ENABLED if enabled is None else enabled
    rows = []
    errors = []
    for item in cart.items.all() if cart else ():
        try:
            offer = get_demo_offer_snapshot(variant_id=item.variant_id, context=context)
        except (PermissionDenied, InputRejected):
            offer = None
            message = "Предложение больше недоступно. Удалите строку перед оформлением."
        else:
            message = None
            if offer["unit_price"] != item.confirmed_unit_price:
                message = "Цена изменилась. Обновите строку и подтвердите новую цену перед оформлением."
            elif offer["initial_quantity"] < item.quantity:
                message = "В доступном остатке недостаточно единиц. Измените количество."
        row = _item_dto(item, offer=offer, message=message)
        rows.append(row)
        if message:
            errors.append(message)
    with localcontext() as precision:
        precision.prec = DemoOrder._meta.get_field("total").max_digits
        total = sum((_line_total(item["unit_price"], item["quantity"]) for item in rows), Decimal("0.00"))
    if not enabled:
        errors.insert(0, "Демонстрация заказов отключена: оформить заказ нельзя.")
    grouped = []
    for row in rows:
        group = next((value for value in grouped if value["seller_id"] == row["seller_id"]), None)
        if group is None:
            group = {"seller_name": row["seller_name"], "seller_id": row["seller_id"], "items": []}
            grouped.append(group)
        group["items"].append(row)
    return {
        "id": str(cart.id) if cart else None,
        "cart_id": str(cart.id) if cart else None,
        "revision": cart.revision if cart else 0,
        "intent_id": str(cart.intent_id) if cart else None,
        "items": tuple(rows),
        "sellers": tuple(grouped),
        "item_count": len(rows),
        "total": total,
        "checkout_available": bool(rows) and enabled and not errors,
        "errors": tuple(dict.fromkeys(errors)),
        "enabled": enabled,
    }


def get_cart(*, context):
    account = _ordinary_account(context)
    cart = Cart.objects.filter(buyer_id=account.id).first()
    return _cart_dto(cart, context)


def add_cart_item(*, variant_id, quantity, context):
    if not settings.DEMO_ORDERS_ENABLED:
        raise PermissionDenied(_UNAVAILABLE)
    variant_id = _uuid(variant_id, "Неверный идентификатор предложения.")
    account = _ordinary_account(context)
    with transaction.atomic():
        account = get_demo_participant(context=context, lock=True)
        offer, value = _offer_for_change(variant_id, quantity, account, context)
        cart = _locked_cart(account, context)
        item = cart.items.filter(variant_id=variant_id).first()
        next_quantity = value if item is None else item.quantity + value
        if offer["initial_quantity"] < next_quantity:
            raise InputRejected("В доступном остатке недостаточно единиц.")
        if item is None:
            CartItem.objects.create(
                cart=cart, variant_id=variant_id, product_id=offer["product_id"], title=offer["title"],
                variant_label=offer["variant_label"], seller_name=offer["seller_display_name"], unit=offer["unit"],
                seller_id=offer["seller_profile_id"],
                quantity=next_quantity, confirmed_unit_price=offer["unit_price"], created_at=context.now, updated_at=context.now,
            )
        else:
            item.quantity = next_quantity
            item.product_id = offer["product_id"]
            item.title = offer["title"]
            item.variant_label = offer["variant_label"]
            item.seller_name = offer["seller_display_name"]
            item.unit = offer["unit"]
            item.confirmed_unit_price = offer["unit_price"]
            item.updated_at = context.now
            item.save()
        _touch(cart, context)
    return _cart_dto(cart, context)


def update_cart_item(*, variant_id, quantity, context):
    if not settings.DEMO_ORDERS_ENABLED:
        raise PermissionDenied(_UNAVAILABLE)
    variant_id = _uuid(variant_id, "Неверный идентификатор предложения.")
    account = _ordinary_account(context)
    with transaction.atomic():
        account = get_demo_participant(context=context, lock=True)
        cart = _locked_cart(account, context)
        item = cart.items.filter(variant_id=variant_id).first()
        if item is None:
            raise PermissionDenied(_UNAVAILABLE)
        offer, value = _offer_for_change(variant_id, quantity, account, context)
        item.product_id = offer["product_id"]
        item.title = offer["title"]
        item.variant_label = offer["variant_label"]
        item.seller_name = offer["seller_display_name"]
        item.unit = offer["unit"]
        item.quantity = value
        item.confirmed_unit_price = offer["unit_price"]
        item.updated_at = context.now
        item.save()
        _touch(cart, context)
    return _cart_dto(cart, context)


def remove_cart_item(*, variant_id, context):
    if not settings.DEMO_ORDERS_ENABLED:
        raise PermissionDenied(_UNAVAILABLE)
    variant_id = _uuid(variant_id, "Неверный идентификатор предложения.")
    account = _ordinary_account(context)
    with transaction.atomic():
        account = get_demo_participant(context=context, lock=True)
        cart = _locked_cart(account, context)
        deleted, _ = cart.items.filter(variant_id=variant_id).delete()
        if deleted:
            _touch(cart, context)
    return _cart_dto(cart, context)


def _receipt_orders(receipt, context):
    return tuple(orders_public.get_order(order_id=order_id, context=context) for order_id in receipt.order_ids)


def checkout_cart(*, intent_id, context):
    if not settings.DEMO_ORDERS_ENABLED:
        raise PermissionDenied(_UNAVAILABLE)
    intent_id = _uuid(intent_id, "Неверный идентификатор намерения.")
    account = _ordinary_account(context)
    with transaction.atomic():
        account = get_demo_participant(context=context, lock=True)
        cart = _locked_cart(account, context)
        receipt = CartCheckoutReceipt.objects.filter(cart=cart, intent_id=intent_id).first()
        if receipt is not None:
            return _receipt_orders(receipt, context)
        if cart.intent_id != intent_id:
            raise ConcurrentConflict("Содержимое корзины уже изменилось. Обновите корзину и подтвердите её снова.")
        items = list(cart.items.select_for_update())
        if not items:
            raise InputRejected("Корзина пуста.")
        for item in sorted(items, key=lambda row: (str(row.product_id), str(row.variant_id))):
            offer = get_demo_offer_snapshot(variant_id=item.variant_id, context=context, lock=True)
            if offer["seller_account_id"] == account.id:
                raise PermissionDenied(_UNAVAILABLE)
            if offer["unit_price"] != item.confirmed_unit_price:
                raise ConcurrentConflict("Цена изменилась. Обновите строку и подтвердите новую цену перед оформлением.")
            if offer["unit"] != item.unit:
                raise ConcurrentConflict("Единица товара изменилась. Обновите строку и подтвердите её снова.")
        created = []
        for item in sorted(items, key=lambda row: (str(row.product_id), str(row.variant_id))):
            created.append(orders_public.create_order(
                variant_id=item.variant_id,
                quantity=_order_quantity(item.quantity, item.unit),
                intent_id=uuid5(intent_id, str(item.variant_id)),
                context=context,
            ))
        CartCheckoutReceipt.objects.create(
            cart=cart, intent_id=intent_id, revision=cart.revision,
            order_ids=[order["id"] for order in created], created_at=context.now,
        )
        cart.items.all().delete()
        _touch(cart, context)
    return tuple(created)


__all__ = (
    "add_cart_item", "checkout_cart", "get_cart", "remove_cart_item", "update_cart_item",
)
