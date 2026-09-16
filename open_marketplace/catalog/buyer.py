from django.db import transaction

from open_marketplace.catalog.application import _audit
from open_marketplace.catalog.models import SavedProduct
from open_marketplace.catalog.policy import UNAVAILABLE, buyer, identifier
from open_marketplace.common.errors import PermissionDenied, InputRejected


def _buyer(context):
    return buyer(context)


def set_saved_product(*, product_id, saved, context):
    account = _buyer(context)
    if type(saved) is not bool:
        raise InputRejected("Состояние избранного должно быть логическим значением.")
    product_id = identifier(product_id)
    if not saved:
        with transaction.atomic():
            row = SavedProduct.objects.filter(account_id=account.id, product_id=product_id).first()
            if row is None:
                return
            row.delete()
            _audit(context, "saved_product_remove", row.id, object_type="catalog_saved_product", after={"state": "removed"})
        return

    from open_marketplace.catalog.queries import public_products

    if not any(card["id"] == str(product_id) for card in public_products(context)):
        raise PermissionDenied(UNAVAILABLE)
    with transaction.atomic():
        row, created = SavedProduct.objects.get_or_create(
            account_id=account.id, product_id=product_id, defaults={"created_at": context.now},
        )
        if created:
            _audit(context, "saved_product_add", row.id, object_type="catalog_saved_product", after={"state": "saved"})


def list_saved_products(*, context):
    account = _buyer(context)
    from open_marketplace.catalog.queries import public_products, product_summary

    cards = {card["id"]: card for card in public_products(context)}
    rows = SavedProduct.objects.filter(account_id=account.id).order_by("-created_at", "product_id")
    return [product_summary(cards[str(row.product_id)]) for row in rows if str(row.product_id) in cards]
