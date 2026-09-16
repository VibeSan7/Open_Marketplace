from urllib.parse import urlencode
from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from open_marketplace.access import public as access_public
from open_marketplace.catalog import public as catalog_public
from open_marketplace.common.errors import ApplicationError, ConcurrentConflict, PermissionDenied
from open_marketplace.identity import public as identity_public
from open_marketplace.web.catalog_forms import (
    AttributeFormSet,
    BlockForm,
    CategoryForm,
    ExpectedVersionForm,
    LocationForm,
    MatchRequestForm,
    MatchReviewForm,
    ParticipantForm,
    PhotoUploadForm,
    PriceForm,
    ProductCreateForm,
    ProductDraftForm,
    SuggestionForm,
    SuggestionReviewForm,
    StockForm,
    VariantActionForm,
    VariantDraftForm,
    attribute_formset_initial,
)
from open_marketplace.web.errors import secure_render, secure_response
from open_marketplace.web.identity_views import _context, _login_required, _redirect_303


def _catalog_render(request, template, context=None, *, status=200):
    response = secure_render(request, template, context, status=status)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _error(request, message, *, status=400, context=None):
    conditions = []
    if request.method == "GET" and status == 400:
        pairs = [(name, value) for name, values in request.GET.lists()
                 if name not in {"cursor", "fragment"} for value in values]
        for index, (name, value) in enumerate(pairs):
            remaining = urlencode(pairs[:index] + pairs[index + 1:])
            conditions.append({"name": name, "value": value,
                               "remove_url": request.path + ("?" + remaining if remaining else "")})
    return _catalog_render(request, "catalog/error.html", {"message": message, "conditions": conditions, "reauth_url": reverse("reauthenticate"), **(context or {})}, status=status)


def _application_error(request, error):
    if isinstance(error, PermissionDenied):
        return _error(request, str(error) or "Доступ к этой странице запрещён.", status=403)
    if isinstance(error, ConcurrentConflict):
        return _error(request, str(error), status=409)
    return _error(request, str(error) or "Не удалось выполнить операцию.", status=400)


def _expected_version(request):
    form = ExpectedVersionForm(request.POST)
    if not form.is_valid():
        raise ApplicationError("Неверная версия формы.")
    return form.cleaned_data["expected_version"]


def _one(query, name, default=None):
    values = query.getlist(name)
    if len(values) > 1:
        raise ValueError(f"Параметр «{name}» указан несколько раз. Оставьте одно значение.")
    return values[0] if values else default


def _search_conditions(request, *, include_cursor=True):
    allowed = {"q", "category", "fragment", "price_min", "price_max", "sort"}
    allowed.add("cursor" if include_cursor else "variant")
    if not include_cursor:
        allowed.add("from_search")
        if _one(request.GET, "from_search") not in (None, "1"):
            raise ValueError("Неверный источник ссылки.")
    unknown = [key for key in request.GET if not (key in allowed or key.startswith("f."))]
    if unknown:
        raise ValueError(f"Параметр «{unknown[0]}» не поддерживается. Исправьте ссылку или сбросьте условия.")
    query = _one(request.GET, "q", "")
    category_id = _one(request.GET, "category")
    cursor = _one(request.GET, "cursor") if include_cursor else None
    filters = {}
    for key in request.GET:
        if key.startswith("f."):
            name = key[2:]
            if not name:
                raise ValueError("Имя фильтра не может быть пустым.")
            values = request.GET.getlist(key)
            filters[name] = values
    minimum, maximum = _one(request.GET, "price_min"), _one(request.GET, "price_max")
    sort = _one(request.GET, "sort", "relevance")
    if sort not in {"relevance", "price_asc", "price_desc"}:
        raise ValueError("Выберите поддерживаемый порядок сортировки.")
    return query, category_id, filters, cursor, minimum, maximum, sort


