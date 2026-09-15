from copy import deepcopy

from open_marketplace.catalog.common_cards import compose_common_cards

from open_marketplace.catalog.domain import UNITS, price_label
from open_marketplace.catalog.models import Category, Participant, Photo, Product, StorageLocation, Variant
from open_marketplace.catalog.photos import photo_path
from open_marketplace.catalog.policy import UNAVAILABLE, identifier, manager, owned_product, participant, seller
from open_marketplace.common.errors import PermissionDenied
from open_marketplace.identity.public import get_account_snapshot
from open_marketplace.seller_onboarding.public import get_public_sellers


def list_categories(*, context, include_inactive=False):
    participant(context)
    query = Category.objects.prefetch_related("attributes")
    if include_inactive:
        manager(context, write=False)
    else:
        query = query.filter(active=True)
    return [{"id": str(category.id), "name": category.name, "active": category.active, "version": category.version,
             "attributes": [{"key": item.key, "label": item.label, "required": item.required, "values": item.values} for item in category.attributes.all()]}
            for category in query]


def get_own_product(*, product_id, context):
    product = owned_product(product_id, context)
    locations = list(StorageLocation.objects.filter(seller_id=product.seller_id)) if product.seller_id else []
    variants = []
    for variant in product.variants.prefetch_related("stocks__location"):
        stocks = {row.location_id: row for row in variant.stocks.all()}
        variants.append({"id": str(variant.id), "draft": deepcopy(variant.draft), "published": deepcopy(variant.published),
            "state": variant.state, "restore_requested": variant.restore_version is not None,
            "blocked": variant.blocked, "block_reason": variant.block_reason, "price": variant.price, "price_version": variant.price_version,
            "stocks": [{"location_id": str(location.id), "location_name": location.name,
                "quantity": stocks[location.id].quantity if location.id in stocks else None,
                "version": stocks[location.id].version if location.id in stocks else 0} for location in locations]})
    return {"id": str(product.id), "kind": product.kind, "unit": product.unit, "unit_label": UNITS[product.unit], "unit_locked": product.unit_locked,
        "draft": deepcopy(product.draft), "published": deepcopy(product.published), "draft_version": product.draft_version, "published_version": product.published_version,
        "blocked": product.blocked, "block_reason": product.block_reason, "variants": variants,
        "locations": [{"id": str(row.id), "name": row.name} for row in locations],
        "photos": [{"id": str(row.id), "width": row.width, "height": row.height, "available": photo_path(row.id).is_file()} for row in product.photos.order_by("created_at", "id")]}


def list_own_products(*, context):
    account = participant(context)
    if account.kind == "service":
        manager(context, write=False)
        query = Product.objects.filter(kind="common")
    else:
        profile = seller(context)
        query = Product.objects.filter(owner_id=account.id, seller_id=profile.id)
    return [{"id": str(row.id), "title": row.draft.get("title") or "Без названия", "kind": row.kind,
             "published": row.published is not None, "blocked": row.blocked, "unit": UNITS[row.unit]} for row in query]


def list_common_cards(*, context):
    participant(context)
    categories = {str(row.id) for row in Category.objects.filter(active=True)}
    return [{"id": str(row.id), "title": row.published["title"], "unit": row.unit,
             "category_id": row.published["category_id"],
             "variants": [{"id": str(variant.id), "label": variant.published["label"],
                           "attributes": deepcopy(variant.published["attributes"])}
                          for variant in row.variants.all()
                          if variant.state == "published" and not variant.blocked and variant.published is not None]}
            for row in Product.objects.filter(kind="common", blocked=False, published__isnull=False).prefetch_related("variants")
            if row.published["category_id"] in categories]


def list_matching_targets(*, source_variant_id, context):
    seller(context)
    source = Variant.objects.filter(pk=identifier(source_variant_id)).first()
    if source is None:
        raise PermissionDenied(UNAVAILABLE)
    product = owned_product(source.product_id, context)
    if product.kind != "physical" or product.blocked or product.published is None or source.state != "published" or source.blocked:
        return []
    return [{**variant, "title": card["title"], "product_id": card["id"]}
            for card in list_common_cards(context=context)
            if card["unit"] == product.unit and card["category_id"] == product.published["category_id"]
            for variant in card["variants"]]


def list_moderation_cards(*, context):
    manager(context, write=False)
    return [{"id": str(row.id), "title": row.published["title"], "description": row.published["description"],
             "kind": row.kind, "unit": UNITS[row.unit], "blocked": row.blocked, "block_reason": row.block_reason,
             "variants": [{"id": str(variant.id), "label": variant.published["label"],
                           "attributes": deepcopy(variant.published["attributes"]), "state": variant.state,
                           "blocked": variant.blocked, "block_reason": variant.block_reason}
                          for variant in row.variants.all() if variant.published is not None]}
            for row in Product.objects.filter(published__isnull=False).prefetch_related("variants")]


