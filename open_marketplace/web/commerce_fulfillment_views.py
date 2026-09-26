import re

from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_views import _post_data_is_exact, _render
from .commerce_fulfillment_forms import fulfillment_package_formset


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
_EVENT_ACTION_LABELS = {
    "planned": "Отгрузка запланирована",
    "ready": "Подготовлена к передаче",
    "in_transit": "Передана в доставку",
    "delivered": "Получение подтверждено",
}
_STATE_FILTERS = tuple(_STATE_LABELS.items())
_PACKAGE_PREFIX = "packages"
_PACKAGE_FIELDS = {"weight_grams", "length_cm", "width_cm", "height_cm", "DELETE"}
_PACKAGE_LINE_FIELD = r"line_\d+"
_PACKAGE_MANAGEMENT_FIELDS = {
    f"{_PACKAGE_PREFIX}-{name}"
    for name in ("TOTAL_FORMS", "INITIAL_FORMS", "MIN_NUM_FORMS", "MAX_NUM_FORMS")
}


def _present(shipment):
    lines = shipment.get("lines", ())
    packages = []
    for package in shipment.get("packages", ()):
        items = []
        for item in package.get("items", ()):
            line_index = item["line_index"]
            line = lines[line_index] if 0 <= line_index < len(lines) else {}
            items.append({
                **item,
                "label": " · ".join(
                    value
                    for value in (line.get("title"), line.get("variant_label"))
                    if value
                ) or f"Позиция {line_index + 1}",
            })
        packages.append({**package, "items_with_labels": items})
    lines_with_labels = [
        {
            **line,
            "label": " · ".join(
                value
                for value in (line.get("title"), line.get("variant_label"))
                if value
            ) or f"Позиция {index + 1}",
        }
        for index, line in enumerate(shipment.get("lines", ()))
    ]
    events = [
        {
            **event,
            "state_label": _STATE_LABELS.get(event["state"], event["state"]),
            "action_label": _EVENT_ACTION_LABELS.get(event["action"], event["action"]),
        }
        for event in shipment.get("events", ())
    ]
    package_count = len(shipment["packages"]) if "packages" in shipment else None
    return {
        **shipment,
        "packages": packages,
        "package_count": package_count,
        "lines_with_labels": lines_with_labels,
        "events_with_labels": events,
        "delivery_mode_label": _MODE_LABELS.get(shipment["delivery_mode"], shipment["delivery_mode"]),
        "state_label": _STATE_LABELS.get(shipment["state"], shipment["state"]),
        "actions_with_labels": [
            {"target_state": target, "label": _ACTION_LABELS[target]}
            for target in shipment.get("actions", ())
        ],
    }


def _package_formset(*, data=None, packages=(), lines=()):
    return fulfillment_package_formset(
        data=data,
        packages=tuple(packages),
        lines=tuple(lines),
    )


def _validate_package_post(request):
    allowed = {"csrfmiddlewaretoken", *_PACKAGE_MANAGEMENT_FIELDS}
    pattern = re.compile(
        rf"{re.escape(_PACKAGE_PREFIX)}-\d+-({'|'.join(sorted(_PACKAGE_FIELDS))}|{_PACKAGE_LINE_FIELD})$"
    )
    for key in request.POST:
        if key not in allowed and not pattern.fullmatch(key):
            raise InputRejected(f"Параметр «{key}» не поддерживается.")
    if any(len(values) != 1 for _, values in request.POST.lists()):
        raise InputRejected("Каждый параметр формы должен быть указан ровно один раз.")


def _package_rows(formset):
    rows = []
    for form in formset:
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            continue
        items = [
            {"line_index": int(field.removeprefix("line_")), "quantity": value}
            for field, value in form.cleaned_data.items()
            if field.startswith("line_") and value
        ]
        rows.append({
            **{
                field: form.cleaned_data[field]
                for field in ("weight_grams", "length_cm", "width_cm", "height_cm")
            },
            "items": items,
        })
    return rows


def _detail_context(shipment, context, *, package_formset=None):
    shipment = _present(shipment)
    can_edit_packages = (
        str(context.actor_account_id) == shipment["seller_account_id"]
        and shipment["state"] == "pending"
    )
    if can_edit_packages and package_formset is None:
        package_formset = _package_formset(
            packages=shipment.get("packages", ()),
            lines=shipment.get("lines", ()),
        )
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


def _state_filter(request):
    unknown = set(request.GET) - {"state"}
    if unknown:
        raise InputRejected("Параметр фильтра не поддерживается.")
    values = request.GET.getlist("state")
    if len(values) > 1:
        raise InputRejected("Состояние фильтра должно быть указано один раз.")
    if not values:
        return None
    state = values[0]
    if state not in _STATE_LABELS:
        raise InputRejected("Указано неподдерживаемое состояние отгрузки.")
    return state


@require_http_methods(["GET"])
@_login_required
def commerce_fulfillment_list(request):
    try:
        state = _state_filter(request)
        shipments = tuple(
            _present(row)
            for row in commerce_public.list_fulfillment_shipments(context=_context(request))
        )
        if state is not None:
            shipments = tuple(row for row in shipments if row["state"] == state)
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(
        request,
        "commerce_fulfillment/list.html",
        {
            "shipments": shipments,
            "active_state_label": _STATE_LABELS.get(state),
            "state_filters": tuple(
                {"value": value, "label": label, "active": value == state}
                for value, label in _STATE_FILTERS
            ),
        },
    )


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
        formset = _package_formset(
            data=request.POST,
            packages=shipment.get("packages", ()),
            lines=shipment.get("lines", ()),
        )
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
