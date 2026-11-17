from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

ZERO = Decimal("0")
DISPLAY_PLACES = Decimal("0.01")


def parse_decimal(value) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"Float rejected — use string decimal for money: {value}")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Cannot parse as Decimal: {value!r}")


def decimal_to_str(value: Decimal) -> str:
    return str(value)


def display_amount(value: Decimal, currency: str = "") -> str:
    rounded = value.quantize(DISPLAY_PLACES, rounding=ROUND_HALF_UP)
    return f"{rounded} {currency}".strip()


def abs_diff(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b)
