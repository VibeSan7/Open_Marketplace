from django.urls import path

from . import commerce_order_views


urlpatterns = [
    path("", commerce_order_views.commerce_order_list, name="commerce-orders"),
    path("<uuid:order_id>/", commerce_order_views.commerce_order_detail, name="commerce-order-detail"),
    path("<uuid:order_id>/cancel/", commerce_order_views.commerce_order_cancel, name="commerce-order-cancel"),
]