def _applied_url(request, *, query, category_id, filters, path=None, price_min=None, price_max=None, sort="relevance"):
    pairs = []
    if query != "":
        pairs.append(("q", query))
    if category_id:
        pairs.append(("category", category_id))
    for key in sorted(filters):
        pairs.extend((f"f.{key}", value) for value in filters[key])
    for name, value in (("price_min", price_min), ("price_max", price_max)):
        if value is not None:
            pairs.append((name, str(value)))
    if sort != "relevance":
        pairs.append(("sort", sort))
    encoded = urlencode(pairs, doseq=True)
    return (path or request.path) + (f"?{encoded}" if encoded else "")


def _render_search(request, result, *, applied_url):
    pairs = [("q", result["query"])] if result["query"] else []
    if result["category_id"]:
        pairs.append(("category", result["category_id"]))
    pairs.extend((f"f.{key}", value) for key, values in result["filters"].items() for value in values)
    budget = {name: result[name] for name in ("price_min", "price_max", "sort")}
    pairs.extend((name, str(budget[name])) for name in ("price_min", "price_max") if budget[name] is not None)
    if budget["sort"] != "relevance":
        pairs.append(("sort", budget["sort"]))
    for item in result["items"]:
        item["url"] = reverse("catalog-product", kwargs={"product_id": item["id"]}) + "?" + urlencode(pairs + [("from_search", "1")])
    suggestion_url = _applied_url(request, query=result["suggestion"], category_id=result["category_id"], filters=result["filters"], **budget) if result["suggestion"] else None
    context = {
        "suggestion_url": suggestion_url,
        "next_url": reverse("catalog-search") + "?" + urlencode(pairs + [("cursor", result["next_cursor"])]),
        "search": result,
        "applied_url": applied_url,
        "fragment": request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("fragment") == "1",
    }
    template = "catalog/_results.html" if context["fragment"] else "catalog/search.html"
    return _catalog_render(request, template, context)


@require_http_methods(["GET"])
def catalog_search(request):
    try:
        query, category_id, filters, cursor, minimum, maximum, sort = _search_conditions(request)
        result = catalog_public.search_catalog(
            query=query,
            category_id=category_id,
            filters=filters,
            cursor=cursor,
            price_min=minimum, price_max=maximum, sort=sort,
            context=_context(request),
        )
        return _render_search(request, result, applied_url=_applied_url(
            request, query=query, category_id=category_id, filters=filters,
            price_min=result["price_min"], price_max=result["price_max"], sort=sort,
        ))
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET"])
def catalog_product(request, *, product_id):
    try:
        query, category_id, filters, _, minimum, maximum, sort = _search_conditions(request, include_cursor=False)
        variant_id = _one(request.GET, "variant")
        product = catalog_public.get_product(
            product_id=product_id,
            variant_id=variant_id,
            filters=filters,
            category_id=category_id,
            from_search=_one(request.GET, "from_search") == "1" or bool(query or category_id or filters or minimum or maximum),
            price_min=minimum, price_max=maximum,
            context=_context(request),
        )
        applied = _applied_url(request, query=query, category_id=category_id, filters=filters, path=reverse("catalog-search"),
            price_min=product["price_min"], price_max=product["price_max"], sort=sort)
        _, _, raw_query = applied.partition("?")
        for item in product["variants"]:
            params = [("variant", item["id"])]
            if raw_query:
                from urllib.parse import parse_qsl
                params = parse_qsl(raw_query, keep_blank_values=True) + params
            item["url"] = reverse("catalog-product", kwargs={"product_id": product["id"]}) + ("?" + urlencode(params, doseq=True) if params else "")
            for offer in item["offers"]:
                if offer.get("seller_id"):
                    offer["seller_url"] = reverse("catalog-seller", kwargs={"seller_id": offer["seller_id"]})
        product["save_url"] = reverse("catalog-save-product", kwargs={"product_id": product["id"]})
        product["save_action"] = "remove" if product["is_saved"] else "save"
        if product.get("seller_id"):
            product["seller_url"] = reverse("catalog-seller", kwargs={"seller_id": product["seller_id"]})
        selected_id = product.get("selected_variant_id")
        share_url = next((item["url"] for item in product["variants"] if item["id"] == selected_id), request.build_absolute_uri())
        return _catalog_render(request, "catalog/product.html", {
            "product": product,
            "back_url": applied,
            "query": query,
            "share_url": share_url,
        })
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET"])
@_login_required
def saved_products(request):
    try:
        products = catalog_public.list_saved_products(context=_context(request))
        for product in products:
            product["url"] = reverse("catalog-product", kwargs={"product_id": product["id"]})
            product["save_url"] = reverse("catalog-save-product", kwargs={"product_id": product["id"]})
        return _catalog_render(request, "catalog/saved.html", {"products": products})
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["POST"])
@_login_required
def save_product(request, *, product_id):
    actions = request.POST.getlist("action")
    unknown = set(request.POST) - {"action", "csrfmiddlewaretoken"}
    if len(actions) != 1 or unknown or actions[0] not in {"save", "remove"}:
        return _error(request, "Форма избранного заполнена неверно.")
    try:
        catalog_public.set_saved_product(product_id=product_id, saved=actions[0] == "save", context=_context(request))
        return _redirect_303(reverse("catalog-saved"))
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET"])
def seller_store(request, *, seller_id):
    try:
        store = catalog_public.get_seller_store(seller_id=seller_id, context=_context(request))
        for product in store["products"]:
            product["url"] = reverse("catalog-product", kwargs={"product_id": product["id"]})
        return _catalog_render(request, "catalog/seller.html", {"store": store})
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET"])
def catalog_photo(request, *, photo_id):
    try:
        photo = catalog_public.get_photo(photo_id=photo_id, context=_context(request))
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))
    response = FileResponse(photo, content_type="image/png")
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    return secure_response(response)