def list_participants(*, context):
    manager(context, write=False)
    return [{"id": str(row.account_id), "email": get_account_snapshot(row.account_id).email, "allowed": row.allowed}
            for row in Participant.objects.order_by("account_id")]


def _available_photos(product, ids):
    owned = {str(value) for value in product.photos.filter(id__in=ids).values_list("id", flat=True)}
    return [value for value in ids if value in owned and photo_path(value).is_file()]


def public_products(context):
    participant(context)
    products = list(Product.objects.filter(published__isnull=False, blocked=False).exclude(kind="digital").prefetch_related("variants__stocks", "photos"))
    seller_ids = tuple({row.seller_id for row in products if row.seller_id is not None})
    sellers = {row["id"]: row for row in get_public_sellers(seller_ids=seller_ids)}
    allowed_owners = set(Participant.objects.filter(allowed=True).values_list("account_id", flat=True))
    categories = {str(row.id): row.name for row in Category.objects.filter(active=True)}
    result = []
    for product in products:
        if product.kind != "common" and (str(product.seller_id) not in sellers or product.owner_id not in allowed_owners):
            continue
        content = product.published
        if content["category_id"] not in categories:
            continue
        variants = []
        for variant in product.variants.all():
            if variant.state != "published" or variant.blocked or variant.published is None:
                continue
            data = variant.published
            in_stock = any(row.quantity is not None and row.quantity > 0 for row in variant.stocks.all())
            offers = []
            if product.seller_id and variant.price is not None:
                offers.append({"variant_id": str(variant.id), "product_id": str(product.id), "seller_name": sellers[str(product.seller_id)]["display_name"], "price": variant.price, "in_stock": in_stock})
            variants.append({"id": str(variant.id), "label": data["label"], "attributes": deepcopy(data["attributes"]),
                "photo_ids": _available_photos(product, data["photo_ids"]), "price": variant.price,
                "price_label": price_label(variant.price) if variant.price is not None else "Нет предложений", "in_stock": in_stock, "offers": offers})
        if not variants:
            continue
        cover = _available_photos(product, [content["cover_id"]]) if content.get("cover_id") else []
        result.append({"id": str(product.id), "kind": product.kind, "title": content["title"], "description": content["description"],
            "category_id": content["category_id"], "category": categories[content["category_id"]], "attributes": deepcopy(content["attributes"]),
            "unit": product.unit, "unit_label": UNITS[product.unit], "cover_id": cover[0] if cover else None, "variants": variants})
    return compose_common_cards(result)


def get_product(*, product_id, context, variant_id=None, filters=None, category_id=None, from_search=False):
    from open_marketplace.catalog.search import validate_filters

    product_id = str(identifier(product_id))
    cards = public_products(context)
    filters, category_id, _ = validate_filters(cards=cards, categories=list_categories(context=context), filters=filters, category_id=category_id)
    product = next((row for row in cards if row["id"] == product_id), None)
    if product is None:
        raise PermissionDenied(UNAVAILABLE)
    variants = product["variants"]
    selected = None
    if variant_id is not None:
        requested = str(identifier(variant_id))
        selected = next((row for row in variants if row["id"] == requested), None)
        if selected is None:
            product["selection_message"] = "Указанный вариант недоступен. Другой вариант не выбран автоматически."
    else:
        matches = [row for row in variants if row["in_stock"] and row["price"] is not None
            and (not from_search or not row.get("grouped"))
            and (category_id is None or product["category_id"] == category_id)
            and all(row["attributes"].get(key) in values for key, values in filters.items())]
        if matches:
            selected = min(matches, key=lambda row: (row["price"], row["id"]))
        else:
            product["selection_message"] = "Подходящих вариантов в наличии нет. Можно посмотреть доступные варианты без покупки."
    product["selected_variant_id"] = selected["id"] if selected else None
    product["selected_variant"] = selected
    return product


def get_photo(*, photo_id, context):
    account = participant(context)
    photo = Photo.objects.select_related("product").filter(pk=identifier(photo_id)).first()
    if photo is None:
        raise PermissionDenied("Фото недоступно.")
    product = photo.product
    if product.owner_id == account.id or (product.kind == "common" and account.kind == "service"):
        owned_product(product.id, context)
    else:
        view = get_product(product_id=product.id, context=context)
        allowed = {view["cover_id"]}
        for variant in view["variants"]:
            allowed.update(variant["photo_ids"])
        if str(photo.id) not in allowed:
            raise PermissionDenied("Фото недоступно.")
    try:
        return photo_path(photo.id).open("rb")
    except FileNotFoundError:
        raise PermissionDenied("Фото недоступно.") from None
