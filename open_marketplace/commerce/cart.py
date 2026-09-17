from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext
from uuid import UUID, uuid4, uuid5

from django.db import transaction

from open_marketplace.catalog import public as catalog_public
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied

from .models import CommerceCart, CommerceCartCheckoutReceipt
from .services import create_order, get_order


_UNAVAILABLE = "Корзина недоступна."
_CART_NAMESPACE = UUID("8f0fc9a0-b54a-48f1-9e99-7e60ca76d6fb")


def _uuid(value, message):
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise InputRejected(message)
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise InputRejected(message) from None
    if str(parsed) != value:
        raise InputRejected(message)
    return parsed


def _buyer(context):
    return catalog_public.buyer(context)


def _locked_cart(account, context):
    cart, _ = CommerceCart.objects.select_for_update().get_or_create(
        buyer_id=account.id,
        defaults={
            "id": uuid4(),
            "intent_id": uuid4(),
            "items": [],
            "updated_at": context.now,
        },
    )
    if cart.revision == 0 and cart.intent_id is None:
        cart.intent_id = uuid5(_CART_NAMESPACE, f"{cart.id}:0")
        cart.save(update_fields=("intent_id",))
    return cart


def _touch(cart, context):
    cart.revision += 1
    cart.intent_id = uuid5(_CART_NAMESPACE, f"{cart.id}:{cart.revision}")
    cart.updated_at = context.now
    cart.save(update_fields=("revision", "intent_id", "updated_at", "items"))


def _quantity(raw, unit):
    try:
        value = catalog_public.stock_value(raw, unit)
    except InputRejected:
        raise InputRejected("Укажите корректное количество.") from None
    if value <= 0:
        raise InputRejected("Количество должно быть больше нуля.")
    return value


