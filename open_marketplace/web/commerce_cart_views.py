from django.urls import reverse
from django.views.decorators.http import require_http_methods

from open_marketplace.catalog import public as catalog_public
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.errors import secure_render
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_forms import CommerceCartCheckoutForm, CommerceCartQuantityForm


def _render(request, template, context=None, *, status=200):
    response = secure_render(request, template, context, status=status)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _error(request, error, *, cart_view=None):
    if isinstance(error, PermissionDenied):
        status = 403
        message = "Рабочая корзина недоступна."
    elif isinstance(error, ConcurrentConflict):
        status = 409
        message = str(error) or "Содержимое корзины уже изменилось."
    elif isinstance(error, InvalidState):
        status = 409
        message = str(error) or "Это действие сейчас недоступно."
    else:
        status = 400
        message = str(error) or "Не удалось изменить рабочую корзину."
    return _render(
        request,
        "commerce_cart/error.html",
        {"message": message, "cart": cart_view},
        status=status,
    )


def _post_data_is_exact(request, allowed):
    keys = set(request.POST.keys())
    if not keys.issubset(allowed):
        unknown = sorted(keys - allowed)[0]
        raise InputRejected(f"Параметр «{unknown}» не поддерживается.")
    if any(len(values) != 1 for _, values in request.POST.lists()):
        raise InputRejected("Каждый параметр формы должен быть указан ровно один раз.")


def _decorate_cart(request, cart_view):
    for item in cart_view["items"]:
        item["product_url"] = (
            f"{reverse('catalog-product', kwargs={'product_id': item['product_id']})}"
            f"?variant={item['variant_id']}"
        )
    return cart_view


@require_http_methods(["GET"])
@_login_required
def commerce_cart(request):
    try:
        cart_view = _decorate_cart(
            request,
            commerce_public.get_commerce_cart(context=_context(request)),
        )
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_cart/cart.html", {"cart": cart_view})


@require_http_methods(["POST"])
@_login_required
def commerce_cart_add(request, *, variant_id):
    try:
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "quantity"})
        form = CommerceCartQuantityForm(request.POST)
        if not form.is_valid():
            raise InputRejected("Укажите корректное количество.")
        commerce_public.add_commerce_cart_item(
            variant_id=variant_id,
            quantity=form.cleaned_data["quantity"],
            context=_context(request),
        )
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-cart"))


@require_http_methods(["POST"])
@_login_required
def commerce_cart_update(request, *, variant_id):
    try:
        if request.POST.get("action") == "remove":
            _post_data_is_exact(request, {"csrfmiddlewaretoken", "action"})
            commerce_public.remove_commerce_cart_item(
                variant_id=variant_id,
                context=_context(request),
            )
        else:
            _post_data_is_exact(request, {"csrfmiddlewaretoken", "quantity"})
            form = CommerceCartQuantityForm(request.POST)
            if not form.is_valid():
                raise InputRejected("Укажите корректное количество.")
            commerce_public.update_commerce_cart_item(
                variant_id=variant_id,
                quantity=form.cleaned_data["quantity"],
                context=_context(request),
            )
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-cart"))


@require_http_methods(["GET", "POST"])
@_login_required
def commerce_cart_checkout(request):
    try:
        cart_view = _decorate_cart(
            request,
            commerce_public.get_commerce_cart(context=_context(request)),
        )
        if request.method == "GET":
            form = CommerceCartCheckoutForm(initial={"intent_id": cart_view["intent_id"]})
            return _render(
                request,
                "commerce_cart/checkout.html",
                {"cart": cart_view, "form": form},
            )
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "intent_id"})
        form = CommerceCartCheckoutForm(request.POST)
        if not form.is_valid():
            raise InputRejected("Неверный идентификатор корзины.")
        orders = commerce_public.checkout_commerce_cart(
            intent_id=form.cleaned_data["intent_id"],
            context=_context(request),
        )
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error, cart_view=locals().get("cart_view"))
    return _render(
        request,
        "commerce_cart/checkout.html",
        {"cart": cart_view, "orders": orders},
    )
