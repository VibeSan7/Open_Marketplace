from uuid import uuid4

from django.conf import settings
from django.http import HttpResponseNotFound
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.web.errors import secure_render, secure_response
from open_marketplace.web.identity_views import _context, _redirect_303

from . import public
from .forms import DemoOrderActionForm, DemoOrderForm


def _guard(request):
    if not settings.DEMO_ORDERS_ENABLED:
        return secure_response(HttpResponseNotFound())
    if not getattr(request.user, "is_authenticated", False):
        return _redirect_303(f"{reverse('login')}?next={request.get_full_path()}")
    return None


def _render(request, template, context=None, *, status=200):
    response = secure_render(request, template, context, status=status)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _error(request, error):
    if isinstance(error, PermissionDenied):
        status = 403
        message = "Заказ недоступен."
    elif isinstance(error, ConcurrentConflict) or isinstance(error, InvalidState):
        status = 409
        message = str(error) or "Состояние тестового заказа уже изменилось."
    else:
        status = 400
        message = str(error) or "Не удалось выполнить операцию с тестовым заказом."
    return _render(request, "demo_orders/error.html", {"message": message}, status=status)


def _post_data_is_exact(request, allowed):
    keys = set(request.POST.keys())
    if not keys.issubset(allowed):
        unknown = sorted(keys - allowed)[0]
        raise InputRejected(f"Параметр «{unknown}» не поддерживается.")
    if any(len(values) != 1 for _, values in request.POST.lists()):
        raise InputRejected("Каждый параметр формы должен быть указан ровно один раз.")


@require_http_methods(["GET"])
def demo_orders(request):
    guarded = _guard(request)
    if guarded is not None:
        return guarded
    try:
        orders = public.list_orders(context=_context(request))
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "demo_orders/list.html", {"orders": orders})


@require_http_methods(["GET", "POST"])
def demo_order_create(request, *, variant_id):
    guarded = _guard(request)
    if guarded is not None:
        return guarded
    try:
        offer = public.get_offer_preview(variant_id=variant_id, context=_context(request))
        if request.method == "GET":
            form = DemoOrderForm(initial={"intent_id": str(uuid4())})
            return _render(request, "demo_orders/create.html", {"offer": offer, "form": form})
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "intent_id", "quantity"})
        form = DemoOrderForm(request.POST)
        if not form.is_valid():
            return _render(request, "demo_orders/create.html", {"offer": offer, "form": form}, status=400)
        order = public.create_order(
            variant_id=variant_id,
            quantity=form.cleaned_data["quantity"],
            intent_id=form.cleaned_data["intent_id"],
            context=_context(request),
        )
        return _redirect_303(reverse("demo-order-detail", kwargs={"order_id": order["id"]}))
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)


@require_http_methods(["GET"])
def demo_order_detail(request, *, order_id):
    guarded = _guard(request)
    if guarded is not None:
        return guarded
    try:
        order = public.get_order(order_id=order_id, context=_context(request))
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)
    action_names = (
        ("simulate_success", "Симулировать успешную оплату"),
        ("simulate_decline", "Симулировать отказ оплаты"),
        ("hand_over", "Симулировать передачу продавцом"),
        ("complete", "Симулировать завершение"),
        ("cancel", "Отменить тестовый заказ"),
    )
    actions = tuple(
        {"form": DemoOrderActionForm(initial={"action": action}), "label": label}
        for action, label in action_names
        if action in order["available_actions"]
    )
    return _render(request, "demo_orders/detail.html", {"order": order, "actions": actions})


@require_http_methods(["POST"])
def demo_order_action(request, *, order_id):
    guarded = _guard(request)
    if guarded is not None:
        return guarded
    try:
        _post_data_is_exact(request, {"csrfmiddlewaretoken", "action"})
        form = DemoOrderActionForm(request.POST)
        if not form.is_valid():
            raise InputRejected("Выберите поддерживаемое действие.")
        public.act_on_order(
            order_id=order_id,
            action=form.cleaned_data["action"],
            context=_context(request),
        )
        return _redirect_303(reverse("demo-order-detail", kwargs={"order_id": order_id}))
    except (PermissionDenied, ConcurrentConflict, InvalidState, InputRejected) as error:
        return _error(request, error)
