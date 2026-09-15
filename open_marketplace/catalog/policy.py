from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist

from open_marketplace.access.public import authorize, authorize_read_only
from open_marketplace.catalog.models import Participant, Product
from open_marketplace.common.errors import AuthenticationDenied, InputRejected, PermissionDenied
from open_marketplace.identity.public import get_account_snapshot, require_live_session_security_snapshot
from open_marketplace.seller_onboarding.public import get_seller_profile_for_owner


UNAVAILABLE = "Карточка недоступна."


def identifier(value):
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or len(value) != 36:
        raise InputRejected("Неверный идентификатор.")
    try:
        parsed = UUID(value)
    except ValueError:
        raise InputRejected("Неверный идентификатор.") from None
    if str(parsed) != value.lower():
        raise InputRejected("Неверный идентификатор.")
    return parsed


def participant(context):
    if context.actor_account_id is None or context.session_id is None:
        raise PermissionDenied("Для просмотра каталога требуется вход и допуск участника.")
    try:
        require_live_session_security_snapshot(session_id=context.session_id, account_id=context.actor_account_id, now=context.now)
        account = get_account_snapshot(context.actor_account_id)
    except (ObjectDoesNotExist, AuthenticationDenied):
        raise PermissionDenied("Сессия недоступна. Войдите повторно.") from None
    if account.state != "active" or account.email_verified_at is None:
        raise PermissionDenied("Для просмотра каталога подтвердите адрес почты.")
    if account.kind == "service":
        authorize_read_only(context=context, permission="catalog.read")
    elif not Participant.objects.filter(account_id=account.id, allowed=True).exists():
        raise PermissionDenied("Допуск к каталогу пока не выдан владельцем этой установки.")
    return account


def seller(context):
    account = participant(context)
    profile = get_seller_profile_for_owner(context=context)
    if account.kind != "ordinary" or not account.totp_enabled or profile is None or profile.state != "active":
        raise PermissionDenied("Требуется действующий допуск продавца и двухэтапный вход.")
    return profile


def manager(context, *, write=True):
    check = authorize if write else authorize_read_only
    return check(context=context, permission="catalog.manage" if write else "catalog.read")


def owned_product(product_id, context, *, lock=False):
    account = participant(context)
    query = Product.objects.select_for_update() if lock else Product.objects
    product = query.filter(pk=identifier(product_id)).first()
    if product is None:
        raise PermissionDenied(UNAVAILABLE)
    if product.kind == "common":
        manager(context, write=lock)
    else:
        profile = seller(context)
        if product.owner_id != account.id or product.seller_id != profile.id:
            raise PermissionDenied(UNAVAILABLE)
    return product