def _category_list(request, *, include_inactive=False):
    return catalog_public.list_categories(context=_context(request), include_inactive=include_inactive)


def _draft_initial(product):
    draft = dict(product["draft"] or {})
    draft.setdefault("unit", product["unit"])
    draft.setdefault("cover_id", "")
    draft["expected_version"] = product["draft_version"]
    return draft


def _common_targets(request, source_variant_id):
    return [(row["id"], f'{row["title"]} — {row["label"]} (' + ", ".join(row["attributes"].values()) + ")")
            for row in catalog_public.list_matching_targets(source_variant_id=source_variant_id, context=_context(request))]


def _suggestion_targets(request, categories):
    targets = [("", "Новая категория / без выбранной цели")]
    targets.extend((category["id"], f'Категория: {category["name"]}') for category in categories)
    targets.extend((row["id"], f'Общая карточка: {row["title"]}')
                   for row in catalog_public.list_common_cards(context=_context(request)))
    return targets


def _editor_context(request, product, categories, *, forms=None, message=None):
    forms = forms or {}
    product_form = forms.get("product") or ProductDraftForm(categories=categories, initial=_draft_initial(product), photos=product["photos"])
    variants = []
    suggestion_targets = _suggestion_targets(request, categories) if product["kind"] == "physical" else []
    for variant in product["variants"]:
        draft = dict(variant["draft"] or {})
        variant_form = forms.get(f"variant:{variant['id']}") or VariantDraftForm(
            categories=categories,
            category_id=(product["draft"] or {}).get("category_id"),
            photos=product["photos"],
            initial={**draft, "expected_version": product["draft_version"]},
        )
        prices = forms.get(f"price:{variant['id']}") or PriceForm(initial={
            "price": variant["price"] if variant["price"] is not None else "",
            "expected_version": variant["price_version"],
        })
        stocks = []
        for stock in variant["stocks"]:
            stocks.append((
                stock,
                forms.get(f"stock:{variant['id']}:{stock['location_id']}")
                or StockForm(initial={
                    "location_id": stock["location_id"],
                    "quantity": stock["quantity"] if stock["quantity"] is not None else "",
                    "expected_version": stock["version"],
                }),
            ))
        variants.append({
            "data": variant,
            "form": variant_form,
            "price_form": prices,
            "stocks": stocks,
            "match_form": forms.get(f"match:{variant['id']}") or MatchRequestForm(
                targets=_common_targets(request, variant["id"]) if product["kind"] == "physical" else [],
                initial={"source_variant_id": variant["id"]},
            ),
        })
    return {
        "product": product,
        "readiness": catalog_public.get_publication_readiness(product_id=product["id"], context=_context(request)),
        "categories": categories,
        "product_form": product_form,
        "variants": variants,
        "photo_form": forms.get("photo") or PhotoUploadForm(),
        "location_form": forms.get("location") or LocationForm(),
        "new_variant_form": forms.get("new_variant") or VariantDraftForm(
            categories=categories,
            category_id=(product["draft"] or {}).get("category_id"),
            photos=product["photos"],
            initial={"expected_version": product["draft_version"]},
        ),
        "message": message,
        "reauth_url": reverse("reauthenticate"),
        "suggestion_form": forms.get("suggestion") or SuggestionForm(targets=suggestion_targets),
    }


