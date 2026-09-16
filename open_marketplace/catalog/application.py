from copy import deepcopy
import re

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from open_marketplace.audit.public import append_audit_entry
from open_marketplace.catalog.domain import UNITS, price_value, stock_value
from open_marketplace.catalog.models import Attribute, Category, Participant, Photo, Product, Stock, StorageLocation, Variant
from open_marketplace.catalog.photos import normalize_photo, photo_path
from open_marketplace.catalog.policy import UNAVAILABLE, identifier, manager, owned_product, seller
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.identity.public import get_account_snapshot
from open_marketplace.seller_onboarding.public import get_public_sellers


def _text(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise InputRejected(f"Ожидается текст длиной не более {maximum} символов.")
    value = value.strip()
    if required and not value:
        raise InputRejected("Заполните обязательные поля.")
    return value


def _mapping(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise InputRejected("Неизвестные или неверные поля формы.")
    return value


def _version(expected, current):
    if type(expected) is not int or expected < 0:
        raise InputRejected("Неверная версия формы.")
    if expected != current:
        raise ConcurrentConflict("Данные уже изменены. Ваш ввод не сохранён: проверьте актуальное значение и повторите явно.")


def _attrs(value):
    if not isinstance(value, dict) or len(value) > 50:
        raise InputRejected("Неверный набор характеристик.")
    result = {}
    for key, item in value.items():
        key = _text(key, 64, required=True)
        if re.fullmatch(r"[\w-]+", key) is None:
            raise InputRejected("Неверный ключ характеристики.")
        item = _text(item, 256)
        if item:
            result[key] = item
    return result


def _audit(context, action, object_id, *, object_type="catalog_product", before=None, after=None, reason=None, staff=False):
    append_audit_entry(context=context, action=f"catalog.{action}", object_type=object_type,
        object_id=str(object_id), result="success", reason=reason, before=before or {}, after=after or {},
        effective_role="security_admin" if staff else None)


def set_participant(*, account_id, allowed, context):
    manager(context)
    account_id = identifier(account_id)
    if type(allowed) is not bool:
        raise InputRejected("Укажите, разрешён ли допуск.")
    try:
        account = get_account_snapshot(account_id)
    except ObjectDoesNotExist:
        raise InputRejected("Учётная запись не найдена.") from None
    if account.kind != "ordinary" or (allowed and (account.state != "active" or account.email_verified_at is None)):
        raise InputRejected("Допуск выдаётся подтверждённой действующей личной учётной записи.")
    with transaction.atomic():
        Participant.objects.update_or_create(account_id=account_id, defaults={"allowed": allowed, "changed_by_id": context.actor_account_id, "changed_at": context.now})
        _audit(context, "participant_change", account_id, object_type="catalog_participant", after={"state": "allowed" if allowed else "revoked"}, staff=True)


def _attribute_definitions(attributes):
    if not isinstance(attributes, list) or len(attributes) > 50:
        raise InputRejected("Допустимо не более 50 характеристик категории.")
    result = []
    keys = set()
    for data in attributes:
        _mapping(data, {"key", "label", "required", "values"})
        key = _text(data.get("key", ""), 64, required=True)
        if re.fullmatch(r"[\w-]+", key) is None or key in keys:
            raise InputRejected("Ключи характеристик должны быть разными и не содержать пробелов.")
        keys.add(key)
        values = data.get("values", [])
        if not isinstance(values, list) or len(values) > 100:
            raise InputRejected("Допустимо не более 100 значений характеристики.")
        values = [_text(value, 256, required=True) for value in values]
        if len(values) != len(set(values)) or type(data.get("required", False)) is not bool:
            raise InputRejected("Проверьте значения и обязательность характеристики.")
        result.append({"key": key, "label": _text(data.get("label", ""), 120, required=True), "required": data.get("required", False), "values": values})
    return result


def create_category(*, name, attributes, context):
    manager(context)
    name = _text(name, 120, required=True)
    definitions = _attribute_definitions(attributes)
    with transaction.atomic():
        if Category.objects.filter(name=name).exists():
            raise InputRejected("Категория с таким названием уже существует.")
        category = Category.objects.create(name=name)
        Attribute.objects.bulk_create([Attribute(category=category, **item) for item in definitions])
        _audit(context, "category_create", category.id, object_type="catalog_category", after={"version": category.version}, staff=True)
    return category.id


def update_category(*, category_id, name, attributes, active, expected_version, context):
    manager(context)
    definitions = _attribute_definitions(attributes)
    name = _text(name, 120, required=True)
    if type(active) is not bool:
        raise InputRejected("Неверное состояние категории.")
    with transaction.atomic():
        category = Category.objects.select_for_update().filter(pk=identifier(category_id)).first()
        if category is None:
            raise InputRejected("Категория не найдена.")
        _version(expected_version, category.version)
        if Category.objects.filter(name=name).exclude(pk=category.id).exists():
            raise InputRejected("Категория с таким названием уже существует.")
        category.name, category.active = name, active
        category.version += 1
        category.save(update_fields=("name", "active", "version"))
        retained = []
        for item in definitions:
            key = item["key"]
            attribute, _ = Attribute.objects.update_or_create(category=category, key=key, defaults=item)
            retained.append(attribute.id)
        category.attributes.exclude(id__in=retained).delete()
        _audit(context, "category_update", category.id, object_type="catalog_category", after={"version": category.version}, staff=True)


def _default_location(profile):
    location, _ = StorageLocation.objects.get_or_create(seller_id=profile.id, is_default=True, defaults={"name": "Основное место хранения"})
    return location


def create_location(*, name, context):
    profile = seller(context)
    name = _text(name, 120, required=True)
    with transaction.atomic():
        _default_location(profile)
        if StorageLocation.objects.filter(seller_id=profile.id, name=name).exists():
            raise InputRejected("Такое место хранения уже существует.")
        return StorageLocation.objects.create(seller_id=profile.id, name=name).id


def create_product(*, kind, unit, context):
    if kind not in {"physical", "digital", "common"} or unit not in UNITS:
        raise InputRejected("Неверный тип товара или единица.")
    if kind == "common":
        manager(context)
        owner_id = seller_id = None
    else:
        profile = seller(context)
        owner_id, seller_id = profile.owner_id, profile.id
    with transaction.atomic():
        if seller_id is not None:
            _default_location(profile)
        product = Product.objects.create(kind=kind, unit=unit, owner_id=owner_id, seller_id=seller_id,
            draft={"title": "", "description": "", "category_id": None, "attributes": {}, "cover_id": None}, created_at=context.now)
        _audit(context, "product_create", product.id, staff=kind == "common")
    return product.id


def _photo_ids(product, raw_ids):
    if not isinstance(raw_ids, list) or len(raw_ids) > 20:
        raise InputRejected("Для варианта допустимо до 20 фотографий.")
    ids = [identifier(value) for value in raw_ids]
    if len(ids) != len(set(ids)) or Photo.objects.filter(product=product, id__in=ids).count() != len(ids):
        raise InputRejected("Выберите разные фотографии этой карточки.")
    return [str(value) for value in ids]


def save_product_draft(*, product_id, data, expected_version, context):
    _mapping(data, {"title", "description", "category_id", "attributes", "cover_id", "unit"})
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        _version(expected_version, product.draft_version)
        unit = data.get("unit", product.unit)
        if unit not in UNITS or (product.unit_locked and unit != product.unit):
            raise InputRejected("Единица зафиксирована после сохранения цены или остатка. Для другой единицы создайте новую карточку.")
        draft = deepcopy(product.draft)
        for field, maximum in (("title", 200), ("description", 10000)):
            if field in data:
                draft[field] = _text(data[field], maximum)
        if "category_id" in data:
            category_id = identifier(data["category_id"]) if data["category_id"] else None
            if category_id and not Category.objects.filter(pk=category_id, active=True).exists():
                raise InputRejected("Категория недоступна.")
            draft["category_id"] = str(category_id) if category_id else None
        if "attributes" in data:
            draft["attributes"] = _attrs(data["attributes"])
        if "cover_id" in data:
            draft["cover_id"] = _photo_ids(product, [data["cover_id"]])[0] if data["cover_id"] else None
        product.draft, product.unit = draft, unit
        product.draft_version += 1
        product.save(update_fields=("draft", "draft_version", "unit"))
        return product.draft_version


def _variant_draft(product, data):
    _mapping(data, {"label", "attributes", "photo_ids", "restore"})
    if "restore" in data and type(data["restore"]) is not bool:
        raise InputRejected("Неверная отметка возврата варианта.")
    return {"label": _text(data.get("label", ""), 200), "attributes": _attrs(data.get("attributes", {})), "photo_ids": _photo_ids(product, data.get("photo_ids", []))}


def add_variant(*, product_id, data, expected_version, context):
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        _version(expected_version, product.draft_version)
        variant = Variant.objects.create(product=product, draft=_variant_draft(product, data))
        if product.seller_id:
            location = StorageLocation.objects.get(seller_id=product.seller_id, is_default=True)
            Stock.objects.create(variant=variant, location=location)
        product.draft_version += 1
        product.save(update_fields=("draft_version",))
        return variant.id


def save_variant_draft(*, product_id, variant_id, data, expected_version, context):
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        _version(expected_version, product.draft_version)
        variant = product.variants.filter(pk=identifier(variant_id)).first()
        if variant is None:
            raise PermissionDenied(UNAVAILABLE)
        variant.draft = _variant_draft(product, data)
        variant.restore_version = variant.withdrawal_version if data.get("restore") is True and variant.state == "withdrawn" else None
        variant.save(update_fields=("draft", "restore_version"))
        product.draft_version += 1
        product.save(update_fields=("draft_version",))
        return product.draft_version


def _owned_variant(variant_id, context):
    variant = Variant.objects.filter(pk=identifier(variant_id)).first()
    if variant is None:
        raise PermissionDenied(UNAVAILABLE)
    product = owned_product(variant.product_id, context, lock=True)
    variant.refresh_from_db()
    return product, variant


def set_offer(*, variant_id, field, value, expected_version, context, location_id=None, currency="RUB"):
    with transaction.atomic():
        product, variant = _owned_variant(variant_id, context)
        if product.kind == "common":
            raise InputRejected("В общей карточке цена и остаток берутся из предложений продавцов.")
        if field == "price":
            if location_id is not None:
                raise InputRejected("Цена общая для мест хранения одного варианта.")
            number = price_value(value, currency=currency)
            _version(expected_version, variant.price_version)
            variant.price = number
            variant.price_version += 1
            variant.save(update_fields=("price", "price_version"))
            new_version = variant.price_version
            audit_id, audit_type = variant.id, "catalog_variant"
        elif field == "stock":
            number = stock_value(value, product.unit)
            locations = StorageLocation.objects.filter(seller_id=product.seller_id)
            location = locations.filter(pk=identifier(location_id)).first() if location_id is not None else locations.filter(is_default=True).first()
            if location is None:
                raise InputRejected("Место хранения недоступно.")
            row, _ = Stock.objects.get_or_create(variant=variant, location=location)
            _version(expected_version, row.version)
            if number < row.reserved_quantity:
                raise InputRejected("Остаток не может быть меньше количества в действующих резервах.")
            row.quantity = number
            row.version += 1
            row.save(update_fields=("quantity", "version"))
            new_version = row.version
            audit_id, audit_type = row.id, "catalog_stock"
        else:
            raise InputRejected("Можно сохранить отдельно цену или остаток.")
        product.unit_locked = True
        product.save(update_fields=("unit_locked",))
        _audit(context, f"{field}_update", audit_id, object_type=audit_type, after={"version": new_version})
        return new_version


def upload_photo(*, product_id, uploaded_file, attested, context):
    owned_product(product_id, context)
    if attested is not True:
        raise InputRejected("Подтвердите, что это реальное фото товара без AI-дорисовок.")
    raw, width, height = normalize_photo(uploaded_file)
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        if product.photos.count() >= 100:
            raise InputRejected("В карточке уже 100 фотографий.")
        photo = Photo.objects.create(product=product, attested_by_id=context.actor_account_id, created_at=context.now, width=width, height=height)
        path = photo_path(photo.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as destination:
            destination.write(raw)
        return photo.id


def _publication_data(product):
    draft = deepcopy(product.draft)
    _text(draft.get("title", ""), 200, required=True)
    _text(draft.get("description", ""), 10000, required=True)
    category = Category.objects.filter(pk=identifier(draft.get("category_id")), active=True).first()
    if category is None:
        raise InputRejected("Выберите действующую категорию.")
    definitions = {row.key: row for row in category.attributes.all()}
    variants = []
    for variant in product.variants.all():
        returning = variant.state == "withdrawn" and variant.restore_version == variant.withdrawal_version
        if variant.state == "withdrawn" and not returning:
            continue
        if variant.blocked:
            raise InputRejected("Вариант заблокирован сотрудником. Публикация не снимает блокировку.")
        data = deepcopy(variant.draft)
        _text(data.get("label", ""), 200, required=True)
        common = draft.get("attributes", {})
        local = data.get("attributes", {})
        if any(key in common and common[key] != value for key, value in local.items()):
            raise InputRejected("Характеристика варианта противоречит общей характеристике карточки.")
        attributes = {**common, **local}
        if set(attributes) - set(definitions):
            raise InputRejected("В черновике есть характеристика, отсутствующая в текущем справочнике.")
        for key, definition in definitions.items():
            value = attributes.get(key)
            if definition.required and not value:
                raise InputRejected(f"Заполните обязательную характеристику «{definition.label}» каждого публикуемого варианта.")
            if value and definition.values and value not in definition.values:
                raise InputRejected(f"Выберите допустимое значение характеристики «{definition.label}».")
        data["attributes"] = attributes
        data["photo_ids"] = _photo_ids(product, data.get("photo_ids", []))
        if not data["photo_ids"] or any(not photo_path(value).is_file() for value in data["photo_ids"]):
            raise InputRejected("У каждого публикуемого варианта должно быть хотя бы одно доступное реальное фото.")
        if product.kind != "common":
            price_value(variant.price)
            stocks = list(variant.stocks.all())
            if not stocks or any(row.quantity is None for row in stocks):
                raise InputRejected("Укажите остаток варианта по его местам хранения, включая нулевой.")
            for row in stocks:
                stock_value(row.quantity, product.unit)
        variants.append((variant, data))
    if not variants:
        raise InputRejected("Нужен хотя бы один публикуемый вариант. Снятый вариант верните явно через черновик.")
    cover = draft.get("cover_id") or variants[0][1]["photo_ids"][0]
    _photo_ids(product, [cover])
    if not photo_path(cover).is_file():
        raise InputRejected("Выбранная обложка недоступна.")
    draft["cover_id"] = cover
    return draft, variants


def publish_product(*, product_id, expected_version, context):
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        _version(expected_version, product.draft_version)
        if product.kind == "digital":
            raise InputRejected("Цифровые товары пока сохраняются только как непубличные черновики.")
        if product.blocked:
            raise InputRejected("Карточка заблокирована сотрудником.")
        draft, variants = _publication_data(product)
        for variant, data in variants:
            variant.published = data
            variant.published_version += 1
            variant.state, variant.restore_version = "published", None
            variant.save(update_fields=("published", "published_version", "state", "restore_version"))
        product.published, product.published_at = draft, context.now
        product.published_version += 1
        product.unit_locked = True
        product.save(update_fields=("published", "published_at", "published_version", "unit_locked"))
        _audit(context, "publish", product.id, after={"version": product.published_version}, staff=product.kind == "common")


def set_public_listing(*, product_id, enabled, context):
    if type(enabled) is not bool:
        raise InputRejected("Укажите, показывать ли карточку публично.")
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        if enabled:
            if product.kind == "digital" or product.published is None or product.blocked:
                raise InputRejected("Публичной может быть только доступная опубликованная карточка.")
            if not Category.objects.filter(pk=identifier(product.published.get("category_id")), active=True).exists():
                raise InputRejected("Публичная карточка должна быть в действующей категории.")
            variants = [variant for variant in product.variants.all()
                        if variant.state == "published" and not variant.blocked and variant.published is not None]
            if not variants:
                raise InputRejected("Публичной может быть только карточка с доступным вариантом.")
            photos = {str(photo_id) for photo_id in product.photos.values_list("id", flat=True)}
            if any(not set(variant.published.get("photo_ids", [])).issubset(photos)
                   or any(not photo_path(photo_id).is_file() for photo_id in variant.published.get("photo_ids", []))
                   for variant in variants):
                raise InputRejected("Публичной может быть только карточка с доступными фотографиями.")
            if product.seller_id and not get_public_sellers(seller_ids=(product.seller_id,)):
                raise InputRejected("Профиль продавца больше не доступен.")
        product.public_listing = enabled
        product.save(update_fields=("public_listing",))
        _audit(context, "public_listing_change", product.id, after={"state": "public" if enabled else "private"}, staff=product.kind == "common")


def withdraw_product(*, product_id, context):
    with transaction.atomic():
        product = owned_product(product_id, context, lock=True)
        for variant_id in product.variants.values_list("id", flat=True):
            withdraw_variant(variant_id=variant_id, context=context)
        _audit(context, "withdraw_product", product.id, after={"state": "withdrawn"}, staff=product.kind == "common")


def withdraw_variant(*, variant_id, context):
    with transaction.atomic():
        product, variant = _owned_variant(variant_id, context)
        if variant.state != "withdrawn":
            variant.state = "withdrawn"
            variant.withdrawal_version += 1
            variant.restore_version = None
            variant.save(update_fields=("state", "withdrawal_version", "restore_version"))
            _audit(context, "withdraw_variant", variant.id, object_type="catalog_variant", after={"state": "withdrawn"}, staff=product.kind == "common")


def set_product_block(*, product_id, blocked, reason, context):
    manager(context)
    reason = _text(reason, 1024, required=True)
    if type(blocked) is not bool:
        raise InputRejected("Неверное состояние блокировки.")
    with transaction.atomic():
        product = Product.objects.select_for_update().filter(pk=identifier(product_id)).first()
        if product is None:
            raise PermissionDenied(UNAVAILABLE)
        product.blocked, product.block_reason = blocked, reason
        product.save(update_fields=("blocked", "block_reason"))
        _audit(context, "block_product", product.id, after={"state": "blocked" if blocked else "unblocked"}, reason=reason, staff=True)


def set_variant_block(*, variant_id, blocked, reason, context):
    manager(context)
    reason = _text(reason, 1024, required=True)
    if type(blocked) is not bool:
        raise InputRejected("Неверное состояние блокировки.")
    with transaction.atomic():
        variant = Variant.objects.filter(pk=identifier(variant_id)).first()
        if variant is None:
            raise PermissionDenied(UNAVAILABLE)
        product = Product.objects.select_for_update().get(pk=variant.product_id)
        variant.blocked, variant.block_reason = blocked, reason
        variant.save(update_fields=("blocked", "block_reason"))
        _audit(context, "block_variant", variant.id, object_type="catalog_variant", after={"state": "blocked" if blocked else "unblocked"}, reason=reason, staff=True)
