from django.conf import settings


def public_features(request):
    return {"demo_orders_enabled": settings.DEMO_ORDERS_ENABLED}