def _render_editor(request, product, *, forms=None, message=None, status=200):
    try:
        categories = _category_list(request, include_inactive=product["kind"] == "common")
        return _catalog_render(request, "catalog/editor.html", _editor_context(
            request, product, categories, forms=forms, message=message,
        ), status=status)
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET"])
@_login_required
def own_products(request):
    try:
        products = catalog_public.list_own_products(context=_context(request))
        own = getattr(request.user, "kind", None) != "service"
        matches = catalog_public.list_match_requests(context=_context(request), own=True) if own else []
        suggestions = catalog_public.list_suggestions(context=_context(request), own=True) if own else []
        return _catalog_render(request, "catalog/own.html", {"products": products, "matches": matches, "suggestions": suggestions})
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET"])
@_login_required
def own_product_preview(request, *, product_id):
    try:
        readiness = catalog_public.get_publication_readiness(product_id=product_id, context=_context(request))
        if not readiness["ready"]:
            return _error(request, "Предпросмотр пока недоступен. " + " ".join(readiness["issues"]))
        return _catalog_render(request, "catalog/preview.html", {"product": readiness["preview"]})
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET", "POST"])
@_login_required
def own_product_new(request):
    if request.method == "GET":
        form = ProductCreateForm()
        if getattr(request.user, "kind", None) == "service":
            form.fields["kind"].choices = (("common", "Общая карточка (для сотрудников)"),)
        else:
            form.fields["kind"].choices = tuple(choice for choice in form.fields["kind"].choices if choice[0] != "common")
    else:
        form = ProductCreateForm(request.POST)
        if form.is_valid():
            try:
                product_id = catalog_public.create_product(
                    kind=form.cleaned_data["kind"],
                    unit=form.cleaned_data["unit"],
                    context=_context(request),
                )
            except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
                return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))
            return _redirect_303(reverse("catalog-own-product", kwargs={"product_id": product_id}))
    return _catalog_render(request, "catalog/new.html", {"form": form})


