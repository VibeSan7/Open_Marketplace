from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from open_marketplace.catalog.application import _publication_data
from open_marketplace.catalog.models import Attribute, Category, Participant, Photo, Product, Stock, StorageLocation, Variant
from open_marketplace.catalog.photos import normalize_photo, photo_path
from open_marketplace.common.demo_content import demo_identifier, require_demo_content
from open_marketplace.common.errors import InputRejected
from open_marketplace.seller_onboarding.public import get_public_sellers


def create_demo_catalog(*, manifest, sellers, assets, now, confirmed):
    require_demo_content(confirmed=confirmed)
    for key, seller in sellers.items():
        if seller != {"account_id": demo_identifier("account", key), "seller_id": demo_identifier("seller", key)}:
            raise InputRejected("Учебное наполнение не изменяет товары существующих продавцов.")
        if not get_public_sellers(seller_ids=(seller["seller_id"],)):
            raise InputRejected("Учебный профиль продавца недоступен.")
    for item in manifest["categories"]:
        if Category.objects.filter(pk=demo_identifier("category", item["key"])).exists() or Category.objects.filter(name=item["name"]).exists():
            raise InputRejected("Учебная категория пересекается с существующей. Ничего не заменено.")
    for item in manifest["products"]:
        if Product.objects.filter(pk=demo_identifier("product", item["key"])).exists() or photo_path(demo_identifier("photo", item["key"])).exists():
            raise InputRejected("Учебная карточка или фотография уже существует. Ничего не заменено.")
    counts = {"categories": 0, "products": 0, "variants": 0, "photos": 0}
    with transaction.atomic():
        for seller in sellers.values():
            Participant.objects.create(account_id=seller["account_id"], allowed=True, changed_by_id=seller["account_id"], changed_at=now)
        categories = {}
        for item in manifest["categories"]:
            category = Category.objects.create(id=demo_identifier("category", item["key"]), name=item["name"])
            Attribute.objects.create(category=category, key="configuration", label="Комплектация", required=True, values=["Стандарт", "Подарочная упаковка"])
            Attribute.objects.create(category=category, key="purpose", label="Назначение", required=True, values=[])
            categories[item["key"]] = category
            counts["categories"] += 1
        locations = {key: StorageLocation.objects.create(
            id=demo_identifier("location", key), seller_id=seller["seller_id"], name="Демонстрационный склад", is_default=True,
        ) for key, seller in sellers.items()}
        for item in manifest["products"]:
            seller = sellers[item["seller"]]
            photo_id = demo_identifier("photo", item["key"])
            description = "Демонстрационный товар: цены, характеристики и комплектации учебные. Настоящей продажи и доставки нет.\n\n" + item["description"]
            description += "\n\nФото иллюстрирует тип товара, а не предложение конкретного бренда. Автор: " + item["credit"]["author"]
            description += ". Лицензия: " + item["credit"]["license"] + ". Источник: " + item["credit"]["source"]
            description += ". Сведения об изображениях: /demo-content/credits/"
            product = Product.objects.create(
                id=demo_identifier("product", item["key"]), owner_id=seller["account_id"], seller_id=seller["seller_id"],
                kind="physical", unit="pc", draft_version=1, created_at=now,
                draft={"title": "Демо · " + item["title"], "description": description, "category_id": str(categories[item["category"]].id), "attributes": {"purpose": item["purpose"]}, "cover_id": str(photo_id)},
            )
            image_path = assets / item["image"]
            png, width, height = normalize_photo(SimpleUploadedFile(image_path.name, image_path.read_bytes(), content_type="image/jpeg"))
            target = photo_path(photo_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(png)
            Photo.objects.create(id=photo_id, product=product, attested_by_id=seller["account_id"], created_at=now, width=width, height=height)
            counts["photos"] += 1
            for offer in item["variants"]:
                variant = Variant.objects.create(
                    id=demo_identifier("variant", item["key"] + "-" + offer["key"]), product=product,
                    draft={"label": offer["label"], "attributes": {"configuration": offer["label"]}, "photo_ids": [str(photo_id)]},
                    price=Decimal(offer["price"]), price_version=1,
                )
                Stock.objects.create(variant=variant, location=locations[item["seller"]], quantity=Decimal("50.000"), version=1)
                counts["variants"] += 1
            published, variants = _publication_data(product)
            for variant, snapshot in variants:
                variant.published, variant.published_version, variant.state = snapshot, 1, "published"
                variant.save(update_fields=("published", "published_version", "state"))
            product.published, product.published_version, product.published_at = published, 1, now
            product.unit_locked, product.public_listing = True, True
            product.save(update_fields=("published", "published_version", "published_at", "unit_locked", "public_listing"))
            counts["products"] += 1
    return counts
