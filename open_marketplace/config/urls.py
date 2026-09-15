from django.urls import include, path

from open_marketplace.staff_admin.site import staff_admin_site

urlpatterns = [
    path("admin/", staff_admin_site.urls),
    path("catalog/", include("open_marketplace.web.catalog_urls")),
    path("", include("open_marketplace.web.urls")),
]

handler500 = "open_marketplace.web.errors.handler500"
