from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_views import _post_data_is_exact, _render


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
        orders = commerce_public.list_orders(context=_context(request))
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_orders/list.html", {"orders": orders})


@require_http_methods(["GET"])
@_login_required
def commerce_order_detail(request, *, order_id):
    try:
        order = commerce_public.get_order(order_id=order_id, context=_context(request))
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_orders/detail.html", {"order": order})


@require_POST
@_login_required
def commerce_order_cancel(request, *, order_id):
    try:
        _post_data_is_exact(request, {"csrfmiddlewaretoken"})
        commerce_public.cancel_order(order_id=order_id, context=_context(request))
    except (ConcurrentConflict, InputRejected, InvalidState, PermissionDenied) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-order-detail", kwargs={"order_id": order_id}))
