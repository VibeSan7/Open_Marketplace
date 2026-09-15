from django.urls import path

from open_marketplace.web import catalog_views


urlpatterns = [
    path("", catalog_views.catalog_search, name="catalog-search"),
    path("p/<uuid:product_id>/", catalog_views.catalog_product, name="catalog-product"),
    path("photo/<uuid:photo_id>/", catalog_views.catalog_photo, name="catalog-photo"),
    path("own/", catalog_views.own_products, name="catalog-own"),
    path("own/new/", catalog_views.own_product_new, name="catalog-own-new"),
    path("own/<uuid:product_id>/", catalog_views.own_product, name="catalog-own-product"),
    path("manage/", catalog_views.catalog_manage, name="catalog-manage"),
    path("manage/category/<uuid:category_id>/", catalog_views.catalog_manage_category, name="catalog-manage-category"),
]
