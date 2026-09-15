from hashlib import sha256
import json

from django.db import transaction

from open_marketplace.catalog.application import _audit, _text
from open_marketplace.catalog.domain import price_label
from open_marketplace.catalog.models import Category, MatchRequest, OfferLink, Participant, Product, Suggestion, Variant
from open_marketplace.catalog.policy import UNAVAILABLE, identifier, manager, owned_product, seller
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.seller_onboarding.public import get_public_sellers


def identity_fingerprint(product, variant):
    data = {"unit": product.unit, "title": product.published["title"], "category_id": product.published["category_id"],
            "attributes": variant.published["attributes"], "label": variant.published["label"]}
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _pair(source_id, target_id):
    rows = {row.id: row for row in Variant.objects.select_related("product").filter(id__in=(identifier(source_id), identifier(target_id)))}
    source, target = rows.get(identifier(source_id)), rows.get(identifier(target_id))
    if source is None or target is None:
        raise PermissionDenied(UNAVAILABLE)
    for variant in (source, target):
        if variant.state != "published" or variant.blocked or variant.published is None or variant.product.blocked or variant.product.published is None:
            raise InputRejected("Для сопоставления нужны доступные опубликованные варианты.")
    if source.product.kind != "physical" or target.product.kind != "common":
        raise InputRejected("Сопоставляется свой физический вариант с вариантом общей карточки.")
    if source.product.unit != target.product.unit:
        raise InputRejected("Единицы предложения и общей карточки должны совпадать.")
    if not Participant.objects.filter(account_id=source.product.owner_id, allowed=True).exists() or not get_public_sellers(seller_ids=(source.product.seller_id,)):
        raise InputRejected("Допуск продавца больше не действует.")
    return source, target


def _lock_pair(source_id, target_id):
    product_ids = Variant.objects.filter(id__in=(source_id, target_id)).values_list("product_id", flat=True)
    list(Product.objects.select_for_update().filter(id__in=product_ids).order_by("id"))
    return _pair(source_id, target_id)


def request_match(*, source_variant_id, target_variant_id, reason, context):
    seller(context)
    source_id, target_id = identifier(source_variant_id), identifier(target_variant_id)
    reason = _text(reason, 2000, required=True)
    with transaction.atomic():
        source, target = _lock_pair(source_id, target_id)
        owned_product(source.product_id, context)
        previous = MatchRequest.objects.filter(source=source, target=target, state="pending").first()
        if previous is not None:
            if previous.source_version == source.product.published_version and previous.target_version == target.product.published_version:
                return previous.id
            previous.state = "stale"
            previous.save(update_fields=("state",))
        request = MatchRequest.objects.create(requester_id=context.actor_account_id, source=source, target=target,
            source_version=source.product.published_version, target_version=target.product.published_version,
            source_fingerprint=identity_fingerprint(source.product, source), target_fingerprint=identity_fingerprint(target.product, target),
            reason=reason, created_at=context.now)
        return request.id


def review_match(*, request_id, approve, identity_confirmed, reason, context):
    manager(context)
    reason = _text(reason, 1024, required=True)
    if type(approve) is not bool or (approve and identity_confirmed is not True):
        raise InputRejected("Подтвердите проверку модели, характеристик, комплектации, состояния и единицы.")
    with transaction.atomic():
        request = MatchRequest.objects.filter(pk=identifier(request_id)).first()
        if request is None:
            raise InputRejected("Запрос не найден.")
        if approve:
            source, target = _lock_pair(request.source_id, request.target_id)
        else:
            list(Product.objects.select_for_update().filter(variants__id__in=(request.source_id, request.target_id)).order_by("id"))
        request.refresh_from_db()
        if request.state != "pending":
            raise ConcurrentConflict("Этот запрос уже обработан или его содержание устарело.")
        if approve:
            if (source.product.published_version != request.source_version or target.product.published_version != request.target_version
                    or identity_fingerprint(source.product, source) != request.source_fingerprint or identity_fingerprint(target.product, target) != request.target_fingerprint):
                raise ConcurrentConflict("После подачи запроса содержание изменилось. Нужен новый запрос и новая проверка.")
            if source.product.published["category_id"] != target.product.published["category_id"] or source.published["attributes"] != target.published["attributes"]:
                raise InputRejected("Категория и характеристики различаются: сначала исправьте и опубликуйте содержание.")
            OfferLink.objects.filter(source=source, active=True).update(active=False)
            OfferLink.objects.create(source=source, target=target, request=request, source_fingerprint=request.source_fingerprint, target_fingerprint=request.target_fingerprint)
        request.state = "approved" if approve else "rejected"
        request.reviewer_id, request.reviewed_at, request.review_reason = context.actor_account_id, context.now, reason
        request.save(update_fields=("state", "reviewer_id", "reviewed_at", "review_reason"))
        _audit(context, "match_review", request.target.product_id, after={"decision": request.state, "subject_fingerprint": request.source_fingerprint}, reason=reason, staff=True)


