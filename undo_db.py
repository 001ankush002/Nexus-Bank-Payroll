"""
Customer-Controlled Undo Window
--------------------------------
Real bank mein paisa move hone ke baad final ho jaata hai - reversal ke liye bank
chahiye, din lagte hain, aur kai baar fail ho jaata hai. Yahan har transaction
(deposit, withdraw, transfer, EMI payment) ek chhoti grace window (default 2 minutes,
config me badal sakte ho) me rehta hai, jisme sirf ek click se undo ho sakta hai -
kisi approval ki zarurat nahi.
"""
import json
from decimal import Decimal

import mysql.connector

import config as cfg

WINDOW_SECONDS = int(getattr(cfg, "UNDO_WINDOW_SECONDS", 120))


def get_conn():
    return mysql.connector.connect(**cfg.DB_CONFIG)


def init_table():
    con = get_conn()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS undo_log (
        undo_id INT AUTO_INCREMENT PRIMARY KEY,
        kind VARCHAR(20) NOT NULL,
        account_number INT NOT NULL,
        counterparty_account INT,
        amount DECIMAL(15,2) NOT NULL,
        loan_id INT,
        loan_snapshot TEXT,
        description VARCHAR(150),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        undone TINYINT(1) DEFAULT 0)""")
    con.commit()
    con.close()


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    return str(o)  # datetime aur baaki sab ko safe text bana do


def log(kind, account, amount, counterparty=None, loan_id=None, loan_snapshot=None, description=""):
    """Ek nayi undo-able entry banata hai. Kisi bhi wajah se fail ho to caller
    ignore kar sakta hai - asal transaction is par depend nahi karta."""
    con = get_conn()
    cur = con.cursor()
    snap = json.dumps(loan_snapshot, default=_json_default) if loan_snapshot else None
    cur.execute(
        "INSERT INTO undo_log (kind, account_number, counterparty_account, amount, loan_id, "
        "loan_snapshot, description, expires_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s, DATE_ADD(NOW(), INTERVAL %s SECOND))",
        (kind, account, counterparty, amount, loan_id, snap, description, WINDOW_SECONDS))
    con.commit()
    undo_id = cur.lastrowid
    con.close()
    return undo_id


def get_active():
    """Abhi undo ho sakne wale entries - already-undone aur expired apne aap chhoot jaate hain."""
    con = get_conn()
    cur = con.cursor(dictionary=True)
    cur.execute(
        "SELECT *, TIMESTAMPDIFF(SECOND, NOW(), expires_at) AS seconds_left "
        "FROM undo_log WHERE undone=0 AND expires_at > NOW() ORDER BY undo_id DESC")
    rows = cur.fetchall()
    con.close()
    for r in rows:
        r["seconds_left"] = max(0, int(r["seconds_left"]))
    return rows


def _insert_txn(cur, account, ttype, amount):
    cur.execute(
        "INSERT INTO Transactions (account_number, transaction_type, amount, transaction_date) "
        "VALUES (%s,%s,%s,NOW())", (account, ttype, amount))


def undo(undo_id):
    """Undo window ke andar ho to original transaction ko reverse karta hai.
    Window nikal chuki ho ya paisa aage kharch ho chuka ho to ValueError uthata hai."""
    con = get_conn()
    try:
        con.start_transaction()
        cur = con.cursor(dictionary=True)
        cur.execute("SELECT *, expires_at < NOW() AS expired FROM undo_log WHERE undo_id=%s FOR UPDATE",
                    (undo_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Ye undo entry ab maujood nahi hai.")
        if row["undone"]:
            raise ValueError("Ye transaction pehle hi undo ho chuki hai.")
        if row["expired"]:
            raise ValueError("Undo window khatam ho chuki hai - ab ye transaction final hai.")

        kind = row["kind"]
        acc = row["account_number"]
        amount = Decimal(str(row["amount"]))

        if kind == "deposit":
            cur.execute("SELECT current_balance FROM Customers WHERE account_number=%s FOR UPDATE", (acc,))
            bal = Decimal(str(cur.fetchone()["current_balance"]))
            if bal < amount:
                raise ValueError("Undo nahi ho sakta: is account se paise pehle hi kharch ho chuke hain.")
            cur.execute("UPDATE Customers SET current_balance=current_balance-%s WHERE account_number=%s",
                        (amount, acc))
            _insert_txn(cur, acc, "Deposit Undo", amount)
            desc = f"Deposit of Rs.{amount} undone on account {acc}."

        elif kind == "withdraw":
            cur.execute("UPDATE Customers SET current_balance=current_balance+%s WHERE account_number=%s",
                        (amount, acc))
            _insert_txn(cur, acc, "Withdraw Undo", amount)
            desc = f"Withdrawal of Rs.{amount} undone on account {acc}."

        elif kind == "transfer":
            dst = row["counterparty_account"]
            cur.execute("SELECT current_balance FROM Customers WHERE account_number=%s FOR UPDATE", (dst,))
            dst_bal = Decimal(str(cur.fetchone()["current_balance"]))
            if dst_bal < amount:
                raise ValueError("Undo nahi ho sakta: receiver ne paise pehle hi kharch kar diye.")
            cur.execute("UPDATE Customers SET current_balance=current_balance+%s WHERE account_number=%s",
                        (amount, acc))
            cur.execute("UPDATE Customers SET current_balance=current_balance-%s WHERE account_number=%s",
                        (amount, dst))
            _insert_txn(cur, acc, "Transfer Undo In", amount)
            _insert_txn(cur, dst, "Transfer Undo Out", amount)
            desc = f"Transfer of Rs.{amount} from {acc} to {dst} undone."

        elif kind == "emi":
            snap = json.loads(row["loan_snapshot"])
            cur.execute(
                "UPDATE Loans SET outstanding_amount=%s, emis_paid=%s, total_paid=%s, "
                "status=%s, closed_on=NULL WHERE loan_id=%s",
                (snap["outstanding_amount"], snap["emis_paid"], snap["total_paid"],
                 snap["status"], row["loan_id"]))
            cur.execute("UPDATE Customers SET current_balance=current_balance+%s WHERE account_number=%s",
                        (amount, acc))
            _insert_txn(cur, acc, "Loan EMI Undo", amount)
            desc = f"EMI payment of Rs.{amount} on loan #{row['loan_id']} undone."

        else:
            raise ValueError("Unknown undo type.")

        cur.execute("UPDATE undo_log SET undone=1 WHERE undo_id=%s", (undo_id,))
        con.commit()
        return desc
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()