@require_http_methods(["GET", "POST"])
@_login_required
def own_product(request, *, product_id):
    try:
        product = catalog_public.get_own_product(product_id=product_id, context=_context(request))
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))
    if request.method == "GET":
        return _render_editor(request, product)

    action = request.POST.get("action", "")
    context = _context(request)
    forms = {}
    try:
        if action == "set_public_listing":
            unknown = set(request.POST) - {"action", "enabled", "csrfmiddlewaretoken"}
            if unknown or request.POST.getlist("action") != [action] or len(request.POST.getlist("enabled")) != 1 or request.POST["enabled"] not in {"true", "false"}:
                raise ApplicationError("Укажите однозначно, показывать ли карточку всем посетителям.")
            catalog_public.set_public_listing(product_id=product_id, enabled=request.POST["enabled"] == "true", context=context)
        elif action == "save_product":
            form = ProductDraftForm(categories=_category_list(request, include_inactive=product["kind"] == "common"), initial=_draft_initial(product), data=request.POST, photos=product["photos"])
            forms["product"] = form
            if form.is_valid():
                catalog_public.save_product_draft(
                    product_id=product_id,
                    data={
                        "title": form.cleaned_data["title"],
                        "description": form.cleaned_data["description"],
                        "category_id": form.cleaned_data["category_id"] or None,
                        "attributes": form.public_attributes(),
                        "cover_id": form.cleaned_data["cover_id"] or None,
                        "unit": form.cleaned_data["unit"],
                    },
                    expected_version=form.cleaned_data["expected_version"],
                    context=context,
                )
            else:
                return _render_editor(request, product, forms=forms, message="Проверьте поля формы.", status=400)
        elif action == "add_variant":
            form = VariantDraftForm(categories=_category_list(request, include_inactive=product["kind"] == "common"), category_id=request.POST.get("category_id") or product["draft"].get("category_id"), photos=product["photos"], data=request.POST)
            forms["new_variant"] = form
            if form.is_valid():
                catalog_public.add_variant(
                    product_id=product_id,
                    data={"label": form.cleaned_data["label"], "attributes": form.public_attributes(), "photo_ids": form.cleaned_data["photo_ids"], "restore": form.cleaned_data["restore"]},
                    expected_version=form.cleaned_data["expected_version"],
                    context=context,
                )
            else:
                return _render_editor(request, product, forms=forms, message="Проверьте поля варианта.", status=400)
        elif action == "save_variant":
            variant_id = request.POST.get("variant_id")
            if not variant_id:
                raise ApplicationError("Вариант не распознан.")
            variant = next((row for row in product["variants"] if row["id"] == variant_id), None)
            if variant is None:
                raise ApplicationError("Вариант недоступен.")
            form = VariantDraftForm(categories=_category_list(request, include_inactive=product["kind"] == "common"), category_id=product["draft"].get("category_id"), photos=product["photos"], initial={**variant["draft"], "expected_version": product["draft_version"]}, data=request.POST)
            forms[f"variant:{variant_id}"] = form
            if form.is_valid():
                catalog_public.save_variant_draft(
                    product_id=product_id,
                    variant_id=variant_id,
                    data={"label": form.cleaned_data["label"], "attributes": form.public_attributes(), "photo_ids": form.cleaned_data["photo_ids"], "restore": form.cleaned_data["restore"]},
                    expected_version=form.cleaned_data["expected_version"],
                    context=context,
                )
            else:
                return _render_editor(request, product, forms=forms, message="Проверьте поля варианта.", status=400)
        elif action == "upload_photo":
            form = PhotoUploadForm(request.POST, request.FILES)
            forms["photo"] = form
            if form.is_valid():
                catalog_public.upload_photo(product_id=product_id, uploaded_file=form.cleaned_data["photo"], attested=form.cleaned_data["attested"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Выберите изображение и подтвердите его происхождение.", status=400)
        elif action == "create_location":
            form = LocationForm(request.POST)
            forms["location"] = form
            if form.is_valid():
                catalog_public.create_location(name=form.cleaned_data["name"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Укажите название места хранения.", status=400)
        elif action == "set_price":
            variant_id = request.POST.get("variant_id")
            if not variant_id:
                raise ApplicationError("Вариант не распознан.")
            form = PriceForm(request.POST)
            forms[f"price:{variant_id}"] = form
            if form.is_valid():
                catalog_public.set_offer(variant_id=variant_id, field="price", value=form.cleaned_data["price"], expected_version=form.cleaned_data["expected_version"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Проверьте цену.", status=400)
        elif action == "set_stock":
            variant_id = request.POST.get("variant_id")
            location_id = request.POST.get("location_id")
            if not variant_id or not location_id:
                raise ApplicationError("Вариант или место хранения не распознаны.")
            form = StockForm(request.POST)
            forms[f"stock:{variant_id}:{location_id}"] = form
            if form.is_valid():
                catalog_public.set_offer(variant_id=variant_id, field="stock", value=form.cleaned_data["quantity"], location_id=form.cleaned_data["location_id"], expected_version=form.cleaned_data["expected_version"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Проверьте остаток.", status=400)
        elif action == "publish":
            catalog_public.publish_product(product_id=product_id, expected_version=_expected_version(request), context=context)
        elif action == "withdraw_variant":
            form = VariantActionForm(request.POST)
            if form.is_valid():
                catalog_public.withdraw_variant(variant_id=form.cleaned_data["variant_id"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Вариант не распознан.", status=400)
        elif action == "withdraw_all":
            catalog_public.withdraw_product(product_id=product_id, context=context)
        elif action == "request_match":
            form = MatchRequestForm(request.POST, targets=_common_targets(request, request.POST.get("source_variant_id")))
            forms[f"match:{request.POST.get('source_variant_id', '')}"] = form
            if form.is_valid():
                catalog_public.request_match(source_variant_id=form.cleaned_data["source_variant_id"], target_variant_id=form.cleaned_data["target_variant_id"], reason=form.cleaned_data["reason"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Выберите общий вариант и опишите совпадение.", status=400)
        elif action == "suggest_change":
            form = SuggestionForm(request.POST, targets=_suggestion_targets(request, _category_list(request)))
            forms["suggestion"] = form
            if form.is_valid():
                catalog_public.suggest_change(kind=form.cleaned_data["kind"], target_id=form.cleaned_data["target_id"] or None, text=form.cleaned_data["text"], context=context)
            else:
                return _render_editor(request, product, forms=forms, message="Выберите цель и опишите предложение.", status=400)
        else:
            return _render_editor(request, product, forms=forms, message="Неизвестное действие формы.", status=400)
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        try:
            current = catalog_public.get_own_product(product_id=product_id, context=context)
        except (ApplicationError, ObjectDoesNotExist, ValueError):
            return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))
        if isinstance(error, ConcurrentConflict):
            for key, form in forms.items():
                version = current["draft_version"]
                if key.startswith(("price:", "stock:")):
                    parts = key.split(":")
                    variant = next(row for row in current["variants"] if row["id"] == parts[1])
                    version = variant["price_version"] if parts[0] == "price" else next(row["version"] for row in variant["stocks"] if row["location_id"] == parts[2])
                form.data = form.data.copy()
                form.data["expected_version"] = str(version)
        return _render_editor(request, current, forms=forms, message=str(error), status=409 if isinstance(error, ConcurrentConflict) else 400)
    return _redirect_303(reverse("catalog-own-product", kwargs={"product_id": product_id}))


def _management_context(request, *, message=None):
    context = _context(request)
    categories = catalog_public.list_categories(context=context, include_inactive=True)
    products = catalog_public.list_own_products(context=context)
    product_details = catalog_public.list_moderation_cards(context=context)
    requests = catalog_public.list_match_requests(context=context)
    suggestions = catalog_public.list_suggestions(context=context)
    return {
        "categories": categories,
        "products": products,
        "product_details": product_details,
        "match_requests": requests,
        "suggestions": suggestions,
        "participants": catalog_public.list_participants(context=context),
        "participant_form": ParticipantForm(),
        "category_form": CategoryForm(),
        "attribute_formset": AttributeFormSet(prefix="attributes", initial=[]),
        "message": message,
        "reauth_url": reverse("reauthenticate"),
    }


@require_http_methods(["GET", "POST"])
@_login_required
def catalog_manage(request):
    try:
        if request.method == "GET":
            return _catalog_render(request, "catalog/manage.html", _management_context(request))
        action = request.POST.get("action", "")
        context = _context(request)
        if action == "participant":
            form = ParticipantForm(request.POST)
            if not form.is_valid():
                return _catalog_render(request, "catalog/manage.html", {**_management_context(request), "participant_form": form, "message": "Проверьте email."}, status=400)
            email = form.cleaned_data["email"].casefold()
            access_public.authorize_read_only(context=context, permission="account.read")
            accounts = identity_public.query_accounts(
                query=identity_public.AccountQuery(kind="ordinary", state=None, canonical_email=email, limit=2, cursor=None),
                context=context,
                authorize=access_public.authorize_read_only,
            )
            if not accounts:
                raise ApplicationError("Учётная запись не найдена.")
            catalog_public.set_participant(account_id=accounts[0].id, allowed=form.cleaned_data["allowed"], context=context)
        elif action == "create_category":
            category_form = CategoryForm(request.POST)
            formset = AttributeFormSet(request.POST, prefix="attributes")
            if not category_form.is_valid() or not formset.is_valid():
                return _catalog_render(request, "catalog/manage.html", {**_management_context(request), "category_form": category_form, "attribute_formset": formset, "message": "Проверьте категорию и характеристики."}, status=400)
            catalog_public.create_category(name=category_form.cleaned_data["name"], attributes=formset.as_definitions(), context=context)
        elif action in {"block_product", "unblock_product"}:
            form = BlockForm(request.POST)
            if not form.is_valid():
                raise ApplicationError("Проверьте блокировку.")
            catalog_public.set_product_block(product_id=form.cleaned_data["object_id"], blocked=action == "block_product", reason=form.cleaned_data["reason"], context=context)
        elif action in {"block_variant", "unblock_variant"}:
            form = BlockForm(request.POST)
            if not form.is_valid():
                raise ApplicationError("Проверьте блокировку.")
            catalog_public.set_variant_block(variant_id=form.cleaned_data["object_id"], blocked=action == "block_variant", reason=form.cleaned_data["reason"], context=context)
        elif action == "review_match":
            form = MatchReviewForm(request.POST)
            if not form.is_valid():
                raise ApplicationError("Проверьте решение по сопоставлению.")
            catalog_public.review_match(request_id=form.cleaned_data["request_id"], approve=form.cleaned_data["approve"], identity_confirmed=form.cleaned_data["identity_confirmed"], reason=form.cleaned_data["reason"], context=context)
        elif action == "review_suggestion":
            form = SuggestionReviewForm(request.POST)
            if not form.is_valid():
                raise ApplicationError("Проверьте ответ на предложение.")
            catalog_public.review_suggestion(suggestion_id=form.cleaned_data["suggestion_id"], response=form.cleaned_data["response"], context=context)
        else:
            raise ApplicationError("Неизвестное действие управления.")
        return _redirect_303(reverse("catalog-manage"))
    except (ApplicationError, ObjectDoesNotExist, ValueError) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError(str(error)))


@require_http_methods(["GET", "POST"])
@_login_required
def catalog_manage_category(request, *, category_id):
    try:
        categories = catalog_public.list_categories(context=_context(request), include_inactive=True)
        category = next(row for row in categories if row["id"] == str(category_id))
        if request.method == "GET":
            return _catalog_render(request, "catalog/category.html", {
                "category": category,
                "form": CategoryForm(initial={"name": category["name"], "active": category["active"], "expected_version": category["version"]}),
                "attribute_formset": AttributeFormSet(prefix="attributes", initial=attribute_formset_initial(category)),
                "reauth_url": reverse("reauthenticate"),
            })
        form = CategoryForm(request.POST)
        formset = AttributeFormSet(request.POST, prefix="attributes")
        if not form.is_valid() or not formset.is_valid():
            return _catalog_render(request, "catalog/category.html", {"category": category, "form": form, "attribute_formset": formset, "message": "Проверьте категорию и характеристики.", "reauth_url": reverse("reauthenticate")}, status=400)
        catalog_public.update_category(category_id=category_id, name=form.cleaned_data["name"], attributes=formset.as_definitions(), active=form.cleaned_data["active"], expected_version=form.cleaned_data["expected_version"], context=_context(request))
        return _redirect_303(reverse("catalog-manage-category", kwargs={"category_id": category_id}))
    except (ApplicationError, ObjectDoesNotExist, ValueError, StopIteration) as error:
        return _application_error(request, error if isinstance(error, ApplicationError) else ApplicationError("Категория недоступна."))
