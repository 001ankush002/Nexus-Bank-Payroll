"""
db.py - MySQL data-access layer.
GUI (main.py) sirf is class ke methods call karta hai; SQL yahin rehta hai.
"""
import calendar
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import mysql.connector
from mysql.connector import Error

import loan_calc
from config import DAILY_TRANSFER_LIMIT, DB_CONFIG
from utils import format_inr


class DatabaseError(Exception):
    """MySQL connection / query problem."""


class BankError(Exception):
    """Business rule problem (account not found, low balance...). Message user ko dikhaya jaata hai."""


ATTENDANCE_STATUSES = ("Present", "Absent", "Half Day", "Paid Leave")

# Purani tables me ensure_schema() inhe ALTER se add karta hai (fresh tables me DDL me hi hain).
_EXTRA_COLUMNS = [
    ("Transactions", "description", "VARCHAR(160) NULL"),          # statement narration
    ("Payroll", "lop_days", "DECIMAL(4,1) NOT NULL DEFAULT 0.0"),  # attendance se loss-of-pay days
]

# Loans me repayment ke columns. Purani Loans table me ensure_schema() inhe ALTER se add karta hai.
_LOAN_EXTRA_COLUMNS = [
    ("interest_rate", "DECIMAL(5,2) NULL"),
    ("tenure_months", "INT NULL"),
    ("emi_amount", "DECIMAL(15,2) NULL"),
    ("outstanding_amount", "DECIMAL(15,2) NULL"),
    ("emis_paid", "INT NOT NULL DEFAULT 0"),
    ("total_paid", "DECIMAL(15,2) NOT NULL DEFAULT 0.00"),
    ("disbursed_on", "DATETIME NULL"),
    ("closed_on", "DATETIME NULL"),
]

# ---------------------------------------------------------------------------
# Tables (schema.sql ka hi copy). ensure_schema() inhe check karke jo missing
# ho use khud bana deta hai, taaki schema.sql run na hui ho tab bhi app chale.
# ---------------------------------------------------------------------------
_TABLES = [
    ("Customers", """
        account_number  INT AUTO_INCREMENT PRIMARY KEY,
        customer_name   VARCHAR(100)  NOT NULL,
        contact_number  VARCHAR(15)   NOT NULL,
        email           VARCHAR(100),
        current_balance DECIMAL(15,2) NOT NULL DEFAULT 0.00""",
     None),
    ("Transactions", """
        transaction_id   INT AUTO_INCREMENT PRIMARY KEY,
        account_number   INT           NOT NULL,
        transaction_type VARCHAR(30)   NOT NULL,
        amount           DECIMAL(15,2) NOT NULL,
        transaction_date DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        description      VARCHAR(160)  NULL""",
     "FOREIGN KEY (account_number) REFERENCES Customers(account_number)"),
    ("Loans", """
        loan_id        INT AUTO_INCREMENT PRIMARY KEY,
        account_number INT           NOT NULL,
        loan_amount    DECIMAL(15,2) NOT NULL,
        status         VARCHAR(20)   NOT NULL DEFAULT 'Pending'""" +
     "".join(f",\n        {col} {definition}" for col, definition in _LOAN_EXTRA_COLUMNS),
     "FOREIGN KEY (account_number) REFERENCES Customers(account_number)"),
    ("Employees", """
        employee_id   INT AUTO_INCREMENT PRIMARY KEY,
        employee_name VARCHAR(100)  NOT NULL,
        designation   VARCHAR(60),
        basic_salary  DECIMAL(12,2) NOT NULL,
        account_number INT NULL""",
     None),
    ("Payroll", """
        payroll_id       INT AUTO_INCREMENT PRIMARY KEY,
        employee_id      INT           NOT NULL,
        pay_month        VARCHAR(30)   NOT NULL,
        bonus            DECIMAL(12,2) NOT NULL DEFAULT 0.00,
        gross_salary     DECIMAL(12,2) NOT NULL,
        total_deductions DECIMAL(12,2) NOT NULL,
        net_salary       DECIMAL(12,2) NOT NULL,
        generated_on     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        account_number   INT NULL,
        lop_days         DECIMAL(4,1)  NOT NULL DEFAULT 0.0""",
     "FOREIGN KEY (employee_id) REFERENCES Employees(employee_id)"),
    ("Transfers", """
        transfer_id  INT AUTO_INCREMENT PRIMARY KEY,
        reference_no VARCHAR(24)   NULL,
        from_account INT           NOT NULL,
        to_account   INT           NOT NULL,
        amount       DECIMAL(15,2) NOT NULL,
        remark       VARCHAR(60)   NULL,
        created_on   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP""",
     "FOREIGN KEY (from_account) REFERENCES Customers(account_number), "
     "FOREIGN KEY (to_account) REFERENCES Customers(account_number)"),
    ("Attendance", """
        attendance_id INT AUTO_INCREMENT PRIMARY KEY,
        employee_id   INT         NOT NULL,
        att_date      DATE        NOT NULL,
        status        VARCHAR(15) NOT NULL DEFAULT 'Present',
        UNIQUE KEY uq_emp_date (employee_id, att_date)""",
     "FOREIGN KEY (employee_id) REFERENCES Employees(employee_id)"),
]

