import re
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings

from open_marketplace.common.errors import InputRejected


DEMO_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/VibeSan7/Open_Marketplace/demo/storefront/v1")


def demo_identifier(kind, key):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key):
        raise InputRejected("Неверный идентификатор демонстрационного объекта.")
    return uuid5(DEMO_NAMESPACE, f"{kind}:{key}")


def require_demo_content(*, confirmed):
    if not getattr(settings, "DEMO_CONTENT_ENABLED", False):
        raise InputRejected("Для наполнения включите DEMO_CONTENT_ENABLED=true только в демонстрационной установке.")
    if confirmed is not True:
        raise InputRejected("Для добавления учебных данных требуется --confirm-demo.")
