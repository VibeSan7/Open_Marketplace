from copy import deepcopy
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from open_marketplace.catalog.domain import price_value, stock_value
from open_marketplace.catalog.models import InventoryAllocation, InventoryReservation, Product, Stock, Variant
from open_marketplace.catalog.policy import buyer, identifier
from open_marketplace.catalog.queries import get_product
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied


_UNAVAILABLE = "Резерв недоступен."


def _request(lines):
    if not isinstance(lines, list) or not lines:
        raise InputRejected("Укажите товары для резервирования.")
    result = []
    seen = set()
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"variant_id", "quantity", "expected_unit_price"}:
            raise InputRejected("Неверные поля товара для резервирования.")
        variant_id = str(identifier(line["variant_id"]))
        if variant_id in seen:
            raise InputRejected("Объедините количество одинакового варианта в одну строку.")
        seen.add(variant_id)
        quantity = stock_value(line["quantity"], "kg")
        if quantity <= 0:
            raise InputRejected("Количество должно быть больше нуля.")
        result.append({
            "variant_id": variant_id,
            "quantity": format(quantity.normalize(), "f"),
            "expected_unit_price": str(price_value(line["expected_unit_price"])),
        })
    return sorted(result, key=lambda row: row["variant_id"])


def _snapshot(reservation):
    return {"id": str(reservation.id), "buyer_id": str(reservation.buyer_id),
            "state": reservation.state, "lines": deepcopy(reservation.lines)}


def reserve_inventory(*, intent_id, lines, context):
    account = buyer(context)
    intent_id = identifier(intent_id)
    request = _request(lines)
    with transaction.atomic():
        reservation, created = InventoryReservation.objects.get_or_create(
            id=intent_id,
            defaults={"buyer_id": account.id, "request": request, "created_at": context.now},
        )
        reservation = InventoryReservation.objects.select_for_update().get(pk=reservation.id)
        if reservation.buyer_id != account.id:
            raise PermissionDenied(_UNAVAILABLE)
        if not created:
            if reservation.request != request:
                raise ConcurrentConflict("Это намерение уже связано с другим составом заказа.")
            return _snapshot(reservation)

        variant_ids = [line["variant_id"] for line in request]
        product_ids = Variant.objects.filter(id__in=variant_ids).values_list("product_id", flat=True)
        products = {row.id: row for row in Product.objects.select_for_update().filter(id__in=product_ids).order_by("id")}
        variants = {str(row.id): row for row in Variant.objects.select_for_update().filter(id__in=variant_ids).order_by("id")}
        snapshot = []
        for line in request:
            variant = variants.get(line["variant_id"])
            if variant is None:
                raise PermissionDenied(_UNAVAILABLE)
            product = products[variant.product_id]
            if product.kind != "physical" or product.owner_id == account.id:
                raise PermissionDenied(_UNAVAILABLE)
            card = get_product(product_id=product.id, variant_id=variant.id, context=context)
            selected = card["selected_variant"]
            if selected is None or selected["id"] != str(variant.id) or variant.price is None:
                raise PermissionDenied(_UNAVAILABLE)
            quantity = stock_value(line["quantity"], product.unit)
            if variant.price != Decimal(line["expected_unit_price"]):
                raise ConcurrentConflict("Цена изменилась. Проверьте заказ перед оплатой.")
            remaining = quantity
            stocks = Stock.objects.select_for_update().filter(
                variant_id=variant.id, quantity__gt=F("reserved_quantity"),
            ).order_by("id")
            for stock in stocks:
                allocated = min(remaining, stock.available_quantity)
                stock.reserved_quantity += allocated
                stock.version += 1
                stock.save(update_fields=("reserved_quantity", "version"))
                InventoryAllocation.objects.create(reservation=reservation, stock=stock, quantity=allocated)
                remaining -= allocated
                if remaining == 0:
                    break
            if remaining:
                raise InputRejected("Недостаточно свободного остатка для заказа.")
            snapshot.append({
                "variant_id": str(variant.id), "product_id": str(product.id),
                "seller_profile_id": str(product.seller_id), "seller_account_id": str(product.owner_id),
                "seller_display_name": card["seller_name"], "title": product.published["title"],
                "variant_label": variant.published["label"], "unit": product.unit,
                "product_version": product.published_version, "variant_version": variant.published_version,
                "unit_price": str(variant.price), "quantity": line["quantity"],
            })
        reservation.lines = snapshot
        reservation.save(update_fields=("lines",))
        return _snapshot(reservation)


def _settle(*, reservation_id, target):
    with transaction.atomic():
        reservation = InventoryReservation.objects.select_for_update().filter(pk=identifier(reservation_id)).first()
        if reservation is None:
            raise PermissionDenied(_UNAVAILABLE)
        if reservation.state == target:
            return _snapshot(reservation)
        if reservation.state != "held":
            raise ConcurrentConflict("Резерв уже завершён другим действием.")
        allocations = list(reservation.allocations.select_related("stock__variant").order_by("stock_id"))
        product_ids = {allocation.stock.variant.product_id for allocation in allocations}
        list(Product.objects.select_for_update().filter(id__in=product_ids).order_by("id"))
        stock_ids = [allocation.stock_id for allocation in allocations]
        stocks = {stock.id: stock for stock in Stock.objects.select_for_update().filter(id__in=stock_ids).order_by("id")}
        for allocation in allocations:
            stock = stocks[allocation.stock_id]
            stock.reserved_quantity -= allocation.quantity
            if target == "committed":
                stock.quantity -= allocation.quantity
            stock.version += 1
            stock.save(update_fields=("quantity", "reserved_quantity", "version"))
        reservation.state = target
        reservation.save(update_fields=("state",))
        return _snapshot(reservation)


# Internal settlement only: callers must reconcile payment/cancellation first.
# These operations must never be exposed directly as buyer or seller endpoints.
def commit_inventory(*, reservation_id):
    return _settle(reservation_id=reservation_id, target="committed")


def release_inventory(*, reservation_id):
    return _settle(reservation_id=reservation_id, target="released")
