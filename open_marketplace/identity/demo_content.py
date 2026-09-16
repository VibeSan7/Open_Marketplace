import pyotp
from django.db import transaction

from open_marketplace.common.demo_content import demo_identifier, require_demo_content
from open_marketplace.common.errors import InputRejected
from open_marketplace.identity.application import _encrypt_totp_secret
from open_marketplace.identity.models import Account, TotpCredential


def create_demo_seller_account(*, key, now, confirmed):
    require_demo_content(confirmed=confirmed)
    account_id = demo_identifier("account", key)
    email = f"{key}@storefront-demo.example.test"
    with transaction.atomic():
        if Account.objects.filter(pk=account_id).exists() or Account.objects.filter(email=email).exists():
            raise InputRejected("Демонстрационный аккаунт пересекается с существующей записью. Ничего не заменено.")
        account = Account(id=account_id, email=email, kind="ordinary", state="active", email_verified_at=now)
        account.set_unusable_password()
        account.save(force_insert=True)
        TotpCredential.objects.create(
            account=account, encrypted_secret=_encrypt_totp_secret(pyotp.random_base32()),
            confirmed_at=now, last_accepted_counter=0,
        )
    return account.id
