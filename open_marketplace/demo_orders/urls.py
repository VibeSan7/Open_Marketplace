from django.urls import path

from . import views


urlpatterns = [
    path("", views.demo_orders, name="demo-orders"),
    path("new/<uuid:variant_id>/", views.demo_order_create, name="demo-order-create"),
    path("<uuid:order_id>/", views.demo_order_detail, name="demo-order-detail"),
    path("<uuid:order_id>/action/", views.demo_order_action, name="demo-order-action"),
]
