"""
Self-Service Dispute Freeze
----------------------------
Asli bank mein dispute file karne ke baad fraud team involve hoti hai, investigation
me din-hafte lagte hain. Yahan customer khud kisi transaction ko "disputed" mark kar
sakta hai aur uska amount turant freeze ho jaata hai - koi fraud team ki zarurat nahi.
Baad me ek click se resolve hota hai: Approve (paisa wapas) ya Reject (hold hata do).

Undo Window (2 min) ke muqable dispute filing window kaafi zyada hai - default 7 din -
taaki purani transaction bhi dispute ki ja sake, sirf turant wali nahi.
"""
from decimal import Decimal

import mysql.connector

import config as cfg

WINDOW_DAYS = int(getattr(cfg, "DISPUTE_WINDOW_DAYS", 7))

# transaction types jinse balance kam hota hai - resolve karte waqt reversal ki
# direction decide karne ke liye (main.py ke DEBIT_TYPES jaisa hi)
DEBIT_TYPES = {"Withdraw", "Loan EMI", "Loan Part-Payment", "Loan Closure", "Transfer Out",
              "Deposit Undo", "Transfer Undo Out", "Dispute Resolved (Debit)"}


def get_conn():
    return mysql.connector.connect(**cfg.DB_CONFIG)


def init_table():
    con = get_conn()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS disputes (
        dispute_id INT AUTO_INCREMENT PRIMARY KEY,
        transaction_id INT NOT NULL UNIQUE,
        account_number INT NOT NULL,
        transaction_type VARCHAR(30) NOT NULL,
        amount DECIMAL(15,2) NOT NULL,
        reason VARCHAR(255),
        status VARCHAR(20) NOT NULL DEFAULT 'Open',
        filed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved_at DATETIME,
        resolution_note VARCHAR(255))""")
    con.commit()
    con.close()


def held_amount(account_number):
    """Is account par abhi kitna paisa freeze hai (sabhi Open disputes ka total)."""
    init_table()
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM disputes WHERE account_number=%s AND status='Open'",
                (account_number,))
    total = Decimal(str(cur.fetchone()[0]))
    con.close()
    return total


def available_balance(account_number):
    """Balance jo abhi kharch/transfer kiya ja sakta hai (raw balance - held amount)."""
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT current_balance FROM Customers WHERE account_number=%s", (account_number,))
    row = cur.fetchone()
    con.close()
    if not row:
        raise ValueError(f"Account {account_number} nahi mila.")
    return Decimal(str(row[0])) - held_amount(account_number)


def get_recent_transactions(account_number):
    """Pichhle WINDOW_DAYS din ki transactions, saath me agar pehle se disputed hai to uska status."""
    init_table()
    con = get_conn()
    cur = con.cursor(dictionary=True)
    cur.execute(
        "SELECT t.transaction_id, t.transaction_type, t.amount, t.transaction_date, d.status AS dispute_status "
        "FROM Transactions t LEFT JOIN disputes d ON d.transaction_id = t.transaction_id "
        "WHERE t.account_number=%s AND t.transaction_date >= DATE_SUB(NOW(), INTERVAL %s DAY) "
        "ORDER BY t.transaction_date DESC", (account_number, WINDOW_DAYS))
    rows = cur.fetchall()
    con.close()
    return rows


def file_dispute(transaction_id, reason):
    """Turant freeze karta hai - kisi approval ki zarurat nahi. Dispute row return karta hai."""
    init_table()
    con = get_conn()
    try:
        con.start_transaction()
        cur = con.cursor(dictionary=True)
        cur.execute(
            "SELECT transaction_id, account_number, transaction_type, amount, transaction_date, "
            "transaction_date < DATE_SUB(NOW(), INTERVAL %s DAY) AS too_old "
            "FROM Transactions WHERE transaction_id=%s FOR UPDATE", (WINDOW_DAYS, transaction_id))
        txn = cur.fetchone()
        if not txn:
            raise ValueError("Transaction nahi mili.")
        if txn["too_old"]:
            raise ValueError(f"Ye transaction {WINDOW_DAYS} din se purani hai - ab dispute nahi ho sakti.")

        cur.execute("SELECT status FROM disputes WHERE transaction_id=%s", (transaction_id,))
        existing = cur.fetchone()
        if existing:
            raise ValueError(f"Ye transaction pehle hi dispute ki ja chuki hai (status: {existing['status']}).")

        cur.execute(
            "INSERT INTO disputes (transaction_id, account_number, transaction_type, amount, reason, status) "
            "VALUES (%s,%s,%s,%s,%s,'Open')",
            (txn["transaction_id"], txn["account_number"], txn["transaction_type"], txn["amount"], reason))
        con.commit()
        return {"dispute_id": cur.lastrowid, "account_number": txn["account_number"],
                "amount": Decimal(str(txn["amount"])), "transaction_type": txn["transaction_type"]}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_disputes(status=None):
    """Sabhi disputes, customer naam ke saath - status se filter kar sakte ho (e.g. 'Open')."""
    init_table()
    con = get_conn()
    cur = con.cursor(dictionary=True)
    query = ("SELECT d.*, c.customer_name FROM disputes d "
             "JOIN Customers c ON c.account_number = d.account_number ")
    params = ()
    if status:
        query += "WHERE d.status=%s "
        params = (status,)
    query += "ORDER BY d.dispute_id DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    con.close()
    return rows


def _insert_txn(cur, account, ttype, amount):
    cur.execute(
        "INSERT INTO Transactions (account_number, transaction_type, amount, transaction_date) "
        "VALUES (%s,%s,%s,NOW())", (account, ttype, amount))


def resolve(dispute_id, approve, note=""):
    """Approve = paisa customer ko wapas (ya galat credit wapas le lo). Reject = sirf hold hatta hai."""
    con = get_conn()
    try:
        con.start_transaction()
        cur = con.cursor(dictionary=True)
        cur.execute("SELECT * FROM disputes WHERE dispute_id=%s FOR UPDATE", (dispute_id,))
        d = cur.fetchone()
        if not d:
            raise ValueError("Ye dispute ab maujood nahi hai.")
        if d["status"] != "Open":
            raise ValueError(f"Ye dispute pehle hi {d['status']} ho chuka hai.")

        acc = d["account_number"]
        amount = Decimal(str(d["amount"]))
        direction = "debit" if d["transaction_type"] in DEBIT_TYPES else "credit"

        if approve:
            if direction == "debit":
                # Customer se galat/bina-authorize paisa kata tha - wapas credit karo
                cur.execute("UPDATE Customers SET current_balance=current_balance+%s WHERE account_number=%s",
                            (amount, acc))
                _insert_txn(cur, acc, "Dispute Resolved (Credit)", amount)
                desc = f"Dispute #{dispute_id} approved - {amount} credited back to account {acc}."
            else:
                # Account me galat paisa aaya tha - wapas le lo
                cur.execute("SELECT current_balance FROM Customers WHERE account_number=%s FOR UPDATE", (acc,))
                bal = Decimal(str(cur.fetchone()["current_balance"]))
                if bal < amount:
                    raise ValueError("Balance kam hai - is galat credit ko wapas nahi liya ja sakta.")
                cur.execute("UPDATE Customers SET current_balance=current_balance-%s WHERE account_number=%s",
                            (amount, acc))
                _insert_txn(cur, acc, "Dispute Resolved (Debit)", amount)
                desc = f"Dispute #{dispute_id} approved - {amount} debited back from account {acc}."
            new_status = "Approved"
        else:
            desc = f"Dispute #{dispute_id} rejected - hold released, balance unchanged."
            new_status = "Rejected"

        cur.execute("UPDATE disputes SET status=%s, resolved_at=NOW(), resolution_note=%s WHERE dispute_id=%s",
                    (new_status, note, dispute_id))
        con.commit()
        return desc
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()