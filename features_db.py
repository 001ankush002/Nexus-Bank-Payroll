"""
Fund Transfer + Bulk Payroll (database layer)
Aapke config.py aur db.py ke saath kaam karta hai - alag password/config nahi chahiye.
"""
import random
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import mysql.connector

import config as cfg
from db import Database

DAILY_TRANSFER_LIMIT = Decimal(str(getattr(cfg, "DAILY_TRANSFER_LIMIT", 200000)))


def _db_settings():
    """config.py me jo MySQL settings dict hai (host/user/password/database) use dhundta hai."""
    for value in vars(cfg).values():
        if isinstance(value, dict) and "host" in value and "database" in value:
            return dict(value)
    raise RuntimeError("config.py me MySQL settings dict nahi mila (host, user, password, database).")


def get_conn():
    return mysql.connector.connect(**_db_settings())


def money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def init_tables():
    con = get_conn()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS fund_transfers (
        transfer_id INT AUTO_INCREMENT PRIMARY KEY,
        reference_no VARCHAR(30) UNIQUE,
        from_account INT NOT NULL,
        to_account INT NOT NULL,
        amount DECIMAL(12,2) NOT NULL,
        remark VARCHAR(100),
        transfer_date DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bulk_attendance (
        emp_id INT NOT NULL,
        pay_month CHAR(7) NOT NULL,
        working_days INT NOT NULL,
        days_present INT NOT NULL,
        PRIMARY KEY (emp_id, pay_month))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bulk_payroll_runs (
        emp_id INT NOT NULL,
        pay_month CHAR(7) NOT NULL,
        gross DECIMAL(12,2), leave_deduction DECIMAL(12,2),
        tax DECIMAL(12,2), net DECIMAL(12,2),
        status VARCHAR(30), paid_on DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (emp_id, pay_month))""")
    # Agar transaction_type ENUM hai to 'Transfer In/Out' fail honge - VARCHAR bana do
    try:
        cur.execute("ALTER TABLE Transactions MODIFY transaction_type VARCHAR(30) NOT NULL")
    except Exception:
        pass
    con.commit()
    con.close()


# ---------------- FUND TRANSFER ----------------
def transfer_funds(src, dst, amount, remark=""):
    """Debit + credit ek hi safe transaction me. Reference number return karta hai."""
    amount = money(amount)
    if src == dst:
        raise ValueError("Sender aur receiver account same nahi ho sakte.")
    if amount <= 0:
        raise ValueError("Amount 0 se zyada hona chahiye.")

    con = get_conn()
    try:
        con.start_transaction()
        cur = con.cursor()
        cur.execute("SELECT account_number, current_balance FROM Customers "
                    "WHERE account_number IN (%s,%s) ORDER BY account_number FOR UPDATE",
                    (src, dst))
        rows = {r[0]: Decimal(str(r[1])) for r in cur.fetchall()}
        if src not in rows:
            raise ValueError(f"Sender account {src} nahi mila.")
        if dst not in rows:
            raise ValueError(f"Receiver account {dst} nahi mila.")
        if rows[src] < amount:
            raise ValueError("Insufficient balance.")

        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fund_transfers "
                    "WHERE from_account=%s AND DATE(transfer_date)=CURDATE()", (src,))
        sent_today = Decimal(str(cur.fetchone()[0]))
        if sent_today + amount > DAILY_TRANSFER_LIMIT:
            raise ValueError(f"Daily transfer limit Rs.{DAILY_TRANSFER_LIMIT:,.0f} cross ho jayegi "
                             f"(aaj bheja: Rs.{sent_today:,.2f}).")

        cur.execute("UPDATE Customers SET current_balance=current_balance-%s WHERE account_number=%s",
                    (amount, src))
        cur.execute("UPDATE Customers SET current_balance=current_balance+%s WHERE account_number=%s",
                    (amount, dst))

        ref = "TRF" + datetime.now().strftime("%y%m%d%H%M%S") + str(random.randint(100, 999))
        cur.execute("INSERT INTO fund_transfers (reference_no, from_account, to_account, amount, remark) "
                    "VALUES (%s,%s,%s,%s,%s)", (ref, src, dst, amount, remark))
        cur.execute("INSERT INTO Transactions (account_number, transaction_type, amount, transaction_date) "
                    "VALUES (%s,'Transfer Out',%s,NOW())", (src, amount))
        cur.execute("INSERT INTO Transactions (account_number, transaction_type, amount, transaction_date) "
                    "VALUES (%s,'Transfer In',%s,NOW())", (dst, amount))
        con.commit()
        return ref
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_customer(acc):
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT customer_name, current_balance FROM Customers WHERE account_number=%s", (acc,))
    row = cur.fetchone()
    con.close()
    return row


def recent_transfers(limit=10):
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT reference_no, from_account, to_account, amount, transfer_date "
                "FROM fund_transfers ORDER BY transfer_id DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


# ---------------- BULK PAYROLL & ATTENDANCE ----------------
def calc_salary(basic, working_days, present):
    basic = money(basic)
    per_day = basic / Decimal(working_days)
    leave_ded = money(per_day * Decimal(max(working_days - present, 0)))
    taxable = basic - leave_ded
    rate = Decimal("0") if taxable <= 25000 else (Decimal("0.05") if taxable <= 50000 else Decimal("0.10"))
    tax = money(taxable * rate)
    return {"gross": basic, "leave_ded": leave_ded, "tax": tax, "net": taxable - tax}


def _month_label(month):
    """'2026-09' -> 'September 2026' (aapke Process Payroll page ka format)."""
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def get_employees():
    """[(id, name, designation, basic, account_or_None), ...] - aapke db.get_employees() se."""
    return [(e["employee_id"], e["employee_name"], e["designation"] or "-",
             e["basic_salary"], e["account_number"])
            for e in Database().get_employees()]


def get_attendance(month):
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT emp_id, days_present FROM bulk_attendance WHERE pay_month=%s", (month,))
    rows = dict(cur.fetchall())
    con.close()
    return rows


def get_paid_ids(month):
    """Bulk payroll se paid + Process Payroll page se (usi mahine me) paid, dono."""
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT emp_id FROM bulk_payroll_runs WHERE pay_month=%s", (month,))
    ids = {r[0] for r in cur.fetchall()}
    con.close()
    try:
        ids |= set(Database().get_paid_employee_ids(_month_label(month)))
    except Exception:
        pass
    return ids


def set_attendance(emp_id, month, working_days, present):
    if not (0 <= present <= working_days):
        raise ValueError("Present days 0 se working days ke beech hone chahiye.")
    con = get_conn()
    cur = con.cursor()
    cur.execute("INSERT INTO bulk_attendance (emp_id, pay_month, working_days, days_present) "
                "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                "working_days=VALUES(working_days), days_present=VALUES(days_present)",
                (emp_id, month, working_days, present))
    con.commit()
    con.close()


def run_bulk_payroll(month, working_days):
    """Sabhi unpaid employees ko ek saath pay karta hai. Double payment nahi hoti."""
    employees = get_employees()
    already = get_paid_ids(month)
    con = get_conn()
    paid, total = 0, Decimal("0")
    try:
        con.start_transaction()
        cur = con.cursor()
        cur.execute("SELECT emp_id, days_present FROM bulk_attendance WHERE pay_month=%s", (month,))
        att = dict(cur.fetchall())

        for eid, name, desig, basic, acct in employees:
            if eid in already:
                continue
            present = att.get(eid, working_days)
            s = calc_salary(basic, working_days, present)
            status = "No A/C (Cash)"
            if acct:
                cur.execute("UPDATE Customers SET current_balance=current_balance+%s "
                            "WHERE account_number=%s", (s["net"], acct))
                if cur.rowcount == 1:
                    cur.execute("INSERT INTO Transactions (account_number, transaction_type, amount, "
                                "transaction_date) VALUES (%s,'Salary Credit',%s,NOW())",
                                (acct, s["net"]))
                    status = "Credited"
            cur.execute("INSERT INTO bulk_payroll_runs (emp_id, pay_month, gross, leave_deduction, tax, net, status) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (eid, month, s["gross"], s["leave_ded"], s["tax"], s["net"], status))
            paid += 1
            total += s["net"]
        con.commit()
        return paid, total
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()