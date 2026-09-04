"""Coordinator: enable the owner TOTP and activate a waiting seller atomically.

Imports only the public contracts of `identity` and `seller_onboarding`; the
whole credential/recovery-code/profile/audit/outbox change lives in one outer
transaction, so any failure rolls every module back together.
"""
from uuid import UUID

from django.db import transaction

from open_marketplace.common.errors import InvalidState
from open_marketplace.common.types import OperationContext
from open_marketplace.identity.public import enable_totp
from open_marketplace.seller_onboarding.public import (
    activate_seller_after_totp,
    get_seller_profile_for_owner,
)


def enable_totp_and_activate_waiting_seller(
    *,
    setup_id: UUID,
    code: str,
    context: OperationContext,
) -> tuple[str, ...]:
    with transaction.atomic():
        codes = enable_totp(
            setup_id=setup_id,
            code=code,
            context=context,
        )
        profile = get_seller_profile_for_owner(context=context)
        if profile is None:
            return codes
        if profile.state != "awaiting_owner_totp":
            raise InvalidState("Seller profile cannot be activated.")
        activate_seller_after_totp(
            seller_id=profile.id,
            context=context,
        )
        return codes
