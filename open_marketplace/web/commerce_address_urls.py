from django.urls import path

from . import commerce_address_views


urlpatterns = [
    path("", commerce_address_views.commerce_address_list, name="commerce-address-list"),
    path("new/", commerce_address_views.commerce_address_new, name="commerce-address-new"),
]
