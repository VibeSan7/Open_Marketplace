import hashlib
import json
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from open_marketplace.catalog import public as catalog_public
from open_marketplace.common.demo_content import require_demo_content
from open_marketplace.common.errors import InputRejected
from open_marketplace.identity import public as identity_public
from open_marketplace.seller_onboarding import public as seller_public
from open_marketplace.verification.models import DemoContentInstallation


ASSETS = Path(__file__).resolve().parent / "assets" / "storefront"


def load_manifest():
    return json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))


def seed_storefront(*, confirmed):
    require_demo_content(confirmed=confirmed)
    manifest = load_manifest()
    digest = hashlib.sha256((ASSETS / "manifest.json").read_bytes()).hexdigest()
    for item in manifest["products"]:
        image = ASSETS / item["image"]
        if image.parent != ASSETS or hashlib.sha256(image.read_bytes()).hexdigest() != item["image_sha256"]:
            raise InputRejected("Демонстрационный файл повреждён. Установите исходный комплект изображений.")
    now = timezone.now()
    with transaction.atomic():
        installation, created = DemoContentInstallation.objects.get_or_create(
            key=manifest["key"], defaults={"manifest_digest": digest, "created_at": now},
        )
        installation = DemoContentInstallation.objects.select_for_update().get(pk=installation.pk)
        if not created:
            if installation.manifest_digest != digest:
                raise InputRejected("Установлен другой комплект демоданных. Существующие записи не перезаписываются.")
            return {"already_installed": True, "counts": installation.counts}
        sellers = {}
        for item in manifest["sellers"]:
            owner = identity_public.create_demo_seller_account(key=item["key"], now=now, confirmed=True)
            profile = seller_public.create_demo_seller_profile(
                key=item["key"], account_id=owner, display_name=item["name"], now=now, confirmed=True,
            )
            sellers[item["key"]] = {"account_id": owner, "seller_id": profile}
        counts = catalog_public.create_demo_catalog(manifest=manifest, sellers=sellers, assets=ASSETS, now=now, confirmed=True)
        counts["sellers"] = len(sellers)
        installation.counts = counts
        installation.save(update_fields=("counts",))
    return {"already_installed": False, "counts": counts}
