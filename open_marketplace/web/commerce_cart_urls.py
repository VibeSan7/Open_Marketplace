from django.urls import path

from . import commerce_cart_views


urlpatterns = [
    path("", commerce_cart_views.commerce_cart, name="commerce-cart"),
    path("add/<uuid:variant_id>/", commerce_cart_views.commerce_cart_add, name="commerce-cart-add"),
    path("items/<uuid:variant_id>/", commerce_cart_views.commerce_cart_update, name="commerce-cart-update"),
    path("checkout/", commerce_cart_views.commerce_cart_checkout, name="commerce-cart-checkout"),
]
