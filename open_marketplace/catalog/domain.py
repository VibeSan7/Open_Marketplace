import re
from decimal import Decimal, InvalidOperation

from open_marketplace.common.errors import InputRejected

UNITS = {"pc": "шт.", "kg": "кг", "m": "м"}


def _decimal_value(raw, places, *, allow_empty=False):
    if raw is None or raw == "":
        if allow_empty:
            return None
        raise InputRejected("Укажите значение: пустое поле не равно нулю.")
    if isinstance(raw, Decimal):
        value = raw
    elif type(raw) in (str, int):
        text = str(raw).strip()
        if len(text) > 128 or re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", text) is None:
            raise InputRejected("Введите неотрицательное десятичное число без пробелов и экспоненты.")
        value = Decimal(text.replace(",", "."))
    else:
        raise InputRejected("Число передаётся обычной десятичной строкой.")
    if not value.is_finite() or value < 0 or value >= Decimal("10000000000000000"):
        raise InputRejected("Допустимо неотрицательное число с не более чем 16 цифрами целой части.")
    try:
        exact = value.quantize(Decimal(1).scaleb(-places))
    except InvalidOperation:
        raise InputRejected("Число выходит за допустимые пределы.") from None
    if value != exact:
        raise InputRejected(f"Допустимо не более {places} дробных знаков. Значение не округлено.")
    return exact


def price_value(raw, *, currency="RUB", allow_empty=False):
    if currency != "RUB":
        raise InputRejected("В этом каталоге цена указывается только в рублях.")
    return _decimal_value(raw, 2, allow_empty=allow_empty)


def stock_value(raw, unit, *, allow_empty=False):
    if unit not in UNITS:
        raise InputRejected("Выберите единицу: штуки, килограммы или метры.")
    return _decimal_value(raw, 0 if unit == "pc" else 3, allow_empty=allow_empty)


def price_label(value, *, different=False):
    if value == 0 and not different:
        return "Бесплатно"
    amount = f"{value:.2f}".replace(".", ",")
    return f"от {amount} ₽" if different else f"{amount} ₽"
