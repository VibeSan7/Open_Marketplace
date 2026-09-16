from django.conf import settings
from django.http import HttpResponseNotFound
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.web.errors import secure_render, secure_response
from open_marketplace.web.identity_views import _context, _redirect_303

from . import cart as cart_public
from .cart_forms import CartCheckoutForm, CartQuantityForm


def _redirect_login(request):
    return _redirect_303(f"{reverse('login')}?next={request.get_full_path()}")


def _guard(request, *, disabled_page=False):
    if not getattr(request.user, "is_authenticated", False):
        if disabled_page and not settings.DEMO_ORDERS_ENABLED:
            return None
        return _redirect_login(request)
    return None


def _render(request, template, context=None, *, status=200):
    response = secure_render(request, template, context, status=status)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _disabled_cart():
    return {
        "enabled": False,
        "items": (),
        "sellers": (),
        "item_count": 0,
        "total": 0,
        "checkout_available": False,
        "errors": ("Демонстрация заказов отключена: оформить заказ нельзя.",),
    }


def _error(request, error, *, cart_view=None):
    if isinstance(error, PermissionDenied):
        status = 403
        message = "Корзина недоступна."
    elif isinstance(error, (ConcurrentConflict, InvalidState)):
        status = 409
        message = str(error) or "Содержимое корзины уже изменилось."
    else:
        status = 400
        message = str(error) or "Не удалось изменить корзину."
    return _render(request, "cart/error.html", {"message": message, "cart": cart_view}, status=status)


def _post_data_is_exact(request, allowed):
    keys = set(request.POST.keys())
    if not keys.issubset(allowed):
        unknown = sorted(keys - allowed)[0]
        raise InputRejected(f"Параметр «{unknown}» не поддерживается.")
    if any(len(values) != 1 for _, values in request.POST.lists()):
        raise InputRejected("Каждый параметр формы должен быть указан ровно один раз.")


@require_http_methods(["GET"])
def cart(request):
    guarded = _guard(request, disabled_page=True)
    if guarded is not None:
        return guarded
    if not settings.DEMO_ORDERS_ENABLED and not getattr(request.user, "is_authenticated", False):
        return _render(request, "cart/cart.html", {"cart": _disabled_cart()})
    try:
        cart_view = cart_public.get_cart(context=_context(request))
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "cart/cart.html", {"cart": cart_view})


@require_http_methods(["POST"])
def cart_add(request, *, variant_id):
    guarded = _guard(request)
    if guarded is not None:
        return guarded
    try:
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "quantity"})
        form = CartQuantityForm(request.POST)
        if not form.is_valid():
            raise InputRejected("Укажите корректное количество.")
        cart_public.add_cart_item(variant_id=variant_id, quantity=form.cleaned_data["quantity"], context=_context(request))
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)
    return _redirect_303(reverse("cart"))


@require_http_methods(["POST"])
def cart_update(request, *, variant_id):
    guarded = _guard(request)
    if guarded is not None:
        return guarded
    try:
        if request.POST.get("action") == "remove":
            _post_data_is_exact(request, {"csrfmiddlewaretoken", "action"})
            cart_public.remove_cart_item(variant_id=variant_id, context=_context(request))
        else:
            _post_data_is_exact(request, {"csrfmiddlewaretoken", "quantity"})
            form = CartQuantityForm(request.POST)
            if not form.is_valid():
                raise InputRejected("Укажите корректное количество.")
            cart_public.update_cart_item(variant_id=variant_id, quantity=form.cleaned_data["quantity"], context=_context(request))
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)
    return _redirect_303(reverse("cart"))


@require_http_methods(["GET", "POST"])
def cart_checkout(request):
    guarded = _guard(request, disabled_page=True)
    if guarded is not None:
        return guarded
    if not settings.DEMO_ORDERS_ENABLED and not getattr(request.user, "is_authenticated", False):
        return _render(request, "cart/checkout.html", {"cart": _disabled_cart()})
    try:
        cart_view = cart_public.get_cart(context=_context(request))
        if request.method == "GET":
            form = CartCheckoutForm(initial={"intent_id": cart_view["intent_id"]})
            return _render(request, "cart/checkout.html", {"cart": cart_view, "form": form})
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "intent_id"})
        form = CartCheckoutForm(request.POST)
        if not form.is_valid():
            raise InputRejected("Неверный идентификатор корзины.")
        orders = cart_public.checkout_cart(intent_id=form.cleaned_data["intent_id"], context=_context(request))
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error, cart_view=locals().get("cart_view"))
    return _render(request, "cart/checkout.html", {"cart": cart_view, "orders": orders})
