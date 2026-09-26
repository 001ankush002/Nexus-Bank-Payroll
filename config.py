"""
Nexus Bank & Payroll - Pro Max : configuration

Secrets (MySQL password, admin login) code me nahi, `.env` file me rakhe jaate hain.
`.env.example` ko copy karke `.env` banao aur apni values bharo.
"""
import os
from pathlib import Path


def _load_env_file():
    """Project folder ki `.env` file padhta hai (extra library ki zarurat nahi)."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# ---------------- MySQL ----------------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "bank_payroll_db"),
    "port": _int("DB_PORT", 3306),
}

# ---------------- Admin login ----------------
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# ---------------- Business rules ----------------
MIN_OPENING_BALANCE = _int("MIN_OPENING_BALANCE", 500)       # new account ke liye minimum deposit (Rs.)
MIN_LOAN_AMOUNT = _int("MIN_LOAN_AMOUNT", 1000)              # minimum loan amount (Rs.)
DAILY_TRANSFER_LIMIT = _int("DAILY_TRANSFER_LIMIT", 200000)  # ek account se ek din me max transfer (Rs.)

# ---------------- Theme colors ----------------
BG_DARK = "#121212"
BG_SIDEBAR = "#1e1e1e"
BG_CARD = "#2b2b2b"
BORDER = "#3a3a3a"
BRAND_BLUE = "#1a4c8a"
MUTED = "gray"

BLUE = "#1E90FF"
GREEN = "#2ED573"
ORANGE = "#FFA500"
RED = "#FF4757"