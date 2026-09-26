from django.urls import path

from . import commerce_fulfillment_views


urlpatterns = [
    path("", commerce_fulfillment_views.commerce_fulfillment_list, name="commerce-fulfillment-list"),
    path("<uuid:shipment_id>/", commerce_fulfillment_views.commerce_fulfillment_detail, name="commerce-fulfillment-detail"),
    path(
        "<uuid:shipment_id>/transition/",
        commerce_fulfillment_views.commerce_fulfillment_transition,
        name="commerce-fulfillment-transition",
    ),
    path(
        "<uuid:shipment_id>/packages/",
        commerce_fulfillment_views.commerce_fulfillment_packages,
        name="commerce-fulfillment-packages",
    ),
]
