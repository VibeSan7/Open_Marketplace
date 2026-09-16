from difflib import get_close_matches
from hashlib import sha256
import json
import re
import unicodedata

from django.core import signing

from open_marketplace.catalog.domain import price_label, price_limited_variant, price_range
from open_marketplace.catalog.policy import identifier
from open_marketplace.catalog.queries import list_categories, public_products
from open_marketplace.catalog.semantic import MIN_SIMILARITY, similarities
from open_marketplace.common.errors import InputRejected

PAGE_SIZE = 20
_CURSOR_SALT = "catalog.search.cursor.v1"


def _normalized(text):
    return unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")


def _words(text):
    return tuple(re.findall(r"\w+", _normalized(text)))


def _eligible(card, filters, category_id, price_min=None, price_max=None):
    if category_id and card["category_id"] != category_id:
        return []
    result = []
    for variant in card["variants"]:
        if (not variant["in_stock"] or variant["price"] is None or variant.get("grouped")
                or not all(variant["attributes"].get(key) in values for key, values in filters.items())):
            continue
        priced = price_limited_variant(variant, price_min, price_max)
        if priced is not None:
            result.append(priced)
    return result


def _document(card, variants):
    attributes = sorted({value for variant in variants for value in variant["attributes"].values()})
    return " ".join((card["title"], *attributes, card["description"]))


def _schema(categories, cards, category_id):
    schema = {}
    for category in categories:
        if category_id and category["id"] != category_id:
            continue
        for attribute in category["attributes"]:
            item = schema.setdefault(attribute["key"], {"label": attribute["label"], "values": set()})
            item["values"].update(attribute["values"])
    for card in cards:
        if category_id and card["category_id"] != category_id:
            continue
        for variant in card["variants"]:
            for key, value in variant["attributes"].items():
                if key in schema:
                    schema[key]["values"].add(value)
    return schema


def validate_filters(*, filters, category_id, cards, categories):
    if category_id:
        category_id = str(identifier(category_id))
        if category_id not in {row["id"] for row in categories}:
            raise InputRejected("Категория в ссылке не поддерживается. Выберите другую или явно удалите условие.")
    else:
        category_id = None
    schema = _schema(categories, cards, category_id)
    if filters is None:
        filters = {}
    if not isinstance(filters, dict) or len(filters) > 50:
        raise InputRejected("Неверный набор фильтров.")
    cleaned = {}
    for key, values in filters.items():
        if key not in schema:
            raise InputRejected(f"Фильтр «{key}» не поддерживается. Исправьте или явно удалите его.")
        if not isinstance(values, list) or not values or len(values) > 100 or any(not isinstance(value, str) or value not in schema[key]["values"] for value in values):
            raise InputRejected(f"Значение фильтра «{schema[key]['label']}» не поддерживается. Исправьте или явно удалите его.")
        cleaned[key] = list(dict.fromkeys(values))
    return cleaned, category_id, schema


def _rank(cards, query, filters, category_id, price_min=None, price_max=None):
    candidates = [(card, variants) for card in cards if (variants := _eligible(card, filters, category_id, price_min, price_max))]
    query_words = _words(query)
    documents = [_document(card, variants) for card, variants in candidates]
    scores = similarities(query, documents) if query_words else [1.0] * len(documents)
    ranked = []
    vocabulary = set()
    for (card, variants), document, semantic_score in zip(candidates, documents, scores, strict=True):
        words = set(_words(document))
        vocabulary.update(words)
        exact = all(word in words for word in query_words)
        shared = sum(word in words for word in query_words)
        close = sum(len(word) >= 4 and bool(get_close_matches(word, sorted(words), n=1, cutoff=0.78)) for word in query_words if word not in words)
        if not exact and not shared and not close and semantic_score < MIN_SIMILARITY:
            continue
        score = max(semantic_score, (shared + close * 0.5) / len(query_words)) if query_words else 1.0
        key = (0 if exact else 1, -score, _normalized(card["title"]), card["id"])
        ranked.append((key, card, variants))
    ranked.sort(key=lambda row: row[0])
    return ranked, vocabulary


