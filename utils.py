"""
utils.py - chhote helper functions (money format, input parsing, validation)
"""
import re
from decimal import Decimal, InvalidOperation

MAX_AMOUNT = Decimal("9999999999.99")


def format_inr(value, symbol=True, decimals=2):
    """1234567.5 -> '₹ 12,34,567.50'  (Indian digit grouping)."""
    quantum = Decimal(10) ** -decimals
    value = Decimal(value).quantize(quantum)
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):.{decimals}f}".partition(".")

    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])

    text = whole + (f".{frac}" if frac else "")
    return f"{sign}{'₹ ' if symbol else ''}{text}"


def parse_amount(text, field="Amount", allow_zero=False):
    """String -> Decimal (2 places). ValueError with a friendly message if invalid."""
    text = (text or "").replace(",", "").strip()
    if not text:
        raise ValueError(f"{field} is required.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{field} must be a valid number.") from None
    if not value.is_finite():
        raise ValueError(f"{field} must be a valid number.")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{field} must be greater than 0.")
    if value > MAX_AMOUNT:
        raise ValueError(f"{field} is too large.")
    return value.quantize(Decimal("0.01"))


def parse_id(text, label="ID"):
    """Account number / employee id / loan id -> int."""
    text = (text or "").strip()
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"Enter a valid {label} (digits only).")
    return int(text)


def is_valid_phone(phone):
    return re.fullmatch(r"[6-9]\d{9}", phone or "") is not None


def is_valid_email(email):
    return re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", email or "") is not None


def shade(hex_color, factor=0.85):
    """Hex color ko thoda dark karta hai (button hover ke liye)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(*(min(255, int(c * factor)) for c in (r, g, b)))