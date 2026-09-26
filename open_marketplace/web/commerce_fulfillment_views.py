import re

from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_views import _post_data_is_exact, _render
from .commerce_fulfillment_forms import FulfillmentPackageFormSet


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
_PACKAGE_PREFIX = "packages"
_PACKAGE_FIELDS = {"weight_grams", "length_cm", "width_cm", "height_cm", "DELETE"}
_PACKAGE_MANAGEMENT_FIELDS = {
    f"{_PACKAGE_PREFIX}-{name}"
    for name in ("TOTAL_FORMS", "INITIAL_FORMS", "MIN_NUM_FORMS", "MAX_NUM_FORMS")
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


def _package_formset(*, data=None, packages=()):
    return FulfillmentPackageFormSet(
        data=data,
        initial=tuple(packages),
        prefix=_PACKAGE_PREFIX,
    )


def _validate_package_post(request):
    allowed = {"csrfmiddlewaretoken", *_PACKAGE_MANAGEMENT_FIELDS}
    pattern = re.compile(
        rf"{re.escape(_PACKAGE_PREFIX)}-\d+-({'|'.join(sorted(_PACKAGE_FIELDS))})$"
    )
    for key in request.POST:
        if key not in allowed and not pattern.fullmatch(key):
            raise InputRejected(f"Параметр «{key}» не поддерживается.")
    if any(len(values) != 1 for _, values in request.POST.lists()):
        raise InputRejected("Каждый параметр формы должен быть указан ровно один раз.")


def _package_rows(formset):
    return [
        {
            field: form.cleaned_data[field]
            for field in ("weight_grams", "length_cm", "width_cm", "height_cm")
        }
        for form in formset
        if form.cleaned_data and not form.cleaned_data.get("DELETE")
    ]


def _detail_context(shipment, context, *, package_formset=None):
    shipment = _present(shipment)
    can_edit_packages = (
        str(context.actor_account_id) == shipment["seller_account_id"]
        and shipment["state"] == "pending"
    )
    if can_edit_packages and package_formset is None:
        package_formset = _package_formset(packages=shipment.get("packages", ()))
    return {
        "shipment": shipment,
        "can_edit_packages": can_edit_packages,
        "package_formset": package_formset,
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
        context = _context(request)
        shipment = commerce_public.get_fulfillment_shipment(
            shipment_id=shipment_id,
            context=context,
        )
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(
        request,
        "commerce_fulfillment/detail.html",
        _detail_context(shipment, context),
    )


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


@require_POST
@_login_required
def commerce_fulfillment_packages(request, *, shipment_id):
    try:
        _validate_package_post(request)
        context = _context(request)
        shipment = commerce_public.get_fulfillment_shipment(
            shipment_id=shipment_id,
            context=context,
        )
        if str(context.actor_account_id) != shipment["seller_account_id"]:
            raise PermissionDenied("Отгрузка недоступна.")
        if shipment["state"] != "pending":
            raise InvalidState("Упаковку можно изменить только для ожидающей отгрузки.")
        formset = _package_formset(data=request.POST, packages=shipment.get("packages", ()))
        if not formset.is_valid():
            return _render(
                request,
                "commerce_fulfillment/detail.html",
                _detail_context(shipment, context, package_formset=formset),
                status=400,
            )
        commerce_public.set_fulfillment_packages(
            shipment_id=shipment_id,
            packages=_package_rows(formset),
            context=context,
        )
    except (ConcurrentConflict, InputRejected, InvalidState, PermissionDenied) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-fulfillment-detail", kwargs={"shipment_id": shipment_id}))
