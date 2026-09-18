from django.urls import include, path

from open_marketplace.staff_admin.site import staff_admin_site
from open_marketplace.web.home_views import home
from open_marketplace.web.demo_content_views import demo_image_credits
from open_marketplace.web.setup_views import setup_guide

urlpatterns = [
    path("", home, name="home"),
    path("setup/", setup_guide, name="setup-guide"),
    path("demo-content/credits/", demo_image_credits, name="demo-image-credits"),
    path("admin/", staff_admin_site.urls),
    path("catalog/", include("open_marketplace.web.catalog_urls")),
    path("demo-orders/", include("open_marketplace.demo_orders.urls")),
    path("cart/", include("open_marketplace.demo_orders.cart_urls")),
    path("commerce-cart/", include("open_marketplace.web.commerce_cart_urls")),
    path("commerce-orders/", include("open_marketplace.web.commerce_order_urls")),
    path("", include("open_marketplace.web.urls")),
]

handler500 = "open_marketplace.web.errors.handler500"
