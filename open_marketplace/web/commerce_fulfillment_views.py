from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_views import _post_data_is_exact, _render


_MODE_LABELS = {
    "cdek": "СДЭК",
    "seller": "Доставка продавцом",
}
_STATE_LABELS = {
    "pending": "Ожидает планирования",
    "ready": "Готово к передаче",
    "in_transit": "В пути",
    "delivered": "Доставлено",
    "cancelled": "Отменено",
}
_ACTION_LABELS = {
    "ready": "Подготовить к передаче",
    "in_transit": "Передать в доставку",
    "delivered": "Подтвердить получение",
}


def _present(shipment):
    return {
        **shipment,
        "delivery_mode_label": _MODE_LABELS.get(shipment["delivery_mode"], shipment["delivery_mode"]),
        "state_label": _STATE_LABELS.get(shipment["state"], shipment["state"]),
        "actions_with_labels": [
            {"target_state": target, "label": _ACTION_LABELS[target]}
            for target in shipment.get("actions", ())
        ],
    }


def _error(request, error):
    if isinstance(error, PermissionDenied):
        status = 403
        message = "Отгрузка недоступна."
    elif isinstance(error, (ConcurrentConflict, InvalidState)):
        status = 409
        message = str(error) or "Состояние отгрузки уже изменилось."
    else:
        status = 400
        message = str(error) or "Не удалось открыть отгрузку."
    return _render(request, "commerce_fulfillment/error.html", {"message": message}, status=status)


@require_http_methods(["GET"])
@_login_required
def commerce_fulfillment_list(request):
    try:
        shipments = tuple(
            _present(row)
            for row in commerce_public.list_fulfillment_shipments(context=_context(request))
        )
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_fulfillment/list.html", {"shipments": shipments})


@require_http_methods(["GET"])
@_login_required
def commerce_fulfillment_detail(request, *, shipment_id):
    try:
        shipment = _present(
            commerce_public.get_fulfillment_shipment(
                shipment_id=shipment_id,
                context=_context(request),
            )
        )
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_fulfillment/detail.html", {"shipment": shipment})


@require_POST
@_login_required
def commerce_fulfillment_transition(request, *, shipment_id):
    try:
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "target_state"})
        target_state = request.POST.get("target_state")
        commerce_public.transition_fulfillment(
            shipment_id=shipment_id,
            target_state=target_state,
            context=_context(request),
        )
    except (ConcurrentConflict, InputRejected, InvalidState, PermissionDenied) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-fulfillment-detail", kwargs={"shipment_id": shipment_id}))
