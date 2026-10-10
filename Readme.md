# 🏦 Nexus Bank & Payroll - Pro Max

A desktop Bank Accounts + Payroll management system built with Python, CustomTkinter and MySQL.
One admin dashboard to manage customer accounts, fund transfers, loans (with real EMI
schedules), payroll (with daily attendance and loss-of-pay), transaction undo, and dispute
resolution.

> Built as a B.Tech CSE (AI/ML) mini project, designed to be extended into a full major
> project - see [Roadmap](#-roadmap--major-project-extension) below.

## ✨ Features

**Accounts & Transactions**
- Admin login (hashed password, no secrets in code)
- Open new accounts, deposit / withdraw cash
- **Fund transfer** between any two accounts - atomic (all-or-nothing), deadlock-safe,
  daily transfer limit, a bank-style reference number, and a live "recent transfers" ledger
- Mini statement per account with a running balance and a narration for every entry
  (e.g. *"To A/C 1002 (Priya Nair) Ref TRF20260920..."*)
- Customer directory: search, CSV export, jump straight to a customer's statement

**Transaction Undo**
- A short grace window after a transaction (deposit, withdrawal, or transfer) where it
  can be reversed in one click, instead of being permanently final the instant it posts

**Dispute Resolution**
- Raise and track a dispute against a transaction, so a flagged entry has a clear,
  auditable trail from being reported through to resolution

**Payroll & Attendance**
- Add employees and (optionally) link them to a salary account
- **Daily attendance**: Present / Absent / Half Day / Paid Leave, with a monthly summary
  and automatic Loss-of-Pay (LOP) calculation
- Pay an individual employee, with the salary slip preview reflecting LOP automatically
- **Bulk payroll**: pay every eligible employee for a month in one click - skips anyone
  already paid or missing a linked account, and reports exactly what happened
- Auto-generated PDF salary slips (single or bulk, saved to a folder of your choice)

**Loans**
- Apply, approve or reject loan requests
- Real EMI schedule (reducing-balance interest), configurable tenure and rate
- Pay EMIs, make part-payments (shortens the loan, EMI unchanged), or foreclose the
  loan with a full closure quote (outstanding + interest + foreclosure charge)

**Dashboard**
- Live customer count, bank liquidity, today's transactions and active loans
- Recent system activity feed

## 🛠 Tech Stack

- **Language:** Python 3.10+
- **GUI:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (dark theme) + `tkinter.ttk`
- **Database:** MySQL 8+ (via `mysql-connector-python`)
- **PDF generation:** `fpdf2`
- **Security:** PBKDF2-SHA256 password hashing (standard library only, see `auth.py`)
- **Tests:** `pytest`, with `mysql.connector` / `fpdf` stubbed out so the suite needs no
  real database or PDF library to run

## 📸 Screenshots

*(Add a few screenshots here - Dashboard, Loan System, Bulk Payroll, Attendance look great
in a README and make a big difference on your profile.)*

## 🚀 Getting Started

### Prerequisites
- Python 3.10 or newer
- MySQL Server 8.0+ running locally (or reachable over the network)

### 1. Clone and set up a virtual environment
```bash
git clone https://github.com/001ankush002/Nexus-Bank-Payroll.git
cd Nexus-Bank-Payroll
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

### 2. Configure your secrets
Copy the example env file and fill in your own MySQL password:
```bash
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
```
Open `.env` and set `DB_PASSWORD` to your MySQL password. `.env` is listed in
`.gitignore`, so it is never committed.

For the admin login, either:
- leave `ADMIN_PASSWORD=admin123` for a quick local demo, **or** (recommended)
- generate a proper hash and delete the plain-text line:
  ```bash
  python tools/hash_password.py
  ```
  Paste the printed `ADMIN_PASSWORD_HASH=...` line into `.env`.

### 3. Run it
```bash
python main.py
```
The database and every table are created automatically on first run (see
`Database.ensure_schema()` in `db.py`) - you do **not** need to run `schema.sql` by hand.
It's kept in the repo purely as a readable reference of the schema, and it's safe to run
manually too (`CREATE TABLE IF NOT EXISTS`, never touches existing data).

Log in with the username/password from your `.env` file.

## 🧪 Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```
The suite (`tests/`) covers the database layer, loan/EMI math, payroll/LOP calculation,
attendance, and password hashing - all against a mocked MySQL connection, so no real
database is needed to run it.

## 📁 Project Structure
```
Nexus-Bank-Payroll/
├── main.py              # GUI - all pages (dashboard, accounts, transfer, payroll, loans...)
├── db.py                # All SQL lives here; self-healing schema (creates/upgrades tables)
├── auth.py               # Password hashing + login check (PBKDF2-SHA256)
├── config.py             # Loads settings from .env - no secrets in code
├── payslip.py             # Salary math (incl. LOP), bulk-payroll planning, PDF slip
├── loan_calc.py           # EMI, part-payment and foreclosure math
├── undo_db.py              # Database logic for reversing a recent transaction
├── undo_ui.py               # UI page for the transaction-undo feature
├── dispute_db.py             # Database logic for raising / tracking disputes
├── dispute_ui.py              # UI page for the dispute-resolution feature
├── utils.py                    # Formatting & validation helpers
├── schema.sql                   # Reference copy of the schema (optional - app self-creates it)
├── tools/
│   └── hash_password.py          # CLI: generate an ADMIN_PASSWORD_HASH for .env
├── tests/                         # pytest suite (mocked DB, no MySQL required)
├── .env.example                    # Template - copy to .env and fill in your own values
├── requirements.txt                 # Runtime dependencies
└── requirements-dev.txt              # + pytest, for running tests/
```

## 🔒 Security notes
- No password, database credential, or admin login is hardcoded anywhere in the source -
  everything comes from `.env` (see `config.py`).
- Admin passwords should be stored as a PBKDF2 hash (`ADMIN_PASSWORD_HASH`), generated
  with `tools/hash_password.py`. The plain `ADMIN_PASSWORD` fallback is for local demos only.
- If you fork or clone this repo, **create your own `.env`** - never reuse someone else's.

## 🗺 Roadmap / Major Project Extension
Planned next for the 4th-year major project version of this app:
- **Real-time fraud detection** - rule-based + an Isolation Forest model flagging unusual
  transactions (large amount vs. history, rapid-fire transfers, odd hours) into a review queue
- **Loan eligibility / credit-risk scoring** - a model suggesting Approve / Review / Reject
  with a reasoned explanation, based on account history and repayment behaviour
- **Role-based access & audit log** - Teller / Manager / Admin roles, with a full action log
- **Cash-flow forecasting** - a simple time-series forecast of next month's balance trend

## 📄 License
This project is licensed under the [MIT License](LICENSE).