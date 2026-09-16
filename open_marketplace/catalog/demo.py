from decimal import Decimal

from django.db.models import Sum

from open_marketplace.catalog.models import Participant, Stock, Variant
from open_marketplace.catalog.policy import participant
from open_marketplace.catalog.queries import get_product
from open_marketplace.common.errors import PermissionDenied
from open_marketplace.seller_onboarding.public import get_public_sellers


def get_demo_participant(*, context, lock=False):
    account = participant(context)
    if lock:
        Participant.objects.select_for_update().get(account_id=account.id)
        account = participant(context)
    return account


def get_demo_offer_snapshot(*, variant_id, context, lock=False):
    variants = Variant.objects.select_related("product")
    if lock:
        variants = variants.select_for_update(of=("self",))
    variant = variants.filter(pk=variant_id).first()
    if variant is None or variant.product.kind != "physical":
        raise PermissionDenied("Заказ недоступен.")
    product = variant.product
    visible = get_product(product_id=product.id, variant_id=variant.id, context=context)
    if visible["selected_variant"]["id"] != str(variant.id):
        raise PermissionDenied("Заказ недоступен.")
    sellers = get_public_sellers(seller_ids=(product.seller_id,))
    if not sellers or variant.price is None:
        raise PermissionDenied("Заказ недоступен.")
    quantity = Stock.objects.filter(variant_id=variant.id, quantity__gt=0).aggregate(total=Sum("quantity"))["total"]
    if quantity is None:
        raise PermissionDenied("Заказ недоступен.")
    return {
        "variant_id": variant.id,
        "product_id": product.id,
        "seller_profile_id": product.seller_id,
        "seller_account_id": product.owner_id,
        "title": product.published["title"],
        "variant_label": variant.published["label"],
        "seller_display_name": sellers[0]["display_name"],
        "unit": product.unit,
        "unit_price": variant.price,
        "initial_quantity": quantity or Decimal("0"),
    }
