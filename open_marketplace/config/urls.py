from django.urls import include, path

urlpatterns = [path("", include("open_marketplace.web.urls"))]

handler500 = "open_marketplace.web.errors.handler500"
