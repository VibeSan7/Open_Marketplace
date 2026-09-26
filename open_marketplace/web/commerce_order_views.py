from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_views import _post_data_is_exact, _render


_FULFILLMENT_MODE_LABELS = {
    "cdek": "СДЭК",
    "seller": "Доставка продавцом",
}
_FULFILLMENT_STATE_LABELS = {
    "pending": "Ожидает планирования",
    "ready": "Готово к передаче",
    "in_transit": "В пути",
    "delivered": "Доставлено",
    "cancelled": "Отменено",
}


def _shipment_summary(shipment):
    return {
        "id": shipment["id"],
        "state_label": _FULFILLMENT_STATE_LABELS.get(
            shipment["state"], shipment["state"]
        ),
        "delivery_mode_label": _FULFILLMENT_MODE_LABELS.get(
            shipment["delivery_mode"], shipment["delivery_mode"]
        ),
        "detail_url": reverse(
            "commerce-fulfillment-detail",
            kwargs={"shipment_id": shipment["id"]},
        ),
    }


def _fulfillment_summaries(*, order, context):
    return tuple(
        _shipment_summary(shipment)
        for shipment in commerce_public.list_fulfillment_shipments(context=context)
        if shipment["order_id"] == order["id"]
    )


def _orders_with_fulfillment(*, orders, context):
    shipments_by_order = {}
    for shipment in commerce_public.list_fulfillment_shipments(context=context):
        shipments_by_order.setdefault(shipment["order_id"], []).append(
            _shipment_summary(shipment)
        )
    return tuple(
        {
            **order,
            "fulfillment_summaries": tuple(shipments_by_order.get(order["id"], ())),
        }
        for order in orders
    )


def _error(request, error):
    if isinstance(error, PermissionDenied):
        status = 403
        message = "Заказ недоступен."
    elif isinstance(error, (ConcurrentConflict, InvalidState)):
        status = 409
        message = str(error) or "Состояние заказа уже изменилось."
    else:
        status = 400
        message = str(error) or "Не удалось открыть заказ."
    return _render(request, "commerce_orders/error.html", {"message": message}, status=status)


@require_http_methods(["GET"])
@_login_required
def commerce_order_list(request):
    try:
        context = _context(request)
        orders = commerce_public.list_orders(context=context)
        orders = _orders_with_fulfillment(orders=orders, context=context)
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_orders/list.html", {"orders": orders})


@require_http_methods(["GET"])
@_login_required
def commerce_order_detail(request, *, order_id):
    try:
        context = _context(request)
        order = commerce_public.get_order(order_id=order_id, context=context)
        fulfillment_shipments = _fulfillment_summaries(order=order, context=context)
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(
        request,
        "commerce_orders/detail.html",
        {"order": order, "fulfillment_shipments": fulfillment_shipments},
    )


@require_POST
@_login_required
def commerce_order_cancel(request, *, order_id):
    try:
        _post_data_is_exact(request, {"csrfmiddlewaretoken"})
        commerce_public.cancel_order(order_id=order_id, context=_context(request))
    except (ConcurrentConflict, InputRejected, InvalidState, PermissionDenied) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-order-detail", kwargs={"order_id": order_id}))