def _suggestion(query, ranked, vocabulary):
    if not query or any(key[0] == 0 for key, card, variants in ranked):
        return None
    original = _words(query)
    corrected = []
    for word in original:
        matches = get_close_matches(word, sorted(vocabulary), n=1, cutoff=0.78) if word not in vocabulary and len(word) >= 4 else []
        corrected.append(matches[0] if matches else word)
    return " ".join(corrected) if tuple(corrected) != original else None


def _cursor_fingerprint(query, filters, category_id, price_min=None, price_max=None, sort="relevance"):
    data = {"q": query, "category": category_id, "filters": {key: sorted(values) for key, values in filters.items()}}
    if price_min is not None:
        data["price_min"] = str(price_min)
    if price_max is not None:
        data["price_max"] = str(price_max)
    if sort != "relevance":
        data["sort"] = sort
    return sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def search_catalog(*, query="", filters=None, category_id=None, cursor=None,
                   price_min=None, price_max=None, sort="relevance", context):
    if not isinstance(query, str) or len(query) > 200 or "\x00" in query or (query.strip() and not _words(query)):
        raise InputRejected("Запрос должен содержать слова и занимать не более 200 символов.")
    price_min, price_max = price_range(price_min, price_max)
    if not isinstance(sort, str) or sort not in {"relevance", "price_asc", "price_desc"}:
        raise InputRejected("Выберите поддерживаемый порядок: обычный, сначала дешевле или сначала дороже.")
    cards = public_products(context)
    categories = list_categories(context=context)
    filters, category_id, schema = validate_filters(filters=filters, category_id=category_id, cards=cards, categories=categories)
    fingerprint = _cursor_fingerprint(query, filters, category_id, price_min, price_max, sort)
    after = None
    if cursor is not None:
        if not isinstance(cursor, str) or len(cursor) > 4096:
            raise InputRejected("Неверная ссылка продолжения списка. Начните поиск заново.")
        try:
            payload = signing.loads(cursor, salt=_CURSOR_SALT, max_age=86400)
        except signing.BadSignature:
            raise InputRejected("Ссылка продолжения списка недействительна. Начните поиск заново.") from None
        if payload["conditions"] != fingerprint:
            raise InputRejected("Условия поиска изменились. Начните список заново.")
        after = tuple(payload["after"])
    ranked, vocabulary = _rank(cards, query, filters, category_id, price_min, price_max)
    suggestion = _suggestion(query, ranked, vocabulary)
    approximate = {card["id"]: key[0] != 0 for key, card, variants in ranked}
    if sort != "relevance":
        direction = 1 if sort == "price_asc" else -1
        ranked = [((direction * int(min(variant["price"] for variant in variants) * 100), *key), card, variants)
                  for key, card, variants in ranked]
        ranked.sort(key=lambda row: row[0])
    remaining = [row for row in ranked if after is None or row[0] > after]
    selected = remaining[:PAGE_SIZE]
    items = []
    for key, card, variants in selected:
        prices = {offer["price"] for variant in variants for offer in variant["offers"] if offer["in_stock"]}
        if not prices:
            prices = {variant["price"] for variant in variants}
        price = min(prices)
        items.append({"id": card["id"], "title": card["title"], "category": card["category"], "cover_id": card["cover_id"], "unit_label": card["unit_label"],
                      "price": price, "price_label": price_label(price, different=len(prices) > 1), "approximate": approximate[card["id"]],
                      "variant_ids": [variant["id"] for variant in sorted(variants, key=lambda row: (row["price"], row["id"]))]})
    facets = []
    for key, definition in sorted(schema.items(), key=lambda row: (row[1]["label"], row[0])):
        others = {name: values for name, values in filters.items() if name != key}
        possible, _ = _rank(cards, query, others, category_id, price_min, price_max)
        available = {variant["attributes"][key] for rank, card, variants in possible for variant in variants if key in variant["attributes"]}
        facets.append({"key": key, "label": definition["label"], "values": [{"value": value, "available": value in available, "selected": value in filters.get(key, [])}
            for value in sorted(definition["values"])]})
    next_cursor = signing.dumps({"conditions": fingerprint, "after": selected[-1][0]}, salt=_CURSOR_SALT) if len(remaining) > len(selected) else None
    return {"items": items, "total": len(ranked), "next_cursor": next_cursor, "facets": facets, "categories": categories,
            "query": query, "filters": filters, "category_id": category_id, "suggestion": suggestion,
            "price_min": price_min, "price_max": price_max, "sort": sort}