_DEMO_EMPLOYEES = """
    INSERT IGNORE INTO Employees (employee_id, employee_name, designation, basic_salary) VALUES
        (101, 'Amit Verma',  'Branch Manager',     60000.00),
        (102, 'Neha Singh',  'Loan Officer',       45000.00),
        (103, 'Rohit Mehta', 'Cashier',            32000.00),
        (104, 'Priya Nair',  'Customer Relations', 28000.00)
"""


class Database:
    # ------------------------------------------------------------ internals
    def _connect(self):
        try:
            return mysql.connector.connect(**DB_CONFIG)
        except Error as exc:
            raise DatabaseError(
                "Could not connect to MySQL.\n"
                "Check that MySQL is running and the DB_* values in your .env file are correct.\n\n"
                f"{exc}"
            ) from exc

    @contextmanager
    def _session(self):
        """Ek connection + cursor. Success par commit, error par rollback."""
        conn = self._connect()
        cur = conn.cursor(dictionary=True, buffered=True)
        try:
            yield cur
            conn.commit()
        except Error as exc:
            conn.rollback()
            raise DatabaseError(str(exc)) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def _add_txn(cur, account_number, txn_type, amount, description=None):
        """Transactions table me ek entry (description = statement narration)."""
        cur.execute(
            "INSERT INTO Transactions (account_number, transaction_type, amount, transaction_date, description) "
            "VALUES (%s, %s, %s, NOW(), %s)",
            (account_number, txn_type, amount, description),
        )

    @staticmethod
    def _require_customer(cur, account_number, lock=False):
        sql = (
            "SELECT account_number, customer_name, contact_number, email, current_balance "
            "FROM Customers WHERE account_number = %s"
        )
        if lock:
            sql += " FOR UPDATE"
        cur.execute(sql, (account_number,))
        row = cur.fetchone()
        if row is None:
            raise BankError(f"Account {account_number} not found.")
        return row

    def ping(self):
        """Login screen par DB status dikhane ke liye. Fail hone par DatabaseError."""
        self._connect().close()

    # ------------------------------------------------------------ schema check
    @staticmethod
    def _text(value):
        """information_schema kabhi bytes return karta hai; usse str bana deta hai."""
        return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)

    @staticmethod
    def _table_exists(cur, name):
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND LOWER(TABLE_NAME) = %s",
            (name.lower(),),
        )
        return cur.fetchone()["n"] > 0

    def _data_type(self, cur, table, column):
        """Column ka data type ('enum', 'varchar'...) ya None."""
        cur.execute(
            "SELECT DATA_TYPE AS dt FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND LOWER(TABLE_NAME) = %s AND LOWER(COLUMN_NAME) = %s",
            (table.lower(), column.lower()),
        )
        row = cur.fetchone()
        return self._text(row["dt"]).lower() if row else None

    @staticmethod
    def _column_exists(cur, table, column):
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND LOWER(TABLE_NAME) = %s AND LOWER(COLUMN_NAME) = %s",
            (table.lower(), column.lower()),
        )
        return cur.fetchone()["n"] > 0

    @staticmethod
    def _create_table(cur, name, columns, foreign_key=None):
        """CREATE TABLE IF NOT EXISTS. Agar FOREIGN KEY type-mismatch se fail ho to bina FK ke bana deta hai."""
        if foreign_key:
            try:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns}, {foreign_key})")
                return
            except Error:
                pass
        cur.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns})")

    def ensure_schema(self):
        """App start par ek baar: missing tables (Payroll, Employees, Loans...) bana deta hai.
        Purani tables aur data ko touch nahi karta."""
        with self._session() as cur:
            employees_existed = self._table_exists(cur, "Employees")
            for name, columns, foreign_key in _TABLES:
                self._create_table(cur, name, columns, foreign_key)
            if not employees_existed:
                cur.execute(_DEMO_EMPLOYEES)

            # Purani Employees / Payroll tables me salary-account column add karo (agar missing ho)
            for table in ("Employees", "Payroll"):
                if not self._column_exists(cur, table, "account_number"):
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN account_number INT NULL")

            for table, column, definition in _EXTRA_COLUMNS:
                if not self._column_exists(cur, table, column):
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

            # 'Loan Disbursed', 'Salary Credit', 'Loan EMI'... save ho sakein, isliye ENUM ho to VARCHAR bana do
            if self._data_type(cur, "Transactions", "transaction_type") == "enum":
                cur.execute("ALTER TABLE Transactions MODIFY transaction_type VARCHAR(30) NOT NULL")

            # ---- Loans: repayment columns, status ENUM -> VARCHAR (Closed/Rejected ke liye), purane loans ----
            for column, definition in _LOAN_EXTRA_COLUMNS:
                if not self._column_exists(cur, "Loans", column):
                    cur.execute(f"ALTER TABLE Loans ADD COLUMN {column} {definition}")
            if self._data_type(cur, "Loans", "status") == "enum":
                cur.execute("ALTER TABLE Loans MODIFY status VARCHAR(20) NOT NULL DEFAULT 'Pending'")
            self._backfill_loans(cur)

    @staticmethod
    def _backfill_loans(cur):
        """Purane loans (repayment feature se pehle ke) ko default rate/tenure/EMI aur outstanding de do."""
        cur.execute(
            "SELECT loan_id, loan_amount FROM Loans "
            "WHERE interest_rate IS NULL OR tenure_months IS NULL OR emi_amount IS NULL"
        )
        for loan in cur.fetchall():
            emi = loan_calc.calculate_emi(loan["loan_amount"], loan_calc.DEFAULT_RATE, loan_calc.DEFAULT_TENURE)
            cur.execute(
                "UPDATE Loans SET interest_rate = %s, tenure_months = %s, emi_amount = %s WHERE loan_id = %s",
                (loan_calc.DEFAULT_RATE, loan_calc.DEFAULT_TENURE, emi, loan["loan_id"]),
            )
        cur.execute(
            "UPDATE Loans SET outstanding_amount = loan_amount "
            "WHERE status = 'Approved' AND outstanding_amount IS NULL"
        )

    # ------ dashboard
    def get_dashboard_stats(self):
        with self._session() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM Customers)                                   AS total_customers,
                    (SELECT COALESCE(SUM(current_balance), 0) FROM Customers)          AS liquidity,
                    (SELECT COUNT(*) FROM Transactions
                      WHERE DATE(transaction_date) = CURDATE())                        AS todays_txns,
                    (SELECT COUNT(*) FROM Loans WHERE status = 'Approved')             AS active_loans
                """
            )
            return cur.fetchone()

    def get_recent_transactions(self, limit=6):
        with self._session() as cur:
            cur.execute(
                """
                SELECT t.transaction_id, t.account_number, c.customer_name,
                       t.transaction_type, t.amount, t.transaction_date
                FROM Transactions t
                JOIN Customers c ON c.account_number = t.account_number
                ORDER BY t.transaction_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()

    # ------ accounts
    def create_account(self, name, phone, email, initial_deposit):
        """Naya customer + 'Account Opened' transaction. Account number return karta hai."""
        with self._session() as cur:
            cur.execute(
                "INSERT INTO Customers (customer_name, contact_number, email, current_balance) "
                "VALUES (%s, %s, %s, %s)",
                (name, phone, email, initial_deposit),
            )
            account_number = cur.lastrowid
            self._add_txn(cur, account_number, "Account Opened", initial_deposit, "Initial deposit")
        return account_number

    def get_customer(self, account_number):
        with self._session() as cur:
            return self._require_customer(cur, account_number)

    def get_customers(self):
        """Saare customers + opening date + transaction count (Customer Directory ke liye)."""
        with self._session() as cur:
            cur.execute(
                """
                SELECT c.account_number, c.customer_name, c.contact_number, c.email,
                       c.current_balance,
                       (SELECT MIN(t.transaction_date) FROM Transactions t
                         WHERE t.account_number = c.account_number
                           AND t.transaction_type = 'Account Opened')   AS opened_on,
                       (SELECT COUNT(*) FROM Transactions t2
                         WHERE t2.account_number = c.account_number)    AS txn_count
                FROM Customers c
                ORDER BY c.account_number
                """
            )
            return cur.fetchall()

    # ------ deposit / withdraw
    def deposit(self, account_number, amount):
        return self._post_transaction(account_number, amount, "Deposit", +1)

    def withdraw(self, account_number, amount):
        return self._post_transaction(account_number, amount, "Withdraw", -1)

    def _post_transaction(self, account_number, amount, txn_type, sign):
        with self._session() as cur:
            customer = self._require_customer(cur, account_number, lock=True)
            new_balance = customer["current_balance"] + sign * amount
            if new_balance < 0:
                raise BankError(
                    "Insufficient balance!\n"
                    f"Available balance: {format_inr(customer['current_balance'])}"
                )
            cur.execute(
                "UPDATE Customers SET current_balance = %s WHERE account_number = %s",
                (new_balance, account_number),
            )
            self._add_txn(cur, account_number, txn_type, amount,
                          "Cash deposit" if sign > 0 else "Cash withdrawal")
        return {"customer_name": customer["customer_name"], "balance": new_balance}

    # ------ fund transfer
    def transfer(self, from_account, to_account, amount, remark=None):
        """Account A -> Account B, ek hi database transaction me (dono ya koi nahi).
        Rules: alag accounts, sufficient balance, daily limit. Dono statements me narration + reference."""
        if from_account == to_account:
            raise BankError("Sender and receiver accounts must be different.")
        remark = (remark or "").strip()[:60] or None

        with self._session() as cur:
            # accounts hamesha ascending order me lock -> do simultaneous transfers me deadlock nahi
            locked = {acc: self._require_customer(cur, acc, lock=True)
                      for acc in sorted((from_account, to_account))}
            sender, receiver = locked[from_account], locked[to_account]

            if sender["current_balance"] < amount:
                raise BankError(
                    "Insufficient balance!\n"
                    f"Available balance: {format_inr(sender['current_balance'])}")

            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) AS used FROM Transfers "
                "WHERE from_account = %s AND DATE(created_on) = CURDATE()",
                (from_account,),
            )
            used = cur.fetchone()["used"]
            limit = Decimal(DAILY_TRANSFER_LIMIT)
            if used + amount > limit:
                raise BankError(
                    "Daily transfer limit exceeded.\n"
                    f"Limit: {format_inr(limit)}   Used today: {format_inr(used)}   "
                    f"Remaining: {format_inr(max(limit - used, Decimal('0')))}")

            cur.execute(
                "UPDATE Customers SET current_balance = current_balance - %s WHERE account_number = %s",
                (amount, from_account))
            cur.execute(
                "UPDATE Customers SET current_balance = current_balance + %s WHERE account_number = %s",
                (amount, to_account))

            cur.execute(
                "INSERT INTO Transfers (from_account, to_account, amount, remark, created_on) "
                "VALUES (%s, %s, %s, %s, NOW())",
                (from_account, to_account, amount, remark))
            transfer_id = cur.lastrowid
            reference = f"TRF{datetime.now():%Y%m%d}{transfer_id:05d}"
            cur.execute("UPDATE Transfers SET reference_no = %s WHERE transfer_id = %s",
                        (reference, transfer_id))

            note = f" - {remark}" if remark else ""
            self._add_txn(cur, from_account, "Transfer Out", amount,
                          f"To A/C {to_account} ({receiver['customer_name'][:28]}) Ref {reference}{note}")
            self._add_txn(cur, to_account, "Transfer In", amount,
                          f"From A/C {from_account} ({sender['customer_name'][:28]}) Ref {reference}{note}")

        return {
            "reference": reference,
            "sender_name": sender["customer_name"],
            "receiver_name": receiver["customer_name"],
            "sender_balance": sender["current_balance"] - amount,
            "receiver_balance": receiver["current_balance"] + amount,
        }

    def get_recent_transfers(self, limit=15):
        with self._session() as cur:
            cur.execute(
                """
                SELECT t.reference_no, t.from_account, cf.customer_name AS from_name,
                       t.to_account, ct.customer_name AS to_name, t.amount, t.remark, t.created_on
                FROM Transfers t
                JOIN Customers cf ON cf.account_number = t.from_account
                JOIN Customers ct ON ct.account_number = t.to_account
                ORDER BY t.transfer_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()


    # ------ statement
    def get_statement(self, account_number):
        with self._session() as cur:
            customer = self._require_customer(cur, account_number)
            cur.execute(
                "SELECT transaction_id, transaction_type, amount, transaction_date, description "
                "FROM Transactions WHERE account_number = %s "
                "ORDER BY transaction_date ASC, transaction_id ASC",
                (account_number,),
            )
            rows = cur.fetchall()
        return customer, rows

    # ------ payroll
    _EMPLOYEE_COLUMNS = "employee_id, employee_name, designation, basic_salary, account_number"

    def create_employee(self, name, designation, basic_salary, account_number=None):
        """Naya employee add karta hai. employee_id return karta hai.
        account_number (optional) = salary jis customer account me credit hogi."""
        with self._session() as cur:
            if account_number is not None:
                self._require_customer(cur, account_number)   # account exist karta hai?
            cur.execute(
                "INSERT INTO Employees (employee_name, designation, basic_salary, account_number) "
                "VALUES (%s, %s, %s, %s)",
                (name, designation, basic_salary, account_number),
            )
            employee_id = cur.lastrowid
        return employee_id

    def get_employees(self):
        with self._session() as cur:
            cur.execute(f"SELECT {self._EMPLOYEE_COLUMNS} FROM Employees ORDER BY employee_id")
            return cur.fetchall()

    def get_employee(self, employee_id):
        with self._session() as cur:
            cur.execute(
                f"SELECT {self._EMPLOYEE_COLUMNS} FROM Employees WHERE employee_id = %s",
                (employee_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise BankError(f"Employee ID {employee_id} not found.")
        return row

    def get_paid_employee_ids(self, month):
        """Us month ki salary jin employees ko pay ho chuki hai unke ids (set)."""
        with self._session() as cur:
            cur.execute(
                "SELECT DISTINCT employee_id FROM Payroll "
                "WHERE LOWER(pay_month) = LOWER(%s) AND account_number IS NOT NULL",
                (month,),
            )
            return {row["employee_id"] for row in cur.fetchall()}

    def get_salary_payment(self, employee_id, month):
        """Us month ka payment record (ya None agar abhi pay nahi hua)."""
        with self._session() as cur:
            cur.execute(
                "SELECT payroll_id, account_number, bonus, net_salary, lop_days, generated_on FROM Payroll "
                "WHERE employee_id = %s AND LOWER(pay_month) = LOWER(%s) AND account_number IS NOT NULL "
                "ORDER BY payroll_id DESC LIMIT 1",
                (employee_id, month),
            )
            return cur.fetchone()

    # ------ attendance
    def get_attendance(self, att_date):
        """Ek din ki attendance: {employee_id: status}."""
        with self._session() as cur:
            cur.execute("SELECT employee_id, status FROM Attendance WHERE att_date = %s", (att_date,))
            return {row["employee_id"]: row["status"] for row in cur.fetchall()}

    def save_attendance(self, att_date, statuses):
        """statuses = {employee_id: 'Present' | 'Absent' | 'Half Day' | 'Paid Leave'} (upsert)."""
        bad = {s for s in statuses.values() if s not in ATTENDANCE_STATUSES}
        if bad:
            raise BankError(f"Unknown attendance status: {', '.join(sorted(bad))}")
        with self._session() as cur:
            for employee_id, status in statuses.items():
                cur.execute(
                    "INSERT INTO Attendance (employee_id, att_date, status) VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE status = VALUES(status)",
                    (employee_id, att_date, status),
                )
        return len(statuses)

    def get_attendance_summary(self, year, month):
        """Har employee ka month ka hisaab (unmarked din = Present maane jaate hain)."""
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        with self._session() as cur:
            cur.execute(
                """
                SELECT e.employee_id, e.employee_name,
                       COALESCE(SUM(a.status = 'Present'), 0)    AS present_days,
                       COALESCE(SUM(a.status = 'Half Day'), 0)   AS half_days,
                       COALESCE(SUM(a.status = 'Absent'), 0)     AS absent_days,
                       COALESCE(SUM(a.status = 'Paid Leave'), 0) AS leave_days
                FROM Employees e
                LEFT JOIN Attendance a
                       ON a.employee_id = e.employee_id AND a.att_date BETWEEN %s AND %s
                GROUP BY e.employee_id, e.employee_name
                ORDER BY e.employee_id
                """,
                (first, last),
            )
            rows = cur.fetchall()
        for row in rows:
            row["lop_days"] = Decimal(row["absent_days"]) + Decimal(row["half_days"]) / 2
        return rows

    def get_lop_days(self, employee_id, year, month):
        """Loss-of-pay days of one employee: Absent = 1, Half Day = 0.5."""
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        with self._session() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(CASE status WHEN 'Absent' THEN 1 WHEN 'Half Day' THEN 0.5 "
                "ELSE 0 END), 0) AS lop FROM Attendance "
                "WHERE employee_id = %s AND att_date BETWEEN %s AND %s",
                (employee_id, first, last),
            )
            return Decimal(cur.fetchone()["lop"])

    def pay_salary(self, employee_id, month, bonus, salary, account_number):
        """Net salary employee ke bank account me credit karta hai.
        Ek hi transaction me: balance update + 'Salary Credit' entry (mini statement me dikhegi)
        + Payroll record. Same employee ko same month ki salary dobara nahi jaati."""
        net = salary["net"]
        if net <= 0:
            raise BankError("Net salary must be greater than zero.")

        with self._session() as cur:
            cur.execute(
                "SELECT employee_id, employee_name, account_number FROM Employees "
                "WHERE employee_id = %s FOR UPDATE",
                (employee_id,),
            )
            employee = cur.fetchone()
            if employee is None:
                raise BankError(f"Employee ID {employee_id} not found.")

            cur.execute(
                "SELECT generated_on FROM Payroll WHERE employee_id = %s "
                "AND LOWER(pay_month) = LOWER(%s) AND account_number IS NOT NULL LIMIT 1",
                (employee_id, month),
            )
            already = cur.fetchone()
            if already:
                raise BankError(
                    f"Salary for {month} is already paid to {employee['employee_name']} "
                    f"(on {already['generated_on'].strftime('%d-%b-%Y')})."
                )

            customer = self._require_customer(cur, account_number, lock=True)
            cur.execute(
                "UPDATE Customers SET current_balance = current_balance + %s WHERE account_number = %s",
                (net, account_number),
            )
            self._add_txn(cur, account_number, "Salary Credit", net, f"Salary {month}")
            cur.execute(
                "INSERT INTO Payroll (employee_id, pay_month, bonus, gross_salary, total_deductions, "
                "net_salary, account_number, lop_days, generated_on) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                (employee_id, month, bonus, salary["gross"], salary["deductions"], net, account_number,
                 salary.get("lop_days", 0)),
            )
            payroll_id = cur.lastrowid
            if employee["account_number"] is None:  # pehli baar: account employee se link kar do
                cur.execute(
                    "UPDATE Employees SET account_number = %s WHERE employee_id = %s",
                    (account_number, employee_id),
                )
        return {
            "payroll_id": payroll_id,
            "employee_name": employee["employee_name"],
            "customer_name": customer["customer_name"],
            "balance": customer["current_balance"] + net,
        }

    # ---- loans
    _LOAN_COLUMNS = (
        "loan_id, account_number, loan_amount, status, interest_rate, tenure_months, "
        "emi_amount, outstanding_amount, emis_paid, total_paid, disbursed_on, closed_on"
    )

    def apply_loan(self, account_number, amount, tenure_months, annual_rate):
        """Loan application -> status 'Pending' (rate, tenure aur EMI ke saath)."""
        emi = loan_calc.calculate_emi(amount, annual_rate, tenure_months)
        with self._session() as cur:
            self._require_customer(cur, account_number)
            cur.execute(
                "INSERT INTO Loans (account_number, loan_amount, status, interest_rate, tenure_months, "
                "emi_amount, outstanding_amount, emis_paid, total_paid) "
                "VALUES (%s, %s, 'Pending', %s, %s, %s, NULL, 0, 0)",
                (account_number, amount, annual_rate, tenure_months, emi),
            )
            loan_id = cur.lastrowid
        return {"loan_id": loan_id, "emi": emi}

    def get_loans(self):
        with self._session() as cur:
            cur.execute(
                """
                SELECT l.loan_id, l.account_number, c.customer_name,
                       c.current_balance AS account_balance,
                       l.loan_amount, l.status, l.interest_rate, l.tenure_months, l.emi_amount,
                       l.outstanding_amount, l.emis_paid, l.total_paid, l.disbursed_on, l.closed_on
                FROM Loans l
                JOIN Customers c ON c.account_number = l.account_number
                ORDER BY l.loan_id DESC
                """
            )
            return cur.fetchall()

    # ---- helpers ----
    def _lock_loan(self, cur, loan_id):
        cur.execute(f"SELECT {self._LOAN_COLUMNS} FROM Loans WHERE loan_id = %s FOR UPDATE", (loan_id,))
        loan = cur.fetchone()
        if loan is None:
            raise BankError(f"Loan #{loan_id} not found.")
        return loan

    def _lock_active_loan(self, cur, loan_id):
        loan = self._lock_loan(cur, loan_id)
        if loan["status"] != "Approved":
            raise BankError(
                f"Loan #{loan_id} is {loan['status']}. Repayment is only possible on an active loan.")
        needed = ("interest_rate", "tenure_months", "emi_amount", "outstanding_amount")
        if any(loan[k] is None for k in needed):
            raise BankError("This loan has no repayment schedule yet. Restart the app once so it can be upgraded.")
        return loan

    def _debit_customer(self, cur, account_number, amount, txn_type, description=None):
        """Customer ke account se paisa kaatta hai (balance check ke saath) + transaction entry."""
        customer = self._require_customer(cur, account_number, lock=True)
        if customer["current_balance"] < amount:
            raise BankError(
                f"Insufficient balance in account {account_number}.\n"
                f"Required: {format_inr(amount)}     Available: {format_inr(customer['current_balance'])}\n"
                "Please deposit funds first."
            )
        new_balance = customer["current_balance"] - amount
        cur.execute(
            "UPDATE Customers SET current_balance = %s WHERE account_number = %s",
            (new_balance, account_number),
        )
        self._add_txn(cur, account_number, txn_type, amount, description)
        return new_balance

    @staticmethod
    def _update_after_payment(cur, loan_id, outstanding, paid, emis_increment, closed):
        sql = ("UPDATE Loans SET outstanding_amount = %s, emis_paid = emis_paid + %s, "
               "total_paid = total_paid + %s")
        if closed:
            sql += ", status = 'Closed', closed_on = NOW()"
        cur.execute(sql + " WHERE loan_id = %s", (outstanding, emis_increment, paid, loan_id))

    # ---- approval ----
    def approve_loan(self, loan_id):
        """Pending -> Approved: amount customer ke account me credit + outstanding set."""
        with self._session() as cur:
            loan = self._lock_loan(cur, loan_id)
            if loan["status"] != "Pending":
                raise BankError(f"Loan #{loan_id} is already {loan['status']}.")

            self._require_customer(cur, loan["account_number"], lock=True)
            cur.execute(
                "UPDATE Customers SET current_balance = current_balance + %s WHERE account_number = %s",
                (loan["loan_amount"], loan["account_number"]),
            )
            self._add_txn(cur, loan["account_number"], "Loan Disbursed", loan["loan_amount"],
                          f"Loan #{loan_id} disbursed")
            cur.execute(
                "UPDATE Loans SET status = 'Approved', outstanding_amount = loan_amount, "
                "emis_paid = 0, disbursed_on = NOW() WHERE loan_id = %s",
                (loan_id,),
            )
        return loan

    def reject_loan(self, loan_id):
        with self._session() as cur:
            loan = self._lock_loan(cur, loan_id)
            if loan["status"] != "Pending":
                raise BankError(f"Only a Pending loan can be rejected (this one is {loan['status']}).")
            cur.execute("UPDATE Loans SET status = 'Rejected' WHERE loan_id = %s", (loan_id,))
        return loan

    # ---- repayment ----
    def repay_emi(self, loan_id):
        """Ek EMI (interest + principal) customer ke account se katti hai."""
        with self._session() as cur:
            loan = self._lock_active_loan(cur, loan_id)
            inst = loan_calc.next_installment(
                loan["outstanding_amount"], loan["interest_rate"], loan["emi_amount"],
                loan["emis_paid"], loan["tenure_months"])
            balance = self._debit_customer(
                cur, loan["account_number"], inst["payment"], "Loan EMI",
                f"Loan #{loan_id} EMI {loan['emis_paid'] + 1}/{loan['tenure_months']}")
            outstanding = max(loan["outstanding_amount"] - inst["principal"], Decimal("0.00"))
            closed = outstanding <= 0
            self._update_after_payment(cur, loan_id, outstanding, inst["payment"], 1, closed)
        return {**inst, "outstanding": outstanding, "balance": balance, "closed": closed}

    def part_payment(self, loan_id, amount):
        """Extra payment: poori rakam principal me jaati hai, EMI same rehti hai (loan jaldi khatam)."""
        with self._session() as cur:
            loan = self._lock_active_loan(cur, loan_id)
            if amount >= loan["outstanding_amount"]:
                raise BankError(
                    "Part-payment must be less than the outstanding principal "
                    f"({format_inr(loan['outstanding_amount'])}).\nUse 'Close Loan' to pay off the whole loan.")
            balance = self._debit_customer(
                cur, loan["account_number"], amount, "Loan Part-Payment", f"Loan #{loan_id} part-payment")
            outstanding = loan["outstanding_amount"] - amount
            self._update_after_payment(cur, loan_id, outstanding, amount, 0, False)
        return {"payment": amount, "outstanding": outstanding, "balance": balance, "closed": False}

    def close_loan(self, loan_id, expected_total=None):
        """Foreclosure: outstanding + interest + charge ek saath bhar ke loan Closed."""
        with self._session() as cur:
            loan = self._lock_active_loan(cur, loan_id)
            quote = loan_calc.closure_quote(loan["outstanding_amount"], loan["interest_rate"])
            if expected_total is not None and quote["total"] != expected_total:
                raise BankError("The closure amount has changed since you opened this loan.\n"
                                "Please select the loan again and retry.")
            balance = self._debit_customer(
                cur, loan["account_number"], quote["total"], "Loan Closure", f"Loan #{loan_id} closure")
            self._update_after_payment(cur, loan_id, Decimal("0.00"), quote["total"], 0, True)
        return {**quote, "balance": balance, "closed": True}