def list_match_requests(*, context, own=False):
    if own:
        seller(context)
        query = MatchRequest.objects.filter(requester_id=context.actor_account_id)
    else:
        manager(context, write=False)
        query = MatchRequest.objects.all()
    result = []
    for row in query.select_related("source__product", "target__product"):
        source, target = row.source, row.target
        result.append({"id": str(row.id), "state": row.state, "reason": row.reason, "review_reason": row.review_reason,
            "source_variant_id": str(source.id), "source_product_id": str(source.product_id), "source_title": (source.product.published or {}).get("title", "Недоступно"),
            "source_attributes": (source.published or {}).get("attributes", {}), "source_unit": source.product.unit,
            "target_variant_id": str(target.id), "target_product_id": str(target.product_id), "target_title": (target.product.published or {}).get("title", "Недоступно"),
            "target_attributes": (target.published or {}).get("attributes", {}), "target_unit": target.product.unit,
            "source_changed": row.source_version != source.product.published_version, "target_changed": row.target_version != target.product.published_version})
    return result


def suggest_change(*, kind, target_id, text, context):
    seller(context)
    text = _text(text, 2000, required=True)
    target_id = identifier(target_id) if target_id else None
    if kind not in {"category", "attribute", "common"}:
        raise InputRejected("Неверный вид предложения.")
    if kind == "common" and not Product.objects.filter(pk=target_id, kind="common", published__isnull=False).exists():
        raise InputRejected("Общая карточка недоступна.")
    if kind == "attribute" and not Category.objects.filter(pk=target_id).exists():
        raise InputRejected("Категория недоступна.")
    return Suggestion.objects.create(author_id=context.actor_account_id, kind=kind, target_id=target_id, text=text, created_at=context.now).id


def list_suggestions(*, context, own=False):
    if own:
        seller(context)
        rows = Suggestion.objects.filter(author_id=context.actor_account_id)
    else:
        manager(context, write=False)
        rows = Suggestion.objects.all()
    return [{"id": str(row.id), "kind": row.kind, "target_id": str(row.target_id) if row.target_id else None, "text": row.text,
             "reviewed": row.reviewed_at is not None, "response": row.response} for row in rows]


def review_suggestion(*, suggestion_id, response, context):
    manager(context)
    response = _text(response, 2000, required=True)
    with transaction.atomic():
        row = Suggestion.objects.select_for_update().filter(pk=identifier(suggestion_id)).first()
        if row is None:
            raise InputRejected("Предложение не найдено.")
        row.response, row.reviewer_id, row.reviewed_at = response, context.actor_account_id, context.now
        row.save(update_fields=("response", "reviewer_id", "reviewed_at"))


def compose_common_cards(cards):
    views = {variant["id"]: (card, variant) for card in cards for variant in card["variants"]}
    for link in OfferLink.objects.filter(active=True).select_related("source__product", "target__product"):
        source_entry, target_entry = views.get(str(link.source_id)), views.get(str(link.target_id))
        if source_entry is None or target_entry is None:
            continue
        source_product, source_view = source_entry
        target_product, target_view = target_entry
        if source_product["kind"] != "physical" or target_product["kind"] != "common" or source_product["unit"] != target_product["unit"]:
            continue
        if identity_fingerprint(link.source.product, link.source) != link.source_fingerprint or identity_fingerprint(link.target.product, link.target) != link.target_fingerprint:
            continue
        target_view["offers"].extend(source_view["offers"])
        source_view["grouped"] = True
    result = []
    for card in cards:
        if card["kind"] == "common":
            card["variants"] = [variant for variant in card["variants"] if variant["offers"]]
            for variant in card["variants"]:
                all_offers = variant["offers"]
                available = [offer for offer in all_offers if offer["in_stock"]]
                variant["in_stock"] = bool(available)
                variant["price"] = min(offer["price"] for offer in (available or all_offers))
                variant["price_label"] = price_label(variant["price"])
                variant["offers"] = sorted(available, key=lambda offer: (offer["price"], offer["seller_name"], offer["variant_id"]))
        if card["variants"]:
            result.append(card)
    return result
