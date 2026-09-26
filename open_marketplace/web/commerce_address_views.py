from django.urls import reverse
from django.views.decorators.http import require_http_methods

from open_marketplace.common.errors import InputRejected, PermissionDenied
from open_marketplace.commerce import public as commerce_public
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303

from .commerce_cart_forms import CommerceDeliveryAddressForm
from .commerce_cart_views import _post_data_is_exact, _render


_ADDRESS_POST_FIELDS = {
    "csrfmiddlewaretoken",
    "label",
    "recipient_name",
    "phone",
    "postal_code",
    "region",
    "city",
    "street",
    "building",
    "apartment",
    "comment",
}


def _error(request, error):
    status = 403 if isinstance(error, PermissionDenied) else 400
    message = str(error) or "Не удалось сохранить адрес доставки."
    return _render(request, "commerce_addresses/error.html", {"message": message}, status=status)


@require_http_methods(["GET"])
@_login_required
def commerce_address_list(request):
    try:
        addresses = commerce_public.list_delivery_addresses(context=_context(request))
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _render(request, "commerce_addresses/list.html", {"addresses": addresses})


@require_http_methods(["GET", "POST"])
@_login_required
def commerce_address_new(request):
    if request.method == "GET":
        return _render(
            request,
            "commerce_addresses/form.html",
            {"form": CommerceDeliveryAddressForm()},
        )
    try:
        _post_data_is_exact(request, _ADDRESS_POST_FIELDS)
        form = CommerceDeliveryAddressForm(request.POST)
        if not form.is_valid():
            raise InputRejected("Заполните обязательные поля адреса.")
        commerce_public.create_delivery_address(
            data=form.cleaned_data,
            context=_context(request),
        )
    except (PermissionDenied, InputRejected) as error:
        return _error(request, error)
    return _redirect_303(reverse("commerce-address-list"))
