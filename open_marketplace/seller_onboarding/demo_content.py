from django.db import transaction

from open_marketplace.common.demo_content import demo_identifier, require_demo_content
from open_marketplace.common.errors import InputRejected
from open_marketplace.identity.public import get_account_snapshot
from open_marketplace.seller_onboarding.models import SellerApplication, SellerApplicationVersion, SellerProfile


def create_demo_seller_profile(*, key, account_id, display_name, now, confirmed):
    require_demo_content(confirmed=confirmed)
    if account_id != demo_identifier("account", key):
        raise InputRejected("Учебный продавец может принадлежать только новому учебному аккаунту.")
    account = get_account_snapshot(account_id)
    if account.email != f"{key}@storefront-demo.example.test" or account.kind != "ordinary" or not account.totp_enabled:
        raise InputRejected("Учебный аккаунт продавца недоступен.")
    if not isinstance(display_name, str) or not display_name.startswith("Демо · ") or len(display_name) > 256:
        raise InputRejected("Название учебного продавца должно быть явно помечено.")
    with transaction.atomic():
        if SellerProfile.objects.filter(owner_id=account_id).exists() or SellerApplication.objects.filter(applicant_id=account_id).exists():
            raise InputRejected("Существующий профиль продавца не заменяется учебным.")
        application = SellerApplication.objects.create(
            id=demo_identifier("application", key), applicant_id=account_id,
            state="approved", current_version=1, created_at=now, test_data_attested=True,
        )
        SellerApplicationVersion.objects.create(
            id=demo_identifier("application-version", key), application=application, version_number=1,
            business_form="self_employed", display_name=display_name, official_name="Вымышленный учебный продавец",
            registration_identifier=f"DEMO-{key}", contact_email=account.email, test_data_attested=True, submitted_at=now,
        )
        profile = SellerProfile.objects.create(
            id=demo_identifier("seller", key), owner_id=account_id, application=application,
            approved_version=1, state="active", created_at=now, updated_at=now,
        )
    return profile.id
