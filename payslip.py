"""
payslip.py - salary calculation + PDF salary slip (fpdf / fpdf2 dono ke saath chalta hai)
"""
from datetime import datetime
from decimal import Decimal

from fpdf import FPDF

from utils import format_inr

# ---- Salary rules (yahan change kar sakte ho) ----
HRA_PERCENT = Decimal("0.40")     # basic ka 40%
DA_PERCENT = Decimal("0.10")      # basic ka 10%
PF_PERCENT = Decimal("0.12")      # basic ka 12% (deduction)
PROFESSIONAL_TAX = Decimal("200")  # flat monthly deduction

_CENT = Decimal("0.01")


def calculate_salary(basic, bonus=Decimal("0")):
    """Basic + bonus se poora salary breakup (Decimal values) return karta hai."""
    basic = Decimal(basic).quantize(_CENT)
    bonus = Decimal(bonus).quantize(_CENT)
    hra = (basic * HRA_PERCENT).quantize(_CENT)
    da = (basic * DA_PERCENT).quantize(_CENT)
    pf = (basic * PF_PERCENT).quantize(_CENT)
    gross = basic + hra + da + bonus
    deductions = pf + PROFESSIONAL_TAX
    return {
        "basic": basic,
        "hra": hra,
        "da": da,
        "bonus": bonus,
        "gross": gross,
        "pf": pf,
        "prof_tax": PROFESSIONAL_TAX,
        "deductions": deductions,
        "net": gross - deductions,
    }


def _safe(text):
    """Built-in PDF fonts sirf latin-1 support karte hain; baaki characters '?' ban jaate hain."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _money(value):
    return format_inr(value, symbol=False)


def generate_salary_slip(file_path, employee, month, salary, payment=None):
    """Ek page ka salary slip PDF file_path par save karta hai.
    payment = Payroll row (dict) agar salary pay ho chuki hai, warna None."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # ---- Header band ----
    pdf.set_fill_color(26, 76, 138)
    pdf.rect(0, 0, 210, 36, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_xy(15, 9)
    pdf.cell(100, 10, "NEXUS BANK")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(15, 21)
    pdf.cell(100, 6, "Bank & Payroll - Pro Max")
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_xy(115, 12)
    pdf.cell(80, 8, "SALARY SLIP", align="R")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(115, 21)
    pdf.cell(80, 6, _safe(month), align="R")

    # ---- Employee details ----
    pdf.set_text_color(30, 30, 30)
    pdf.set_xy(15, 46)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(180, 8, "Employee Details")
    pdf.ln(10)

    details = [
        ("Employee ID", employee["employee_id"]),
        ("Employee Name", employee["employee_name"]),
        ("Designation", employee.get("designation") or "-"),
        ("Pay Period", month),
        ("Generated On", datetime.now().strftime("%d-%b-%Y %I:%M %p")),
    ]
    for label, value in details:
        pdf.set_x(15)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(45, 7, label)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(135, 7, ": " + _safe(value))
        pdf.ln(7)

    # ---- Earnings / Deductions table ----
    pdf.ln(8)
    widths = [55, 35, 55, 35]

    pdf.set_x(15)
    pdf.set_fill_color(26, 76, 138)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    for w, title, align in zip(
        widths, ["EARNINGS", "AMOUNT (Rs.)", "DEDUCTIONS", "AMOUNT (Rs.)"], ["L", "R", "L", "R"]
    ):
        pdf.cell(w, 9, title, border=1, align=align, fill=True)
    pdf.ln(9)

    earnings = [
        ("Basic Salary", salary["basic"]),
        (f"HRA ({int(HRA_PERCENT * 100)}%)", salary["hra"]),
        (f"DA ({int(DA_PERCENT * 100)}%)", salary["da"]),
        ("Bonus", salary["bonus"]),
    ]
    deductions = [
        (f"Provident Fund ({int(PF_PERCENT * 100)}%)", salary["pf"]),
        ("Professional Tax", salary["prof_tax"]),
        ("", None),
        ("", None),
    ]

    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 10)
    for (e_label, e_val), (d_label, d_val) in zip(earnings, deductions):
        pdf.set_x(15)
        pdf.cell(widths[0], 8, e_label, border=1)
        pdf.cell(widths[1], 8, _money(e_val), border=1, align="R")
        pdf.cell(widths[2], 8, d_label, border=1)
        pdf.cell(widths[3], 8, _money(d_val) if d_val is not None else "", border=1, align="R")
        pdf.ln(8)

    pdf.set_x(15)
    pdf.set_fill_color(228, 236, 247)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(widths[0], 9, "Gross Earnings", border=1, fill=True)
    pdf.cell(widths[1], 9, _money(salary["gross"]), border=1, align="R", fill=True)
    pdf.cell(widths[2], 9, "Total Deductions", border=1, fill=True)
    pdf.cell(widths[3], 9, _money(salary["deductions"]), border=1, align="R", fill=True)
    pdf.ln(9)

    # ---- Net salary ----
    pdf.ln(6)
    pdf.set_x(15)
    pdf.set_fill_color(26, 76, 138)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(120, 13, "  NET SALARY PAYABLE", border=1, fill=True)
    pdf.cell(60, 13, "Rs. " + _money(salary["net"]) + "  ", border=1, align="R", fill=True)
    pdf.ln(13)

    # ---- Payment status ----
    pdf.ln(7)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "B", 11)
    if payment:
        paid_on = payment.get("generated_on")
        when = paid_on.strftime("%d-%b-%Y %I:%M %p") if hasattr(paid_on, "strftime") else ""
        pdf.set_text_color(20, 130, 70)
        status = (f"PAID - Rs. {_money(payment['net_salary'])} credited to "
                  f"A/C {payment['account_number']} on {when}")
    else:
        pdf.set_text_color(200, 120, 0)
        status = "PAYMENT PENDING - salary not yet credited"
    pdf.cell(180, 8, _safe(status))

    # ---- Footer ----
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_y(-28)
    pdf.cell(0, 6, "This is a computer-generated salary slip and does not require a signature.", align="C")

    pdf.output(str(file_path))