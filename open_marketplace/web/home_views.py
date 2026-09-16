from django.http import HttpResponseNotAllowed
from django.urls import reverse

from open_marketplace.catalog import public as catalog_public
from open_marketplace.web.errors import secure_render, secure_response
from open_marketplace.web.identity_views import _context


def _storefront(request):
    result = catalog_public.search_catalog(
        query="", category_id=None, filters={}, cursor=None,
        price_min=None, price_max=None, sort="relevance",
        context=_context(request, anonymous=True),
    )
    items = []
    covers_by_category = {}
    for source in result["items"]:
        item = dict(source)
        item["url"] = reverse("catalog-product", kwargs={"product_id": item["id"]})
        items.append(item)
        key = str(item.get("category_id") or item.get("category") or "")
        if key and item.get("cover_id") and key not in covers_by_category:
            covers_by_category[key] = item["cover_id"]
    categories = []
    for source in result["categories"]:
        category = dict(source)
        category_id = str(category["id"])
        category["id"] = category_id
        category["url"] = f'{reverse("catalog-search")}?category={category_id}'
        category["cover_id"] = covers_by_category.get(category_id) or covers_by_category.get(str(category.get("name", "")))
        categories.append(category)
    return {"categories": categories, "items": items[:12], "total": result["total"]}


def home(request):
    if request.method not in {"GET", "HEAD"}:
        return secure_response(HttpResponseNotAllowed(("GET", "HEAD")))
    return secure_render(request, "home.html", {"storefront": _storefront(request)})
