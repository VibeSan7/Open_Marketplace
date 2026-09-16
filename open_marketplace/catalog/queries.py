from copy import deepcopy

from open_marketplace.catalog.application import _publication_data
from open_marketplace.catalog.common_cards import compose_common_cards

from open_marketplace.catalog.domain import UNITS, price_label, price_limited_variant, price_range
from open_marketplace.catalog.models import Category, Participant, Photo, Product, SavedProduct, StorageLocation, Variant
from open_marketplace.catalog.photos import photo_path
from open_marketplace.catalog.policy import UNAVAILABLE, identifier, manager, owned_product, participant, seller
from open_marketplace.common.errors import InputRejected, PermissionDenied
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


def get_publication_readiness(*, product_id, context):
    product = owned_product(product_id, context)
    variants = [row for row in product.variants.prefetch_related("stocks")
                if not row.blocked and (row.state != "withdrawn" or row.restore_version == row.withdrawal_version)]
    issues = []
    changed = None
    preview = None
    if product.blocked:
        issues.append("Карточка заблокирована. Публикация недоступна.")
    elif product.kind == "digital":
        issues.append("Цифровые карточки пока доступны только как черновики.")
    else:
        try:
            content, published_variants = _publication_data(product)
            changed = content != product.published or any(
                row.state != "published" or data != row.published for row, data in published_variants)
            category = Category.objects.prefetch_related("attributes").get(pk=content["category_id"])
            labels = {attribute.key: attribute.label for attribute in category.attributes.all()}
            preview = {**deepcopy(content), "id": str(product.id), "kind": product.kind,
                "category": category.name, "unit_label": UNITS[product.unit],
                "variants": [{**deepcopy(data), "id": str(row.id),
                    "attribute_items": [{"label": labels.get(key, key), "value": value} for key, value in data["attributes"].items()],
                    "price_label": price_label(row.price) if row.price is not None else "Цены берутся из предложений продавцов",
                    "in_stock": any(stock.quantity is not None and stock.quantity > 0 for stock in row.stocks.all())}
                    for row, data in published_variants]}
        except InputRejected as exc:
            issues.append(str(exc))
    try:
        get_product(product_id=product.id, context=context)
        can_view_published = True
    except PermissionDenied:
        can_view_published = False
    checks = [
        {"label": "Название и описание", "complete": bool(product.draft.get("title") and product.draft.get("description"))},
        {"label": "Действующая категория", "complete": Category.objects.filter(pk=product.draft.get("category_id"), active=True).exists()},
        {"label": "Варианты с названиями", "complete": bool(variants) and all(row.draft.get("label") for row in variants)},
        {"label": "Доступные фотографии вариантов", "complete": bool(variants) and all(
            row.draft.get("photo_ids") and _available_photos(product, row.draft["photo_ids"]) == row.draft["photo_ids"] for row in variants)},
        {"label": "Цена и остаток", "complete": bool(variants) and (product.kind == "common" or all(
            row.price is not None and bool(row.stocks.all()) and all(stock.quantity is not None for stock in row.stocks.all()) for row in variants))},
        {"label": "Все требования публикации", "complete": not issues},
    ]
    return {"ready": not issues, "issues": issues, "checks": checks,
            "can_view_published": can_view_published, "has_unpublished_changes": changed, "preview": preview}


