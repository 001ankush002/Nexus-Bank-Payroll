# 🏦 Nexus Bank & Payroll - Pro Max

A modern dark-themed **desktop banking and payroll application** built with Python, CustomTkinter and MySQL. Manage customers, transactions, fund transfers, payroll and loans from a single dashboard.

## ✨ Features

| Module | What it does |
|---|---|
| 📊 **Dashboard** | Live stats (customers, liquidity, today's transactions, active loans), quick shortcuts and recent activity |
| 👥 **Customers** | Searchable customer directory with CSV export and one-click statement |
| ➕ **New Account** | Register a customer with an initial deposit; auto-generated account number |
| 💸 **Deposit / Withdraw** | Balance validation, prevents over-withdrawal |
| 🔁 **Fund Transfer** | Account-to-account transfer in one safe DB transaction, reference number, daily limit |
| 📄 **Mini Statement** | Full transaction history with running balance |
| 👔 **Add Employee** | Employee master with optional salary account |
| 💼 **Process Payroll** | Salary preview (PF, HRA, DA, tax), credit to bank account, PDF salary slip |
| 🧾 **Bulk Payroll** | Attendance-based leave deduction + tax slabs, pay all employees in one click (no double payment) |
| 🏦 **Loan System** | Apply, approve/reject, EMI, part-payment and foreclosure |

## 🛠️ Tech Stack

- Python 3.10+
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (GUI)
- MySQL + `mysql-connector-python`
- `fpdf` (PDF salary slips)

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up MySQL
Start MySQL and create the database and base tables:
```bash
mysql -u root -p < schema.sql
```

### 4. Configure environment variables
Copy `.env.example` to `.env` and fill in your values:
```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```
Then edit `.env` (MySQL password, admin login, etc.). **Never commit `.env`.**

### 5. Run
```bash
python main.py
```
Sign in with the admin credentials from your `.env` (default: `admin` / `admin123` - change it!).

## 📁 Project Structure

```
├── main.py           # App window, sidebar, all main screens
├── features_ui.py    # Fund Transfer & Bulk Payroll screens
├── features_db.py    # Fund Transfer & Bulk Payroll database logic
├── db.py             # Core database layer
├── config.py         # Settings (reads from .env)
├── loan_calc.py      # EMI / loan calculations
├── payslip.py        # Salary calculation & PDF slip
├── utils.py          # Helpers (validation, formatting)
├── schema.sql        # Base MySQL schema
├── requirements.txt
└── .env.example
```

## 🔐 Security Notes

- Secrets live in `.env`, which is git-ignored.
- This is a learning/demo project: the admin login is a single configured account. For production use, add hashed passwords, roles and an audit log.

## 🗺️ Roadmap

- Roles (Admin / Teller / Manager) and audit log
- EMI due dates and overdue tracking
- Real-time fraud detection and loan credit scoring (ML)
- Charts and cash-flow forecasting

## 📄 License

MIT - see [LICENSE](LICENSE).