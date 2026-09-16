from django.urls import path

from open_marketplace.web import catalog_views


urlpatterns = [
    path("", catalog_views.catalog_search, name="catalog-search"),
    path("p/<uuid:product_id>/", catalog_views.catalog_product, name="catalog-product"),
    path("p/<uuid:product_id>/saved/", catalog_views.save_product, name="catalog-save-product"),
    path("saved/", catalog_views.saved_products, name="catalog-saved"),
    path("sellers/<uuid:seller_id>/", catalog_views.seller_store, name="catalog-seller"),
    path("photo/<uuid:photo_id>/", catalog_views.catalog_photo, name="catalog-photo"),
    path("own/", catalog_views.own_products, name="catalog-own"),
    path("own/new/", catalog_views.own_product_new, name="catalog-own-new"),
    path("own/<uuid:product_id>/", catalog_views.own_product, name="catalog-own-product"),
    path("own/<uuid:product_id>/preview/", catalog_views.own_product_preview, name="catalog-own-preview"),
    path("manage/", catalog_views.catalog_manage, name="catalog-manage"),
    path("manage/category/<uuid:category_id>/", catalog_views.catalog_manage_category, name="catalog-manage-category"),
]
