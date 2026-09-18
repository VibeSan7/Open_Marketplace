from django.views.decorators.http import require_http_methods

from open_marketplace.common.errors import InputRejected, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required

from .commerce_cart_views import _render


def _error(request, error):
    if isinstance(error, PermissionDenied):
        status = 403
        message = "Заказ недоступен."
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
