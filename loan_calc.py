"""
loan_calc.py - loan maths (reducing-balance, real-bank style)

Rules yahin se badlo:
  DEFAULT_RATE                 default interest (% per year)
  TENURES                      tenure options (months)
  FORECLOSURE_CHARGE_PERCENT   loan jaldi close karne ka charge (% of outstanding); 0 = koi charge nahi
"""
import math
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_RATE = Decimal("10.5")          # % per annum
DEFAULT_TENURE = 12                     # months
TENURES = [6, 12, 24, 36, 48, 60]       # dropdown options (months)
MIN_RATE = Decimal("1")
MAX_RATE = Decimal("36")
FORECLOSURE_CHARGE_PERCENT = Decimal("2")

_CENT = Decimal("0.01")


def money(value):
    """2 decimal places, half-up (bank style rounding)."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def monthly_rate(annual_percent):
    return Decimal(annual_percent) / Decimal(1200)


def calculate_emi(principal, annual_percent, months):
    """EMI = P*r*(1+r)^n / ((1+r)^n - 1)   (r = monthly rate)."""
    principal = Decimal(principal)
    if months <= 0:
        raise ValueError("Tenure must be at least 1 month.")
    r = monthly_rate(annual_percent)
    if r == 0:
        return money(principal / months)
    factor = (1 + r) ** months
    return money(principal * r * factor / (factor - 1))


def next_installment(outstanding, annual_percent, emi, emis_paid, tenure):
    """Agli EMI ka breakup: interest (outstanding par 1 mahine ka) + principal.
    Aakhri EMI (ya jab baaki rakam EMI se kam ho) me poori baaki rakam le li jaati hai."""
    outstanding = Decimal(outstanding)
    emi = Decimal(emi)
    interest = money(outstanding * monthly_rate(annual_percent))
    is_last = (emis_paid + 1 >= tenure) or (outstanding + interest <= emi)
    payment = money(outstanding + interest) if is_last else emi
    return {
        "interest": interest,
        "principal": payment - interest,
        "payment": payment,
        "is_last": is_last,
    }


def closure_quote(outstanding, annual_percent, charge_percent=None):
    """Loan foreclose karne ka total: outstanding principal + is cycle ka interest + foreclosure charge."""
    if charge_percent is None:
        charge_percent = FORECLOSURE_CHARGE_PERCENT
    outstanding = Decimal(outstanding)
    interest = money(outstanding * monthly_rate(annual_percent))
    charge = money(outstanding * Decimal(charge_percent) / 100)
    return {
        "principal": outstanding,
        "interest": interest,
        "charge": charge,
        "total": outstanding + interest + charge,
    }


def remaining_emis(outstanding, annual_percent, emi):
    """Kitni EMIs baaki hain (estimate, sirf dikhane ke liye)."""
    p, e = float(outstanding), float(emi)
    if p <= 0 or e <= 0:
        return 0
    r = float(monthly_rate(annual_percent))
    if r == 0:
        return math.ceil(p / e)
    if e <= p * r:            # EMI interest bhi cover nahi karti
        return None
    return math.ceil(-math.log(1 - p * r / e) / math.log(1 + r))


def parse_rate(text):
    """'10.5' -> Decimal. ValueError agar range se bahar ho."""
    try:
        rate = Decimal((text or "").strip())
    except Exception:
        raise ValueError("Interest rate must be a number, e.g. 10.5") from None
    if not rate.is_finite() or rate < MIN_RATE or rate > MAX_RATE:
        raise ValueError(f"Interest rate must be between {MIN_RATE}% and {MAX_RATE}%.")
    return rate.quantize(_CENT)