def list_own_products(*, context):
    account = participant(context)
    if account.kind == "service":
        manager(context, write=False)
        query = Product.objects.filter(kind="common")
    else:
        profile = seller(context)
        query = Product.objects.filter(owner_id=account.id, seller_id=profile.id)
    visible_ids = {row["id"] for row in public_products(context)}
    result = []
    for row in query.prefetch_related("variants__stocks"):
        variants = list(row.variants.all())
        active_variants = [variant for variant in variants if not variant.blocked and variant.state != "withdrawn"]
        prices = [variant.price for variant in active_variants if variant.price is not None]
        stocks = [stock.quantity for variant in active_variants for stock in variant.stocks.all()]
        if row.blocked:
            status = "Заблокирована"
        elif row.published is None:
            status = "Черновик"
        elif variants and all(variant.state == "withdrawn" for variant in variants):
            status = "Снята с продажи"
        elif str(row.id) not in visible_ids:
            status = "Не видна покупателям"
        else:
            status = "Опубликована"
        if row.kind == "common":
            amount, availability = "Цены продавцов", "Предложения продавцов"
        else:
            amount = price_label(min(prices), different=min(prices) != max(prices)) if prices else "Цена не указана"
            availability = "В наличии" if any(value is not None and value > 0 for value in stocks) else (
                "Нет в наличии" if stocks and all(value is not None for value in stocks) else "Остаток не заполнен")
        result.append({"id": str(row.id), "title": row.draft.get("title") or "Без названия", "kind": row.kind,
            "kind_label": {"physical": "Физический товар", "digital": "Цифровой черновик", "common": "Общая карточка"}[row.kind],
            "published": row.published is not None, "blocked": row.blocked, "unit": UNITS[row.unit],
            "status_label": status, "price_label": amount, "availability_label": availability,
            "can_view_published": str(row.id) in visible_ids})
    return result


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
                offers.append({"variant_id": str(variant.id), "product_id": str(product.id), "seller_id": str(product.seller_id), "seller_name": sellers[str(product.seller_id)]["display_name"], "price": variant.price, "in_stock": in_stock})
            variants.append({"id": str(variant.id), "label": data["label"], "attributes": deepcopy(data["attributes"]),
                "photo_ids": _available_photos(product, data["photo_ids"]), "price": variant.price,
                "price_label": price_label(variant.price) if variant.price is not None else "Нет предложений", "in_stock": in_stock, "offers": offers})
        if not variants:
            continue
        cover = _available_photos(product, [content["cover_id"]]) if content.get("cover_id") else []
        result.append({"id": str(product.id), "kind": product.kind, "seller_id": str(product.seller_id) if product.seller_id else None,
            "seller_name": sellers[str(product.seller_id)]["display_name"] if product.seller_id else None,
            "title": content["title"], "description": content["description"],
            "category_id": content["category_id"], "category": categories[content["category_id"]], "attributes": deepcopy(content["attributes"]),
            "unit": product.unit, "unit_label": UNITS[product.unit], "cover_id": cover[0] if cover else None, "variants": variants})
    return compose_common_cards(result)


def product_summary(card):
    in_stock_prices = [variant["price"] for variant in card["variants"] if variant["in_stock"] and variant["price"] is not None]
    known_prices = [variant["price"] for variant in card["variants"] if variant["price"] is not None]
    prices = in_stock_prices or known_prices
    price = min(prices) if prices else None
    return {
        "id": card["id"], "title": card["title"], "category": card["category"], "cover_id": card["cover_id"],
        "unit_label": card["unit_label"], "price": price, "price_label": price_label(price) if price is not None else "Цена не указана",
        "in_stock": any(variant["in_stock"] for variant in card["variants"]),
    }


def get_seller_store(*, seller_id, context):
    seller_id = str(identifier(seller_id))
    cards = [card for card in public_products(context) if card["kind"] == "physical" and card.get("seller_id") == seller_id]
    if not cards:
        raise PermissionDenied(UNAVAILABLE)
    sellers = get_public_sellers(seller_ids=(identifier(seller_id),))
    if not sellers:
        raise PermissionDenied(UNAVAILABLE)
    return {"seller": {"id": seller_id, "display_name": sellers[0]["display_name"]}, "products": [product_summary(card) for card in cards]}


def get_product(*, product_id, context, variant_id=None, filters=None, category_id=None, from_search=False, price_min=None, price_max=None):
    from open_marketplace.catalog.search import validate_filters

    price_min, price_max = price_range(price_min, price_max)
    product_id = str(identifier(product_id))
    cards = public_products(context)
    filters, category_id, _ = validate_filters(cards=cards, categories=list_categories(context=context), filters=filters, category_id=category_id)
    product = next((row for row in cards if row["id"] == product_id), None)
    if product is None:
        raise PermissionDenied(UNAVAILABLE)
    product["is_saved"] = SavedProduct.objects.filter(account_id=context.actor_account_id, product_id=product_id).exists()
    variants = product["variants"]
    product["price_min"], product["price_max"] = price_min, price_max
    priced = {row["id"]: price_limited_variant(row, price_min, price_max)
              for row in variants if row["price"] is not None}
    if price_min is not None or price_max is not None:
        product["price_filter_message"] = "Показаны предложения в выбранном диапазоне цен. Доставка в цену не включена."
    selected = None
    if variant_id is not None:
        requested = str(identifier(variant_id))
        selected = next((row for row in variants if row["id"] == requested), None)
        if selected is None:
            product["selection_message"] = "Указанный вариант недоступен. Другой вариант не выбран автоматически."
        elif priced.get(selected["id"]) is not None:
            selected = priced[selected["id"]]
        elif price_min is not None or price_max is not None:
            product["selection_message"] = "Указанный вариант вне выбранного диапазона цен или не имеет подходящих предложений в наличии. Выбор сохранён."
    else:
        matches = [row for row in priced.values() if row is not None and row["in_stock"] and row["price"] is not None
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
