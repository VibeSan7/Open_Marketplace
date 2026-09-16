from django.urls import path

from . import cart_views


urlpatterns = [
    path("", cart_views.cart, name="cart"),
    path("add/<uuid:variant_id>/", cart_views.cart_add, name="cart-add"),
    path("items/<uuid:variant_id>/", cart_views.cart_update, name="cart-update"),
    path("checkout/", cart_views.cart_checkout, name="cart-checkout"),
]