def _money(value):
    with localcontext() as precision:
        precision.prec = 40
        return (Decimal(value) * Decimal("1.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _line_total(line):
    with localcontext() as precision:
        precision.prec = 40
        total = (_money(line["unit_price"]) * _quantity(line["quantity"], line["unit"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    return total


def _line_from_offer(offer, quantity):
    return {
        "variant_id": str(offer["variant_id"]),
        "product_id": str(offer["product_id"]),
        "seller_profile_id": str(offer["seller_profile_id"]),
        "seller_account_id": str(offer["seller_account_id"]),
        "seller_display_name": offer["seller_display_name"],
        "title": offer["title"],
        "variant_label": offer["variant_label"],
        "unit": offer["unit"],
        "quantity": format(quantity.normalize(), "f"),
        "unit_price": str(offer["unit_price"]),
    }


def _item_view(line, offer=None, message=None):
    quantity = _quantity(line["quantity"], line["unit"])
    unit_price = Decimal(line["unit_price"])
    if offer is not None and offer["unit_price"] != unit_price:
        message = "Цена изменилась. Обновите строку перед оформлением."
    return {
        "variant_id": line["variant_id"],
        "product_id": line["product_id"],
        "seller_profile_id": line["seller_profile_id"],
        "seller_account_id": line["seller_account_id"],
        "seller_name": line["seller_display_name"],
        "title": line["title"],
        "variant_label": line["variant_label"],
        "unit": line["unit"],
        "quantity": quantity,
        "unit_price": unit_price,
        "current_unit_price": offer["unit_price"] if offer is not None else None,
        "total": _line_total(line),
        "message": message,
    }


def _cart_view(cart, context):
    if cart is None:
        return {
            "id": None,
            "revision": 0,
            "intent_id": None,
            "items": (),
            "sellers": (),
            "item_count": 0,
            "total": Decimal("0.00"),
            "checkout_available": False,
            "errors": (),
        }
    items = []
    errors = []
    for line in cart.items:
        try:
            offer = catalog_public.get_offer_snapshot(variant_id=line["variant_id"], context=context)
        except PermissionDenied:
            offer = None
            message = "Предложение больше недоступно. Удалите строку перед оформлением."
        else:
            message = None
        item = _item_view(line, offer=offer, message=message)
        items.append(item)
        if item["message"]:
            errors.append(item["message"])
    sellers = []
    for item in items:
        seller = next((row for row in sellers if row["seller_account_id"] == item["seller_account_id"]), None)
        if seller is None:
            seller = {
                "seller_account_id": item["seller_account_id"],
                "seller_name": item["seller_name"],
                "items": [],
            }
            sellers.append(seller)
        seller["items"].append(item)
    total = sum((item["total"] for item in items), Decimal("0.00"))
    return {
        "id": str(cart.id),
        "revision": cart.revision,
        "intent_id": str(cart.intent_id),
        "items": tuple(items),
        "sellers": tuple(sellers),
        "item_count": len(items),
        "total": total,
        "checkout_available": bool(items) and not errors,
        "errors": tuple(dict.fromkeys(errors)),
    }


def get_commerce_cart(*, context):
    account = _buyer(context)
    cart = CommerceCart.objects.filter(buyer_id=account.id).first()
    return _cart_view(cart, context)


def add_commerce_cart_item(*, variant_id, quantity, context):
    account = _buyer(context)
    with transaction.atomic():
        cart = _locked_cart(account, context)
        offer = catalog_public.get_offer_snapshot(variant_id=variant_id, context=context, lock=True)
        if offer["seller_account_id"] == account.id:
            raise PermissionDenied(_UNAVAILABLE)
        value = _quantity(quantity, offer["unit"])
        items = deepcopy(cart.items)
        index = next((index for index, line in enumerate(items) if line["variant_id"] == str(offer["variant_id"])), None)
        if index is None:
            next_value = value
            items.append(_line_from_offer(offer, value))
        else:
            existing = items[index]
            next_value = _quantity(existing["quantity"], existing["unit"]) + value
            items[index] = _line_from_offer(offer, next_value)
        if offer["initial_quantity"] < next_value:
            raise InputRejected("Недостаточно свободного остатка для корзины.")
        cart.items = items
        _touch(cart, context)
    return _cart_view(cart, context)


def update_commerce_cart_item(*, variant_id, quantity, context):
    account = _buyer(context)
    with transaction.atomic():
        cart = _locked_cart(account, context)
        variant_id = str(_uuid(variant_id, "Неверный идентификатор предложения."))
        items = deepcopy(cart.items)
        index = next((index for index, line in enumerate(items) if line["variant_id"] == variant_id), None)
        if index is None:
            raise PermissionDenied(_UNAVAILABLE)
        offer = catalog_public.get_offer_snapshot(variant_id=variant_id, context=context, lock=True)
        if offer["seller_account_id"] == account.id:
            raise PermissionDenied(_UNAVAILABLE)
        value = _quantity(quantity, offer["unit"])
        if offer["initial_quantity"] < value:
            raise InputRejected("Недостаточно свободного остатка для корзины.")
        items[index] = _line_from_offer(offer, value)
        cart.items = items
        _touch(cart, context)
    return _cart_view(cart, context)


def remove_commerce_cart_item(*, variant_id, context):
    account = _buyer(context)
    with transaction.atomic():
        cart = _locked_cart(account, context)
        variant_id = str(_uuid(variant_id, "Неверный идентификатор предложения."))
        cart.items = [line for line in cart.items if line["variant_id"] != variant_id]
        _touch(cart, context)
    return _cart_view(cart, context)


def _receipt_orders(receipt, context):
    return tuple(get_order(order_id=order_id, context=context) for order_id in receipt.order_ids)


def checkout_commerce_cart(*, intent_id, context):
    intent_id = _uuid(intent_id, "Неверный идентификатор намерения.")
    account = _buyer(context)
    with transaction.atomic():
        cart = _locked_cart(account, context)
        receipt = CommerceCartCheckoutReceipt.objects.filter(cart=cart, intent_id=intent_id).first()
        if receipt is not None:
            return _receipt_orders(receipt, context)
        if cart.intent_id != intent_id:
            raise ConcurrentConflict("Содержимое корзины уже изменилось. Обновите корзину и подтвердите её снова.")
        if not cart.items:
            raise InputRejected("Корзина пуста.")
        lines = []
        for line in sorted(cart.items, key=lambda row: row["variant_id"]):
            offer = catalog_public.get_offer_snapshot(variant_id=line["variant_id"], context=context, lock=True)
            if offer["seller_account_id"] == account.id:
                raise PermissionDenied(_UNAVAILABLE)
            quantity = _quantity(line["quantity"], offer["unit"])
            if offer["unit"] != line["unit"]:
                raise ConcurrentConflict("Единица товара изменилась. Обновите строку и подтвердите её снова.")
            if offer["unit_price"] != Decimal(line["unit_price"]):
                raise ConcurrentConflict("Цена изменилась. Обновите строку и подтвердите её снова.")
            if offer["initial_quantity"] < quantity:
                raise InputRejected("Недостаточно свободного остатка для заказа.")
            lines.append({
                "variant_id": line["variant_id"],
                "quantity": line["quantity"],
                "expected_unit_price": line["unit_price"],
            })
        order = create_order(intent_id=intent_id, lines=lines, context=context)
        CommerceCartCheckoutReceipt.objects.create(
            cart=cart,
            intent_id=intent_id,
            revision=cart.revision,
            order_ids=[order["id"]],
            created_at=context.now,
        )
        cart.items = []
        _touch(cart, context)
        return (order,)


__all__ = (
    "add_commerce_cart_item",
    "checkout_commerce_cart",
    "get_commerce_cart",
    "remove_commerce_cart_item",
    "update_commerce_cart_item",
)
