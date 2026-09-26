"""
Nexus Bank & Payroll - Pro Max
Run:  python main.py

Files:  config.py  utils.py  db.py  payslip.py  features_db.py  features_ui.py  main.py  (+ schema.sql for MySQL)
"""
import csv
import re
import tkinter as tk
import webbrowser
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import config as cfg
import loan_calc
from db import BankError, Database, DatabaseError
from features_ui import TransferFrame, BulkPayrollFrame
from payslip import calculate_salary, generate_salary_slip
from utils import (format_inr, is_valid_email, is_valid_phone,
                   parse_amount, parse_id, shade)

# ==========================================
# UI THEME SETUP
# ==========================================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# transaction type -> Treeview row color tag
TXN_TAGS = {
    "Deposit": "credit",
    "Withdraw": "debit",
    "Account Opened": "opened",
    "Loan Disbursed": "loan",
    "Salary Credit": "credit",
    "Loan EMI": "debit",
    "Loan Part-Payment": "debit",
    "Loan Closure": "debit",
    "Transfer In": "credit",
    "Transfer Out": "debit",
}

# in types se account balance kam hota hai (statement me '-' aur running balance ghatta hai)
DEBIT_TYPES = {"Withdraw", "Loan EMI", "Loan Part-Payment", "Loan Closure", "Transfer Out"}

# login screen ke left panel ka gradient (top -> bottom)
LOGIN_GRADIENT = ("#0a2342", "#1f5fae")


def font(size=13, bold=False):
    return ctk.CTkFont(size=size, weight="bold" if bold else "normal")


def blend(c1, c2, t):
    """Do hex colors ke beech ka color (t = 0..1)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def recent_months(count=12):
    """['September 2026', 'August 2026', ...] - pay month dropdown ke liye."""
    year, month = datetime.now().year, datetime.now().month
    months = []
    for _ in range(count):
        months.append(datetime(year, month, 1).strftime("%B %Y"))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return months


# ==========================================
# MAIN APPLICATION GUI CLASS
# ==========================================
class BankPayrollApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Nexus Bank & Payroll - Pro Max")
        self.geometry("1100x700")
        self.minsize(1000, 650)
        self.configure(fg_color=cfg.BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.db = Database()
        self.screen = None          # current top-level screen (login OR app layout)
        self.main_frame = None      # right-side content area
        self.menu_buttons = {}
        self._clock_job = None
        self._schema_ready = False  # missing tables ek baar check/create ho jaayein

        self.setup_table_style()
        self.show_login_screen()

    # ==================================================
    # SMALL HELPERS
    # ==================================================
    def setup_table_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Nexus.Treeview", background=cfg.BG_CARD, foreground="#eaeaea",
                        fieldbackground=cfg.BG_CARD, borderwidth=0, rowheight=30,
                        bordercolor=cfg.BG_CARD, lightcolor=cfg.BG_CARD, darkcolor=cfg.BG_CARD,
                        font=("Segoe UI", 10))
        style.configure("Nexus.Treeview.Heading", background="#1f538d", foreground="white",
                        relief="flat", padding=6, font=("Segoe UI", 10, "bold"),
                        bordercolor="#1f538d", lightcolor="#1f538d", darkcolor="#1f538d")
        style.map("Nexus.Treeview", background=[("selected", "#3a7ebf")],
                  foreground=[("selected", "white")])
        style.map("Nexus.Treeview.Heading", background=[("active", "#2a6cb5")])

    def _on_close(self):
        self._cancel_clock()
        self.destroy()

    def _new_screen(self):
        """Purani screen hata kar ek fresh full-window frame deta hai."""
        self._cancel_clock()
        if self.screen is not None:
            self.screen.destroy()
        self.screen = ctk.CTkFrame(self, fg_color=cfg.BG_DARK, corner_radius=0)
        self.screen.pack(fill="both", expand=True)
        return self.screen

    def _start_clock(self, label):
        def tick():
            try:
                label.configure(text=datetime.now().strftime("%d %B %Y   |   %I:%M:%S %p"))
            except Exception:
                return  # label destroy ho chuka hai
            self._clock_job = self.after(1000, tick)
        tick()

    def _cancel_clock(self):
        if self._clock_job is not None:
            try:
                self.after_cancel(self._clock_job)
            except Exception:
                pass
            self._clock_job = None

    def _guard(self, action):
        """action() chalata hai; validation/DB error par message box dikhata hai.
        Return: (True, result) ya (False, None)."""
        try:
            return True, action()
        except ValueError as exc:
            messagebox.showwarning("Please check your input", str(exc))
        except BankError as exc:
            messagebox.showwarning("Not allowed", str(exc))
        except DatabaseError as exc:
            messagebox.showerror("Database Error", str(exc))
        return False, None

    def _page_header(self, title, subtitle=""):
        ctk.CTkLabel(self.main_frame, text=title, font=font(26, True)).pack(
            anchor="w", pady=(0, 2 if subtitle else 16))
        if subtitle:
            ctk.CTkLabel(self.main_frame, text=subtitle, font=font(13), text_color="gray").pack(
                anchor="w", pady=(0, 16))

    def _field(self, parent, label, placeholder="", width=440, **kwargs):
        ctk.CTkLabel(parent, text=label, font=font(13), text_color="#c8c8c8").pack(
            anchor="w", padx=40, pady=(16, 4))
        entry = ctk.CTkEntry(parent, width=width, height=38, placeholder_text=placeholder, **kwargs)
        entry.pack(anchor="w", padx=40)
        return entry

    def _button(self, parent, text, command, color, width=140, height=38, text_color=None):
        kwargs = {"text_color": text_color} if text_color else {}
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=height,
                             fg_color=color, hover_color=shade(color, 0.8),
                             font=font(13, True), **kwargs)

    def _make_tree(self, parent, columns, height=None):
        """columns = [(id, heading, width, anchor), ...]  ->  (wrapper_frame, treeview)"""
        wrapper = ctk.CTkFrame(parent, fg_color=cfg.BG_CARD, corner_radius=15)
        extra = {"height": height} if height else {}
        tree = ttk.Treeview(wrapper, columns=[c[0] for c in columns], show="headings",
                            style="Nexus.Treeview", selectmode="browse", **extra)
        has_text_col = any(c[3] == "w" for c in columns)
        for cid, heading, width, anchor in columns:
            tree.heading(cid, text=heading)
            # jagah bachne par sirf text (left-aligned) columns badhte hain, numbers/IDs fixed rehte hain
            tree.column(cid, width=width, anchor=anchor,
                        stretch=(anchor == "w") if has_text_col else True)
        scroll = ctk.CTkScrollbar(wrapper, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)
        scroll.pack(side="right", fill="y", padx=(0, 6), pady=12)

        tree.tag_configure("credit", foreground=cfg.GREEN)
        tree.tag_configure("debit", foreground=cfg.RED)
        tree.tag_configure("opened", foreground=cfg.BLUE)
        tree.tag_configure("loan", foreground=cfg.ORANGE)
        tree.tag_configure("pending", foreground=cfg.ORANGE)
        tree.tag_configure("approved", foreground=cfg.GREEN)
        tree.tag_configure("paid", foreground=cfg.GREEN)
        tree.tag_configure("unpaid", foreground=cfg.ORANGE)
        tree.tag_configure("closed", foreground="#8a8a8a")
        tree.tag_configure("rejected", foreground=cfg.RED)
        tree.tag_configure("other", foreground="#eaeaea")
        return wrapper, tree

    @staticmethod
    def _fmt_dt(value):
        return value.strftime("%d-%b-%Y %I:%M %p") if value else "-"

    # ==================================================
    # 1. LOGIN  (redesigned: gradient brand panel + clean card)
    # ==================================================
    def show_login_screen(self):
        screen = self._new_screen()
        self.main_frame = None
        self.menu_buttons = {}
        screen.grid_rowconfigure(0, weight=1)
        screen.grid_columnconfigure(0, weight=11, uniform="login")   # left  ~55%
        screen.grid_columnconfigure(1, weight=9, uniform="login")    # right ~45%

        # ---- left: gradient brand panel (canvas, window ke saath resize hota hai) ----
        art = tk.Canvas(screen, highlightthickness=0, bd=0, bg=LOGIN_GRADIENT[0])
        art.grid(row=0, column=0, sticky="nsew")
        art.bind("<Configure>", lambda e: self._draw_login_art(art, e.width, e.height))

        # ---- right: login card ----
        right = ctk.CTkFrame(screen, corner_radius=0, fg_color=cfg.BG_SIDEBAR)
        right.grid(row=0, column=1, sticky="nsew")

        card = ctk.CTkFrame(right, corner_radius=22, fg_color=cfg.BG_CARD,
                            border_width=1, border_color=cfg.BORDER)
        card.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(card, text="ADMIN PORTAL", font=font(11, True), text_color=cfg.BLUE).pack(
            anchor="w", padx=36, pady=(36, 0))
        ctk.CTkLabel(card, text="Welcome back 👋", font=font(28, True)).pack(
            anchor="w", padx=36, pady=(4, 2))
        ctk.CTkLabel(card, text="Sign in to manage accounts, payroll and loans.", font=font(13),
                     text_color="gray", wraplength=320, justify="left").pack(
            anchor="w", padx=36, pady=(0, 22))

        ctk.CTkLabel(card, text="Username", font=font(12, True), text_color="#c8c8c8").pack(
            anchor="w", padx=36)
        self.entry_user = ctk.CTkEntry(card, width=328, height=46, corner_radius=10, border_width=1,
                                       placeholder_text="👤  Enter your username")
        self.entry_user.pack(padx=36, pady=(4, 14))

        ctk.CTkLabel(card, text="Password", font=font(12, True), text_color="#c8c8c8").pack(
            anchor="w", padx=36)
        self.entry_pass = ctk.CTkEntry(card, width=328, height=46, corner_radius=10, border_width=1,
                                       show="•", placeholder_text="🔒  Enter your password")
        self.entry_pass.pack(padx=36, pady=(4, 8))

        self.show_pw = ctk.CTkCheckBox(card, text="Show password", font=font(12),
                                       checkbox_width=18, checkbox_height=18,
                                       command=self._toggle_password)
        self.show_pw.pack(anchor="w", padx=36, pady=(0, 4))

        self.login_error = ctk.CTkLabel(card, text="", height=22, font=font(12), text_color=cfg.RED)
        self.login_error.pack(anchor="w", padx=36)

        ctk.CTkButton(card, text="Sign In  →", width=328, height=48, corner_radius=10,
                      font=font(15, True), command=self.verify_login).pack(padx=36, pady=(4, 14))

        self.db_status = ctk.CTkLabel(card, text="● Checking database…", font=font(11),
                                      text_color="gray")
        self.db_status.pack(pady=(0, 26))

        for entry in (self.entry_user, self.entry_pass):
            entry.bind("<Return>", lambda _e: self.verify_login())
            entry.bind("<Key>", lambda _e: self.login_error.configure(text=""))

        self.after(150, self.entry_user.focus)
        self.after(300, self._check_db_status)

    def _draw_login_art(self, c, w, h):
        """Left panel: vertical gradient + decorative rings + brand text + feature pills."""
        if w < 50 or h < 50:
            return
        c.delete("all")
        top, bottom = LOGIN_GRADIENT

        steps = max(2, min(h, 90))
        band = h / steps
        for i in range(steps):
            c.create_rectangle(0, int(i * band), w, int((i + 1) * band) + 1,
                               outline="", fill=blend(top, bottom, i / (steps - 1)))

        ring = "#2f68ac"
        c.create_oval(-w * 0.40, h * 0.60, w * 0.50, h * 1.50, outline=ring, width=2)
        c.create_oval(w * 0.55, -h * 0.30, w * 1.30, h * 0.35, outline=ring, width=2)
        c.create_oval(w * 0.72, h * 0.68, w * 0.72 + w * 0.20, h * 0.68 + w * 0.20,
                      outline=ring, width=2)

        cx = w / 2
        c.create_text(cx, h * 0.20, text="🏦", font=("Segoe UI Emoji", 58), fill="white")
        c.create_text(cx, h * 0.34, text="NEXUS BANK", font=("Segoe UI", 34, "bold"), fill="white")
        c.create_text(cx, h * 0.405, text="Pro Max Edition  •  Bank & Payroll Suite",
                      font=("Segoe UI", 12), fill="#b9d4f5")

        features = [
            ("💳", "Accounts, deposits & withdrawals"),
            ("💼", "Payroll, salary transfer & PDF slips"),
            ("🏦", "Loan approval & disbursement"),
        ]
        pill_w = min(350, w - 80)
        x0 = (w - pill_w) / 2
        y = h * 0.53
        for icon, text in features:
            fill = blend(blend(top, bottom, y / h), "#ffffff", 0.10)
            self._round_rect(c, x0, y, x0 + pill_w, y + 46, 14, fill=fill, outline=ring)
            c.create_text(x0 + 26, y + 23, text=icon, font=("Segoe UI Emoji", 15), fill="white")
            c.create_text(x0 + 54, y + 23, text=text, anchor="w", font=("Segoe UI", 11),
                          fill="#e6f0ff")
            y += 60

        c.create_text(cx, h - 26, text="© 2026 Nexus Bank  •  Secure Admin Access",
                      font=("Segoe UI", 9), fill="#8fb4e3")

    @staticmethod
    def _round_rect(c, x0, y0, x1, y1, r, **kwargs):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return c.create_polygon(pts, smooth=True, **kwargs)

    def _toggle_password(self):
        self.entry_pass.configure(show="" if self.show_pw.get() else "•")

    def _check_db_status(self):
        try:
            self.db.ping()
            text, color = "● Database connected", cfg.GREEN
        except DatabaseError:
            text, color = "● Database offline - check MySQL & config.py", cfg.RED
        try:
            self.db_status.configure(text=text, text_color=color)
        except Exception:
            pass  # user pehle hi login kar chuka hai

    def verify_login(self):
        user, pwd = self.entry_user.get().strip(), self.entry_pass.get()
        if user == cfg.ADMIN_USERNAME and pwd == cfg.ADMIN_PASSWORD:
            self.build_main_dashboard()
            return
        self.login_error.configure(text="❌  Invalid username or password.")
        self.entry_pass.delete(0, "end")
        self.entry_pass.focus()

    # ==================================================
    # 2. MAIN LAYOUT & SIDEBAR
    # ==================================================
    def build_main_dashboard(self):
        screen = self._new_screen()
        self.create_sidebar(screen)
        self.main_frame = ctk.CTkFrame(screen, corner_radius=0, fg_color="transparent")
        self.main_frame.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        self.show_dashboard()

    def create_sidebar(self, parent):
        sidebar = ctk.CTkFrame(parent, width=220, corner_radius=0, fg_color=cfg.BG_SIDEBAR)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="🏦 NEXUS BANK", font=font(20, True),
                     text_color=cfg.BLUE).pack(padx=20, pady=(24, 18))

        menus = [
            ("dashboard", "📊 Dashboard", self.show_dashboard),
            ("customers", "👥 Customers", self.show_customers),
            ("add_account", "➕ New Account", self.show_add_account),
            ("add_employee", "👔 Add Employee", self.show_add_employee),
            ("transactions", "💸 Deposit / Withdraw", self.show_transactions),
            ("transfer", "🔁 Fund Transfer", self.show_transfer),
            ("statement", "📄 Mini Statement", self.show_statement),
            ("payroll", "💼 Process Payroll", self.show_payroll),
            ("bulk_payroll", "🧾 Bulk Payroll", self.show_bulk_payroll),
            ("loans", "🏦 Loan System", self.show_loans),
        ]
        self.menu_buttons = {}
        for key, text, command in menus:
            btn = ctk.CTkButton(sidebar, text=text, command=command, anchor="w", height=36,
                                fg_color="transparent", text_color="gray90",
                                hover_color=cfg.BG_CARD, font=font(14))
            btn.pack(fill="x", padx=10, pady=2)
            self.menu_buttons[key] = btn

        ctk.CTkButton(sidebar, text="Logout", command=self.logout, height=38,
                      fg_color=cfg.RED, hover_color="#d63031",
                      font=font(13, True)).pack(side="bottom", fill="x", padx=20, pady=20)

    def logout(self):
        if messagebox.askyesno("Logout", "Do you want to log out?"):
            self.show_login_screen()

    def clear_main_frame(self, active=None):
        """Content area saaf karta hai aur sidebar me active menu highlight karta hai."""
        self._cancel_clock()
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        for key, btn in self.menu_buttons.items():
            btn.configure(fg_color="#1f538d" if key == active else "transparent")

    # ==================================================
    # 3. DASHBOARD
    # ==================================================
    def show_dashboard(self):
        self.clear_main_frame("dashboard")
        root = self.main_frame

        # --- Welcome banner + live date/time ---
        banner = ctk.CTkFrame(root, fg_color=cfg.BG_CARD, corner_radius=15, height=70)
        banner.pack(fill="x", pady=(0, 12))
        banner.pack_propagate(False)
        ctk.CTkLabel(banner, text="👋 Welcome back, Administrator",
                     font=font(20, True)).pack(side="left", padx=25)
        clock = ctk.CTkLabel(banner, text="", font=font(14), text_color="gray")
        clock.pack(side="right", padx=25)
        self._start_clock(clock)

        # --- Live data ---
        stats = {"total_customers": 0, "liquidity": 0, "todays_txns": 0, "active_loans": 0}
        recent = []
        db_error = None
        try:
            if not self._schema_ready:
                self.db.ensure_schema()   # missing tables (Payroll etc.) khud ban jaayengi
                self._schema_ready = True
            stats = self.db.get_dashboard_stats()
            recent = self.db.get_recent_transactions(6)
        except DatabaseError as exc:
            db_error = str(exc)

        if db_error:
            err = ctk.CTkFrame(root, fg_color="#3a1f24", corner_radius=12)
            err.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(err, text="⚠ Database problem: " + db_error.splitlines()[0],
                         text_color=cfg.RED, font=font(13)).pack(side="left", padx=16, pady=10)
            self._button(err, "Retry", self.show_dashboard, cfg.RED, width=80, height=28).pack(
                side="right", padx=12)

        # --- 4 stat cards ---
        cards = ctk.CTkFrame(root, fg_color="transparent")
        cards.pack(fill="x", pady=(0, 12))
        cards.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stat")
        items = [
            ("👥 Total Customers", f"{stats['total_customers']:,}", cfg.BLUE),
            ("💰 Bank Liquidity", format_inr(stats["liquidity"], decimals=0), cfg.GREEN),
            ("⚡ Today's Txns", str(stats["todays_txns"]), cfg.ORANGE),
            ("📉 Active Loans", str(stats["active_loans"]), cfg.RED),
        ]
        for col, (title, value, color) in enumerate(items):
            card = ctk.CTkFrame(cards, fg_color=cfg.BG_CARD, corner_radius=14)
            card.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
            ctk.CTkFrame(card, fg_color=color, height=4, corner_radius=2).pack(
                fill="x", padx=14, pady=(12, 0))
            ctk.CTkLabel(card, text=title, font=font(12), text_color="gray").pack(pady=(10, 2))
            ctk.CTkLabel(card, text=value, font=font(22, True), text_color=color).pack(pady=(0, 14))

        # --- Quick shortcuts ---
        bar = ctk.CTkFrame(root, fg_color=cfg.BG_CARD, height=52, corner_radius=12)
        bar.pack(fill="x", pady=(0, 12))
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="Quick Shortcuts:", font=font(12, True)).pack(side="left", padx=15)
        self._button(bar, "+ New Account", self.show_add_account, "#1f538d", 120, 30).pack(side="left", padx=8)
        self._button(bar, "💸 Deposit/Withdraw", self.show_transactions, "#26af5f", 150, 30).pack(side="left", padx=8)
        self._button(bar, "🔁 Transfer", self.show_transfer, "#1f538d", 100, 30).pack(side="left", padx=8)
        self._button(bar, "💼 Payroll", self.show_payroll, "#cc8400", 100, 30, "black").pack(side="left", padx=8)

        # --- Recent activity ---
        ctk.CTkLabel(root, text="Recent System Activity", font=font(15, True)).pack(
            anchor="w", padx=5, pady=(0, 4))
        wrapper, tree = self._make_tree(root, [
            ("id", "Txn ID", 70, "center"),
            ("acc", "Account No", 100, "center"),
            ("name", "Customer", 170, "w"),
            ("type", "Activity Type", 140, "center"),
            ("amount", "Amount (₹)", 130, "e"),
            ("date", "Date & Time", 160, "center"),
        ])
        wrapper.pack(fill="both", expand=True)

        if recent:
            for r in recent:
                tree.insert("", "end", tags=(TXN_TAGS.get(r["transaction_type"], "other"),),
                            values=(r["transaction_id"], r["account_number"], r["customer_name"],
                                    r["transaction_type"], format_inr(r["amount"]),
                                    self._fmt_dt(r["transaction_date"])))
        else:
            tree.insert("", "end", values=("-", "-", "No recent transactions found", "-", "-", "-"))

    # ==================================================
    # 4. NEW ACCOUNT
    # ==================================================
    def show_add_account(self):
        self.clear_main_frame("add_account")
        self._page_header("Open New Account", "Register a customer and credit the initial deposit")

        card = ctk.CTkFrame(self.main_frame, corner_radius=15, fg_color=cfg.BG_CARD)
        card.pack(pady=(0, 10))

        self.f_name = self._field(card, "Full Name", "e.g. Rahul Sharma")
        self.f_phone = self._field(card, "Mobile Number", "10-digit mobile number")
        self.f_email = self._field(card, "Email Address", "e.g. rahul@example.com")
        self.f_deposit = self._field(
            card, "Initial Deposit (₹)", f"Minimum {format_inr(cfg.MIN_OPENING_BALANCE, decimals=0)}")
        self._button(card, "Create Account", self._create_account, cfg.BLUE, 440, 42).pack(
            padx=40, pady=(26, 32))

    def _create_account(self):
        def work():
            name = self.f_name.get().strip()
            phone = self.f_phone.get().strip()
            email = self.f_email.get().strip()
            if len(name) < 3:
                raise ValueError("Please enter the customer's full name.")
            if not is_valid_phone(phone):
                raise ValueError("Enter a valid 10-digit mobile number.")
            if not is_valid_email(email):
                raise ValueError("Enter a valid email address.")
            deposit = parse_amount(self.f_deposit.get(), "Initial deposit")
            if deposit < cfg.MIN_OPENING_BALANCE:
                raise ValueError(
                    f"Minimum opening deposit is {format_inr(cfg.MIN_OPENING_BALANCE)}.")
            return self.db.create_account(name, phone, email, deposit), deposit

        ok, res = self._guard(work)
        if not ok:
            return
        account_number, deposit = res
        messagebox.showinfo(
            "Account Created",
            f"Account opened successfully!\n\nAccount Number: {account_number}\n"
            f"Opening Balance: {format_inr(deposit)}")
        self.show_add_account()  # form reset

    # ==================================================
    # 4b. CUSTOMER DIRECTORY  (sab customers ki details)
    # ==================================================
    def show_customers(self):
        self.clear_main_frame("customers")
        self._page_header("Customer Directory", "Every customer with account number, contact details and balance")

        bar = ctk.CTkFrame(self.main_frame, fg_color=cfg.BG_CARD, corner_radius=15)
        bar.pack(fill="x", pady=(0, 8))
        self.c_search = ctk.CTkEntry(bar, width=300, height=38,
                                     placeholder_text="🔍  Search name, A/C no, mobile, email")
        self.c_search.pack(side="left", padx=(16, 10), pady=14)
        self.c_search.bind("<KeyRelease>", lambda _e: self._render_customers())
        self._button(bar, "📄 Statement", self._customer_statement, cfg.BLUE, 120, 38).pack(
            side="left", padx=(0, 8))
        self._button(bar, "⬇ Export CSV", self._export_customers, cfg.GREEN, 125, 38, "black").pack(
            side="left", padx=(0, 8))
        self._button(bar, "⟳", self._load_customers, cfg.BRAND_BLUE, 44, 38).pack(side="left")

        self.c_summary = ctk.CTkLabel(self.main_frame, text="", font=font(12), text_color="gray")
        self.c_summary.pack(anchor="w", padx=6, pady=(0, 6))

        wrapper, self.c_tree = self._make_tree(self.main_frame, [
            ("acc", "A/C No", 75, "center"),
            ("name", "Customer Name", 150, "w"),
            ("phone", "Mobile", 100, "center"),
            ("email", "Email", 175, "w"),
            ("balance", "Balance (₹)", 115, "e"),
            ("opened", "Opened On", 100, "center"),
            ("txns", "Txns", 50, "center"),
        ])
        wrapper.pack(fill="both", expand=True)
        self.c_tree.bind("<Double-1>", lambda _e: self._customer_statement())

        self._customers = []
        self._customers_view = []
        self._load_customers()

    def _load_customers(self):
        ok, rows = self._guard(self.db.get_customers)
        self._customers = rows if ok else []
        self._render_customers()

    def _render_customers(self):
        query = self.c_search.get().strip().lower()
        rows = [
            c for c in self._customers
            if not query or query in " ".join(
                str(c[k] or "") for k in ("account_number", "customer_name", "contact_number", "email")
            ).lower()
        ]
        self._customers_view = rows

        self.c_tree.delete(*self.c_tree.get_children())
        for c in rows:
            self.c_tree.insert("", "end", iid=str(c["account_number"]), values=(
                c["account_number"], c["customer_name"], c["contact_number"], c["email"] or "-",
                format_inr(c["current_balance"], symbol=False),
                c["opened_on"].strftime("%d-%b-%Y") if c["opened_on"] else "-",
                c["txn_count"]))

        total = sum((c["current_balance"] for c in rows), Decimal("0"))
        self.c_summary.configure(
            text=f"Showing {len(rows)} of {len(self._customers)} customers   •   "
                 f"Total balance: {format_inr(total)}")

    def _customer_statement(self):
        selected = self.c_tree.selection()
        if not selected:
            messagebox.showinfo("Select a customer", "Click a customer row first.")
            return
        self.show_statement()
        self.s_account.insert(0, selected[0])
        self._load_statement()

    def _export_customers(self):
        rows = self._customers_view
        if not rows:
            messagebox.showinfo("Nothing to export", "There are no customers to export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export customers", defaultextension=".csv", initialfile="customers.csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel me sahi khulta hai
                writer = csv.writer(f)
                writer.writerow(["Account No", "Customer Name", "Mobile", "Email",
                                 "Balance", "Opened On", "Transactions"])
                for c in rows:
                    writer.writerow([
                        c["account_number"], c["customer_name"], c["contact_number"], c["email"] or "",
                        f"{c['current_balance']:.2f}",
                        c["opened_on"].strftime("%Y-%m-%d") if c["opened_on"] else "",
                        c["txn_count"]])
        except OSError as exc:
            messagebox.showerror("Export failed", f"Could not save the file.\n\n{exc}")
            return
        messagebox.showinfo("Exported", f"{len(rows)} customers saved to:\n{path}")

    # ==================================================
    # 4c. ADD EMPLOYEE
    # ==================================================
    def show_add_employee(self):
        self.clear_main_frame("add_employee")
        self._page_header("Add New Employee",
                          "Register an employee here, then pay the salary from Process Payroll")

        body = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ---- left: form ----
        form = ctk.CTkFrame(body, corner_radius=15, fg_color=cfg.BG_CARD)
        form.grid(row=0, column=0, sticky="n", padx=(0, 14))
        self.e_name = self._field(form, "Full Name", "e.g. Ankush Sharma", width=260)
        self.e_role = self._field(form, "Designation", "e.g. Software Developer", width=260)
        self.e_salary = self._field(form, "Basic Salary (₹ / month)", "e.g. 50000", width=260)
        self.e_account = self._field(form, "Salary Account No. (optional)",
                                     "Customer account number", width=260)
        self._button(form, "➕ Add Employee", self._create_employee, cfg.BLUE, 260, 44).pack(
            anchor="w", padx=40, pady=(24, 30))

        # ---- right: current employees ----
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(right, text="👥 Current Employees", font=font(14, True)).pack(
            anchor="w", pady=(0, 6))
        wrapper, tree = self._make_tree(right, [
            ("id", "ID", 42, "center"),
            ("name", "Name", 110, "w"),
            ("role", "Designation", 115, "w"),
            ("basic", "Basic (₹)", 90, "e"),
            ("acc", "A/C No", 65, "center"),
        ], height=8)
        wrapper.pack(fill="both", expand=True)
        self.e_tree = tree

        ok, employees = self._guard(self.db.get_employees)
        for e in (employees if ok else []):
            tree.insert("", "end", iid=str(e["employee_id"]), values=(
                e["employee_id"], e["employee_name"], e["designation"] or "-",
                format_inr(e["basic_salary"], symbol=False), e["account_number"] or "-"))

    def _create_employee(self):
        def work():
            name = self.e_name.get().strip()
            role = self.e_role.get().strip()
            if len(name) < 3:
                raise ValueError("Please enter the employee's full name.")
            if len(name) > 100:
                raise ValueError("Name is too long (max 100 characters).")
            if len(role) < 2:
                raise ValueError("Please enter the designation.")
            if len(role) > 60:
                raise ValueError("Designation is too long (max 60 characters).")
            salary = parse_amount(self.e_salary.get(), "Basic salary")
            account_text = self.e_account.get().strip()
            account = parse_id(account_text, "salary account number") if account_text else None
            return self.db.create_employee(name, role, salary, account), name, salary

        ok, res = self._guard(work)
        if not ok:
            return
        employee_id, name, salary = res
        messagebox.showinfo(
            "Employee Added",
            f"Employee added successfully!\n\nEmployee ID: {employee_id}\nName: {name}\n"
            f"Basic Salary: {format_inr(salary)}")
        self.show_add_employee()  # form reset + table refresh

    # ==================================================
    # 5. DEPOSIT / WITHDRAW
    # ==================================================
    def show_transactions(self):
        self.clear_main_frame("transactions")
        self._page_header("Deposit & Withdraw Funds", "Search an account, then post the transaction")

        card = ctk.CTkFrame(self.main_frame, corner_radius=15, fg_color=cfg.BG_CARD)
        card.pack(pady=(0, 10))

        ctk.CTkLabel(card, text="Target Account Number", font=font(13), text_color="#c8c8c8").pack(
            anchor="w", padx=40, pady=(26, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=40)
        self.t_account = ctk.CTkEntry(row, width=320, height=38, placeholder_text="e.g. 1001")
        self.t_account.pack(side="left")
        self.t_account.bind("<Return>", lambda _e: self._txn_search())
        self._button(row, "🔍 Search", self._txn_search, cfg.BRAND_BLUE, 110, 38).pack(
            side="left", padx=(10, 0))

        info = ctk.CTkFrame(card, fg_color=cfg.BG_SIDEBAR, corner_radius=12)
        info.pack(fill="x", padx=40, pady=(16, 0))
        self.t_name = ctk.CTkLabel(info, text="No account selected", font=font(15, True))
        self.t_name.pack(anchor="w", padx=16, pady=(12, 0))
        self.t_bal = ctk.CTkLabel(info, text="Balance: -", font=font(13), text_color="gray")
        self.t_bal.pack(anchor="w", padx=16, pady=(2, 12))

        self.t_amount = self._field(card, "Amount (₹)", "e.g. 5000")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(anchor="w", padx=40, pady=(26, 32))
        self._button(btns, "Deposit Money", lambda: self._do_txn("Deposit"), cfg.GREEN,
                     210, 42, "black").pack(side="left", padx=(0, 20))
        self._button(btns, "Withdraw Money", lambda: self._do_txn("Withdraw"), cfg.RED,
                     210, 42).pack(side="left")

    def _show_account_info(self, name, balance):
        self.t_name.configure(text=name)
        self.t_bal.configure(text=f"Balance: {format_inr(balance)}", text_color=cfg.GREEN)

    def _txn_search(self):
        ok, customer = self._guard(
            lambda: self.db.get_customer(parse_id(self.t_account.get(), "account number")))
        if ok:
            self._show_account_info(
                f"{customer['customer_name']}  (A/C {customer['account_number']})",
                customer["current_balance"])

    def _do_txn(self, kind):
        def work():
            acc = parse_id(self.t_account.get(), "account number")
            amount = parse_amount(self.t_amount.get())
            result = self.db.deposit(acc, amount) if kind == "Deposit" else self.db.withdraw(acc, amount)
            return acc, amount, result

        ok, res = self._guard(work)
        if not ok:
            return
        acc, amount, result = res
        self._show_account_info(f"{result['customer_name']}  (A/C {acc})", result["balance"])
        self.t_amount.delete(0, "end")
        messagebox.showinfo(
            "Success",
            f"{kind} of {format_inr(amount)} successful!\nNew balance: {format_inr(result['balance'])}")

    # ==================================================
    # 5b. FUND TRANSFER  &  BULK PAYROLL  (features_ui.py se)
    # ==================================================
    def show_transfer(self):
        self.clear_main_frame("transfer")
        try:
            TransferFrame(self.main_frame).pack(fill="both", expand=True)
        except Exception as exc:
            messagebox.showerror("Fund Transfer", f"Could not open this page.\n\n{exc}")

    def show_bulk_payroll(self):
        self.clear_main_frame("bulk_payroll")
        try:
            BulkPayrollFrame(self.main_frame).pack(fill="both", expand=True)
        except Exception as exc:
            messagebox.showerror("Bulk Payroll", f"Could not open this page.\n\n{exc}")

    # ==================================================
    # 6. MINI STATEMENT
    # ==================================================
    def show_statement(self):
        self.clear_main_frame("statement")
        self._page_header("Account Mini Statement", "Complete transaction history with running balance")

        top = ctk.CTkFrame(self.main_frame, fg_color=cfg.BG_CARD, corner_radius=15)
        top.pack(fill="x", pady=(0, 14))
        self.s_account = ctk.CTkEntry(top, width=250, height=38, placeholder_text="Enter Account Number")
        self.s_account.pack(side="left", padx=(20, 12), pady=16)
        self.s_account.bind("<Return>", lambda _e: self._load_statement())
        self._button(top, "Fetch Statement", self._load_statement, cfg.BLUE, 150, 38).pack(side="left")
        self.s_summary = ctk.CTkLabel(top, text="", font=font(14), text_color="#d0d0d0")
        self.s_summary.pack(side="right", padx=20)

        wrapper, self.s_tree = self._make_tree(self.main_frame, [
            ("id", "Txn ID", 80, "center"),
            ("date", "Date & Time", 190, "center"),
            ("type", "Type", 150, "center"),
            ("amount", "Amount (₹)", 150, "e"),
            ("balance", "Balance (₹)", 150, "e"),
        ])
        wrapper.pack(fill="both", expand=True)

    def _load_statement(self):
        ok, res = self._guard(
            lambda: self.db.get_statement(parse_id(self.s_account.get(), "account number")))
        if not ok:
            return
        customer, rows = res

        running = Decimal("0")
        lines = []
        for r in rows:  # oldest -> newest, running balance nikalne ke liye
            if r["transaction_type"] in DEBIT_TYPES:
                running -= r["amount"]
                sign = "-"
            else:
                running += r["amount"]
                sign = "+"
            lines.append((r["transaction_id"], self._fmt_dt(r["transaction_date"]),
                          r["transaction_type"], f"{sign} {format_inr(r['amount'])}",
                          format_inr(running), TXN_TAGS.get(r["transaction_type"], "other")))

        self.s_tree.delete(*self.s_tree.get_children())
        for line in reversed(lines):  # newest first
            self.s_tree.insert("", "end", values=line[:5], tags=(line[5],))

        self.s_summary.configure(
            text=f"{customer['customer_name']}   •   Balance: {format_inr(customer['current_balance'])}"
                 f"   •   {len(rows)} txns")

    # ==================================================
    # 7. PAYROLL  (preview / PDF slip / PAY salary into bank account)
    # ==================================================
    def show_payroll(self):
        self.clear_main_frame("payroll")
        self._page_header("Disburse Payroll & Generate Slip",
                          "Pay the salary into the employee's bank account, then create the PDF slip")

        body = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ---- left: form ----
        form = ctk.CTkFrame(body, corner_radius=15, fg_color=cfg.BG_CARD)
        form.grid(row=0, column=0, sticky="n", padx=(0, 14))
        self.p_emp = self._field(form, "Employee ID", "e.g. 101", width=260)
        self.p_account = self._field(form, "Salary Account No.", "Customer account to credit", width=260)

        ctk.CTkLabel(form, text="Pay Month", font=font(13), text_color="#c8c8c8").pack(
            anchor="w", padx=40, pady=(16, 4))
        self.p_month = ctk.CTkOptionMenu(form, values=recent_months(), width=260, height=38,
                                         command=lambda _v: self._load_employees())
        self.p_month.pack(anchor="w", padx=40)

        self.p_bonus = self._field(form, "Bonus (₹)", "0", width=260)

        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(anchor="w", padx=40, pady=(22, 0))
        self._button(row, "👁 Preview", self._preview_slip, cfg.BRAND_BLUE, 120, 40).pack(side="left")
        self._button(row, "📄 PDF Slip", self._generate_slip, cfg.ORANGE, 130, 40, "black").pack(
            side="left", padx=(10, 0))
        self._button(form, "💸 Pay Salary", self._pay_salary, cfg.GREEN, 260, 46, "black").pack(
            anchor="w", padx=40, pady=(12, 30))

        # ---- right: employee list + salary preview ----
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(right, text="👥 Employees  (click a row to select)", font=font(14, True)).pack(
            anchor="w", pady=(0, 6))
        wrapper, self.p_tree = self._make_tree(right, [
            ("id", "ID", 40, "center"),
            ("name", "Name", 105, "w"),
            ("role", "Designation", 95, "w"),
            ("basic", "Basic (₹)", 82, "e"),
            ("acc", "A/C No", 58, "center"),
            ("status", "Status", 62, "center"),
        ], height=6)
        wrapper.pack(fill="both", expand=True)
        self.p_tree.bind("<<TreeviewSelect>>", self._pick_employee)

        card = ctk.CTkFrame(right, corner_radius=15, fg_color=cfg.BG_CARD)
        card.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(card, text="🧾 Salary Preview", font=font(13, True)).pack(
            anchor="w", padx=16, pady=(10, 0))
        self.p_preview = ctk.CTkLabel(card, text="Select an employee and click Preview.",
                                      justify="left", anchor="w", font=("Consolas", 11),
                                      text_color="#d0d0d0")
        self.p_preview.pack(anchor="w", padx=16, pady=(4, 12))

        self._load_employees()

    def _load_employees(self):
        """Employee table reload karta hai; Status column selected month ke hisaab se (Paid/Pending)."""
        month = self.p_month.get()
        ok, res = self._guard(
            lambda: (self.db.get_employees(), self.db.get_paid_employee_ids(month)))
        self.p_tree.delete(*self.p_tree.get_children())
        if not ok:
            return
        employees, paid_ids = res
        for e in employees:
            paid = e["employee_id"] in paid_ids
            self.p_tree.insert(
                "", "end", iid=str(e["employee_id"]), tags=("paid" if paid else "unpaid",),
                values=(e["employee_id"], e["employee_name"], e["designation"] or "-",
                        format_inr(e["basic_salary"], symbol=False),
                        e["account_number"] or "-", "Paid ✓" if paid else "Pending"))

    def _pick_employee(self, _event=None):
        selected = self.p_tree.selection()
        if not selected:
            return
        iid = selected[0]
        self.p_emp.delete(0, "end")
        self.p_emp.insert(0, iid)
        account = self.p_tree.set(iid, "acc")
        self.p_account.delete(0, "end")
        if account != "-":
            self.p_account.insert(0, account)

    def _payroll_inputs(self):
        emp_id = parse_id(self.p_emp.get(), "Employee ID")
        bonus = parse_amount(self.p_bonus.get() or "0", "Bonus", allow_zero=True)
        month = self.p_month.get()
        employee = self.db.get_employee(emp_id)
        salary = calculate_salary(employee["basic_salary"], bonus)
        return employee, month, bonus, salary

    def _preview_slip(self):
        ok, res = self._guard(self._payroll_inputs)
        if not ok:
            return
        employee, month, _bonus, s = res

        def m(value):
            return format_inr(value, symbol=False)

        def row(e_label, e_val, d_label="", d_val=""):
            return f"{e_label:<10}{e_val:>12}   {d_label:<10}{d_val:>11}"

        rule = "-" * 46
        self.p_preview.configure(text="\n".join([
            f"{employee['employee_name']} (ID {employee['employee_id']})  -  {month}",
            rule,
            row("EARNINGS", "(₹)", "DEDUCTIONS", "(₹)"),
            row("Basic", m(s["basic"]), "PF", m(s["pf"])),
            row("HRA", m(s["hra"]), "Prof. Tax", m(s["prof_tax"])),
            row("DA", m(s["da"])),
            row("Bonus", m(s["bonus"])),
            row("Gross", m(s["gross"]), "Total", m(s["deductions"])),
            rule,
            row("NET SALARY", m(s["net"])),
        ]))

    def _pay_salary(self):
        """Net salary employee ke bank account me credit karta hai (mini statement me 'Salary Credit')."""
        def prepare():
            employee, month, bonus, salary = self._payroll_inputs()
            account_text = self.p_account.get().strip()
            if not account_text and employee["account_number"]:
                account_text = str(employee["account_number"])   # employee ka linked account
            account = parse_id(account_text, "salary account number")
            customer = self.db.get_customer(account)
            return employee, month, bonus, salary, account, customer

        ok, res = self._guard(prepare)
        if not ok:
            return
        employee, month, bonus, salary, account, customer = res

        if not messagebox.askyesno(
                "Confirm Salary Payment",
                f"Pay {format_inr(salary['net'])} ({month})\n"
                f"to {employee['employee_name']} (ID {employee['employee_id']})\n\n"
                f"Credit to account {account} - {customer['customer_name']}?"):
            return

        ok, result = self._guard(
            lambda: self.db.pay_salary(employee["employee_id"], month, bonus, salary, account))
        if not ok:
            return

        self.p_account.delete(0, "end")
        self.p_account.insert(0, str(account))
        self._preview_slip()
        self._load_employees()
        if messagebox.askyesno(
                "Salary Paid ✓",
                f"{format_inr(salary['net'])} credited to account {account} "
                f"({result['customer_name']}).\nNew balance: {format_inr(result['balance'])}\n\n"
                "It now appears in the Mini Statement.\n\nSave the PDF salary slip now?"):
            self._save_slip(employee, month, salary)

    def _generate_slip(self):
        ok, res = self._guard(self._payroll_inputs)
        if not ok:
            return
        employee, month, _bonus, salary = res
        self._save_slip(employee, month, salary)

    def _save_slip(self, employee, month, salary):
        safe_month = re.sub(r"[^\w\-]+", "_", month)
        path = filedialog.asksaveasfilename(
            title="Save salary slip", defaultextension=".pdf",
            initialfile=f"SalarySlip_{employee['employee_id']}_{safe_month}.pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not path:
            return

        ok, payment = self._guard(
            lambda: self.db.get_salary_payment(employee["employee_id"], month))
        if not ok:
            return
        if payment:  # slip wahi numbers dikhaye jo asal me pay hue the
            salary = calculate_salary(employee["basic_salary"], payment["bonus"])

        try:
            generate_salary_slip(path, employee, month, salary, payment)
        except Exception as exc:  # fpdf / file permission problems
            messagebox.showerror("PDF Error", f"Could not create the salary slip.\n\n{exc}")
            return

        if messagebox.askyesno("Salary Slip Saved", f"Saved:\n{path}\n\nOpen the PDF now?"):
            webbrowser.open(Path(path).resolve().as_uri())

    # ==================================================
    # 8. LOANS  (apply -> approve/reject -> EMI / part-payment -> closure)
    # ==================================================
    LOAN_TAB_APPLY = "📝 Applications"
    LOAN_TAB_REPAY = "💳 Repay & Close"

    def show_loans(self, tab=None):
        self.clear_main_frame("loans")
        self._page_header("Loan System",
                          "Apply, approve, pay EMIs, part-pay and close loans - like a real bank")
        self._loans = []
        self._sel_loan_id = None

        self.loan_tabs = ctk.CTkSegmentedButton(
            self.main_frame, values=[self.LOAN_TAB_APPLY, self.LOAN_TAB_REPAY],
            command=self._switch_loan_tab, height=36, font=font(13, True))
        self.loan_tabs.pack(anchor="w", pady=(0, 12))
        self.loan_body = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.loan_body.pack(fill="both", expand=True)

        tab = tab or self.LOAN_TAB_APPLY
        self.loan_tabs.set(tab)
        self._switch_loan_tab(tab)

    def _switch_loan_tab(self, tab):
        for widget in self.loan_body.winfo_children():
            widget.destroy()
        if tab == self.LOAN_TAB_REPAY:
            self._build_loan_repay()
        else:
            self._build_loan_apply()

    def _fetch_loans(self):
        ok, loans = self._guard(self.db.get_loans)
        self._loans = loans if ok else []

    # ---------------------------------------------- tab 1: applications
    def _build_loan_apply(self):
        body = self.loan_body
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ---- left: application form with live EMI preview ----
        form = ctk.CTkFrame(body, corner_radius=15, fg_color=cfg.BG_CARD)
        form.grid(row=0, column=0, sticky="n", padx=(0, 14))
        ctk.CTkLabel(form, text="New Loan Application", font=font(16, True)).pack(
            anchor="w", padx=40, pady=(20, 0))
        self.l_account = self._field(form, "Account Number", "e.g. 10001", width=260)
        self.l_amount = self._field(form, "Loan Amount (₹)", "e.g. 100000", width=260)

        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(anchor="w", padx=40, pady=(16, 0))
        ctk.CTkLabel(row, text="Tenure", font=font(13), text_color="#c8c8c8").grid(
            row=0, column=0, sticky="w")
        ctk.CTkLabel(row, text="Interest (% p.a.)", font=font(13), text_color="#c8c8c8").grid(
            row=0, column=1, sticky="w", padx=(10, 0))
        self.l_tenure = ctk.CTkOptionMenu(
            row, values=[f"{m} months" for m in loan_calc.TENURES], width=125, height=38,
            command=lambda _v: self._update_emi_preview())
        self.l_tenure.grid(row=1, column=0, pady=(4, 0))
        self.l_tenure.set(f"{loan_calc.DEFAULT_TENURE} months")
        self.l_rate = ctk.CTkEntry(row, width=125, height=38)
        self.l_rate.grid(row=1, column=1, padx=(10, 0), pady=(4, 0))
        self.l_rate.insert(0, str(loan_calc.DEFAULT_RATE))

        self.l_preview = ctk.CTkLabel(form, text="", justify="left", anchor="w",
                                      font=("Consolas", 11), text_color="#d0d0d0")
        self.l_preview.pack(anchor="w", padx=40, pady=(14, 0))
        self._button(form, "Submit Application", self._apply_loan, cfg.BLUE, 260, 42).pack(
            anchor="w", padx=40, pady=(14, 26))
        for entry in (self.l_amount, self.l_rate):
            entry.bind("<KeyRelease>", lambda _e: self._update_emi_preview())
        self._update_emi_preview()

        # ---- right: all loan requests ----
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        head = ctk.CTkFrame(right, fg_color="transparent")
        head.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(head, text="Loan Requests", font=font(14, True)).pack(side="left")
        self._button(head, "⟳", self._reload_loans, cfg.BRAND_BLUE, 44, 32).pack(side="right")
        self._button(head, "✖ Reject", self._reject_loan, cfg.RED, 90, 32).pack(side="right", padx=8)
        self._button(head, "✅ Approve", self._approve_loan, cfg.GREEN, 105, 32, "black").pack(side="right")

        wrapper, self.l_tree = self._make_tree(right, [
            ("id", "Loan ID", 55, "center"),
            ("acc", "A/C No", 65, "center"),
            ("name", "Customer", 100, "w"),
            ("amount", "Amount (₹)", 95, "e"),
            ("tenure", "Tenure", 60, "center"),
            ("status", "Status", 70, "center"),
        ], height=8)
        wrapper.pack(fill="both", expand=True)
        self._reload_loans()

    def _tenure_months(self):
        return int(self.l_tenure.get().split()[0])

    def _update_emi_preview(self):
        def line(label, value):
            return f"{label:<17}{value:>14}"
        try:
            amount = parse_amount(self.l_amount.get(), "Loan amount")
            rate = loan_calc.parse_rate(self.l_rate.get())
            months = self._tenure_months()
            emi = loan_calc.calculate_emi(amount, rate, months)
            total = emi * months
            text = "\n".join([
                line("Monthly EMI (₹)", format_inr(emi, symbol=False)),
                line("Total interest (₹)", format_inr(total - amount, symbol=False)),
                line("Total payable (₹)", format_inr(total, symbol=False)),
            ])
        except ValueError:
            text = "Enter amount & rate to see the EMI."
        self.l_preview.configure(text=text)

    def _reload_loans(self):
        self._fetch_loans()
        self.l_tree.delete(*self.l_tree.get_children())
        for loan in self._loans:
            self.l_tree.insert(
                "", "end", iid=str(loan["loan_id"]), tags=(str(loan["status"]).lower(),),
                values=(loan["loan_id"], loan["account_number"], loan["customer_name"],
                        format_inr(loan["loan_amount"], symbol=False),
                        f"{loan['tenure_months']} m" if loan["tenure_months"] else "-",
                        loan["status"]))

    def _apply_loan(self):
        def work():
            acc = parse_id(self.l_account.get(), "account number")
            amount = parse_amount(self.l_amount.get(), "Loan amount")
            if amount < cfg.MIN_LOAN_AMOUNT:
                raise ValueError(f"Minimum loan amount is {format_inr(cfg.MIN_LOAN_AMOUNT)}.")
            rate = loan_calc.parse_rate(self.l_rate.get())
            months = self._tenure_months()
            return self.db.apply_loan(acc, amount, months, rate), amount, months, rate

        ok, res = self._guard(work)
        if not ok:
            return
        result, amount, months, rate = res
        messagebox.showinfo(
            "Application Submitted",
            f"Loan #{result['loan_id']} for {format_inr(amount)} is now Pending approval.\n\n"
            f"{months} months @ {rate}% p.a.  →  EMI {format_inr(result['emi'])}")
        self.l_account.delete(0, "end")
        self.l_amount.delete(0, "end")
        self._update_emi_preview()
        self._reload_loans()

    def _selected_request(self, want_status, action):
        """Applications table se selected loan (id, amount_text) ya None (message ke saath)."""
        selected = self.l_tree.selection()
        if not selected:
            messagebox.showinfo("Select a loan", "Please select a loan from the table first.")
            return None
        status = self.l_tree.set(selected[0], "status")
        if status != want_status:
            messagebox.showinfo("Not possible", f"Loan #{selected[0]} is {status} - only a "
                                                f"{want_status} loan can be {action}.")
            return None
        return int(selected[0]), self.l_tree.set(selected[0], "amount")

    def _approve_loan(self):
        picked = self._selected_request("Pending", "approved")
        if not picked:
            return
        loan_id, amount = picked
        if not messagebox.askyesno(
                "Confirm Disbursement",
                f"Approve loan #{loan_id} of ₹ {amount} and credit it to the customer's account?"):
            return
        ok, loan = self._guard(lambda: self.db.approve_loan(loan_id))
        if ok:
            messagebox.showinfo(
                "Loan Disbursed",
                f"{format_inr(loan['loan_amount'])} credited to account {loan['account_number']}.\n"
                f"EMI {format_inr(loan['emi_amount'])} x {loan['tenure_months']} months - "
                "repay from the 'Repay & Close' tab.")
            self._reload_loans()

    def _reject_loan(self):
        picked = self._selected_request("Pending", "rejected")
        if not picked:
            return
        loan_id, amount = picked
        if not messagebox.askyesno("Reject Loan", f"Reject loan #{loan_id} of ₹ {amount}?"):
            return
        ok, _ = self._guard(lambda: self.db.reject_loan(loan_id))
        if ok:
            messagebox.showinfo("Loan Rejected", f"Loan #{loan_id} has been rejected.")
            self._reload_loans()

    # ---------------------------------------------- tab 2: repay & close
    def _build_loan_repay(self):
        body = self.loan_body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ---- left: active + closed loans ----
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(head, text="Loan Accounts  (select one)", font=font(14, True)).pack(side="left")
        self._button(head, "⟳", self._after_loan_change, cfg.BRAND_BLUE, 44, 30).pack(side="right")
        wrapper, self.r_tree = self._make_tree(left, [
            ("id", "Loan", 48, "center"),
            ("name", "Customer", 105, "w"),
            ("out", "Outstanding (₹)", 105, "e"),
            ("emi", "EMI (₹)", 80, "e"),
            ("status", "Status", 65, "center"),
        ], height=8)
        wrapper.pack(fill="both", expand=True)
        self.r_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_loan_details())

        # ---- right: loan account card ----
        card = ctk.CTkFrame(body, corner_radius=15, fg_color=cfg.BG_CARD)
        card.grid(row=0, column=1, sticky="n")
        self.r_title = ctk.CTkLabel(card, text="Select a loan", font=font(16, True))
        self.r_title.pack(anchor="w", padx=18, pady=(16, 0))
        self.r_details = ctk.CTkLabel(card, text="Pick a loan from the list to see its repayment "
                                                 "details.", justify="left", anchor="w",
                                      font=("Consolas", 11), text_color="#d0d0d0")
        self.r_details.pack(anchor="w", padx=18, pady=(8, 0))

        self.r_emi_btn = self._button(card, "💳 Pay EMI", self._pay_emi, cfg.GREEN, 330, 42, "black")
        self.r_emi_btn.pack(padx=18, pady=(14, 0))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(padx=18, pady=(10, 0))
        self.r_part = ctk.CTkEntry(row, width=180, height=40, placeholder_text="Part-payment (₹)")
        self.r_part.pack(side="left")
        self.r_part_btn = self._button(row, "💰 Part Pay", self._part_pay, cfg.ORANGE, 142, 40, "black")
        self.r_part_btn.pack(side="left", padx=(8, 0))
        self.r_close_btn = self._button(card, "🔒 Close Loan (Full Payment)", self._close_loan,
                                        cfg.RED, 330, 42)
        self.r_close_btn.pack(padx=18, pady=(10, 18))

        self._after_loan_change()

    def _render_loan_accounts(self):
        loans = [loan for loan in self._loans if loan["status"] in ("Approved", "Closed")]
        loans.sort(key=lambda loan: (loan["status"] != "Approved", -loan["loan_id"]))   # active pehle
        self.r_tree.delete(*self.r_tree.get_children())
        for loan in loans:
            self.r_tree.insert(
                "", "end", iid=str(loan["loan_id"]), tags=(str(loan["status"]).lower(),),
                values=(loan["loan_id"], loan["customer_name"],
                        format_inr(loan["outstanding_amount"] or 0, symbol=False),
                        format_inr(loan["emi_amount"] or 0, symbol=False), loan["status"]))
        keep = str(self._sel_loan_id)
        if keep in self.r_tree.get_children():
            self.r_tree.selection_set(keep)

    def _after_loan_change(self):
        """Loans dobara load karo, table + right card refresh karo."""
        self._fetch_loans()
        self._render_loan_accounts()
        self._show_loan_details()

    def _current_loan(self):
        selected = self.r_tree.selection()
        if not selected:
            return None
        self._sel_loan_id = int(selected[0])
        return next((loan for loan in self._loans if loan["loan_id"] == self._sel_loan_id), None)

    def _loan_detail_text(self, loan):
        def line(label, value):
            return f"{label:<15}{value:>23}"

        def m(value):
            return format_inr(value or 0, symbol=False)

        rows = [
            line("Customer", str(loan["customer_name"])[:22]),
            line("Account No", loan["account_number"]),
            line("A/C Balance", m(loan["account_balance"])),
            line("Loan Amount", m(loan["loan_amount"])),
            line("Interest", f"{loan['interest_rate']}% p.a."),
            line("EMI", m(loan["emi_amount"])),
            line("EMIs Paid", f"{loan['emis_paid']} / {loan['tenure_months']}"),
            line("Outstanding", m(loan["outstanding_amount"])),
            line("Total Repaid", m(loan["total_paid"])),
        ]
        if loan["status"] == "Approved":
            inst = loan_calc.next_installment(
                loan["outstanding_amount"], loan["interest_rate"], loan["emi_amount"],
                loan["emis_paid"], loan["tenure_months"])
            left = loan_calc.remaining_emis(loan["outstanding_amount"], loan["interest_rate"],
                                            loan["emi_amount"])
            rows += [
                "-" * 38,
                line("Next EMI", m(inst["payment"])),
                line("  Interest", m(inst["interest"])),
                line("  Principal", m(inst["principal"])),
                line("EMIs left (est.)", "-" if left is None else left),
            ]
        elif loan["closed_on"]:
            rows += ["-" * 38, line("Closed on", loan["closed_on"].strftime("%d-%b-%Y"))]
        return "(amounts in ₹)\n" + "\n".join(rows)

    def _show_loan_details(self):
        loan = self._current_loan()
        if loan is None:
            self.r_title.configure(text="Select a loan")
            self.r_details.configure(text="Pick a loan from the list to see its repayment details.")
            active = False
        else:
            active = loan["status"] == "Approved"
            self.r_title.configure(
                text=f"Loan #{loan['loan_id']}  •  {loan['status']}",
                text_color=cfg.GREEN if active else "gray")
            self.r_details.configure(text=self._loan_detail_text(loan))
        state = "normal" if active else "disabled"
        for widget in (self.r_emi_btn, self.r_part_btn, self.r_close_btn, self.r_part):
            widget.configure(state=state)

    def _active_loan_or_none(self):
        loan = self._current_loan()
        if loan is None:
            messagebox.showinfo("Select a loan", "Please select a loan from the list first.")
            return None
        if loan["status"] != "Approved":
            messagebox.showinfo("Loan not active", f"Loan #{loan['loan_id']} is {loan['status']}.")
            return None
        return loan

    def _pay_emi(self):
        loan = self._active_loan_or_none()
        if not loan:
            return
        inst = loan_calc.next_installment(
            loan["outstanding_amount"], loan["interest_rate"], loan["emi_amount"],
            loan["emis_paid"], loan["tenure_months"])
        if not messagebox.askyesno(
                "Confirm EMI Payment",
                f"Pay EMI {loan['emis_paid'] + 1} of {loan['tenure_months']} for loan #{loan['loan_id']}?\n\n"
                f"EMI amount : {format_inr(inst['payment'])}\n"
                f"   Interest  : {format_inr(inst['interest'])}\n"
                f"   Principal : {format_inr(inst['principal'])}\n\n"
                f"Debit from account {loan['account_number']} ({loan['customer_name']})\n"
                f"Available balance: {format_inr(loan['account_balance'])}"):
            return
        ok, res = self._guard(lambda: self.db.repay_emi(loan["loan_id"]))
        if not ok:
            return
        text = (f"EMI of {format_inr(res['payment'])} paid.\n"
                f"Outstanding principal: {format_inr(res['outstanding'])}\n"
                f"Account balance: {format_inr(res['balance'])}")
        if res["closed"]:
            text = "That was the final EMI - the loan is now CLOSED. 🎉\n\n" + text
        messagebox.showinfo("EMI Paid", text)
        self._after_loan_change()

    def _part_pay(self):
        loan = self._active_loan_or_none()
        if not loan:
            return
        ok, amount = self._guard(lambda: parse_amount(self.r_part.get(), "Part-payment amount"))
        if not ok:
            return
        if amount >= loan["outstanding_amount"]:
            messagebox.showwarning(
                "Amount too high",
                f"Part-payment must be less than the outstanding principal "
                f"({format_inr(loan['outstanding_amount'])}).\nUse 'Close Loan' to pay off everything.")
            return
        after = loan["outstanding_amount"] - amount
        if not messagebox.askyesno(
                "Confirm Part-Payment",
                f"Pay {format_inr(amount)} towards loan #{loan['loan_id']}?\n\n"
                "The full amount reduces your principal - the EMI stays the same, "
                "so the loan finishes earlier.\n\n"
                f"Outstanding after payment: {format_inr(after)}\n"
                f"Debit from account {loan['account_number']} "
                f"(balance {format_inr(loan['account_balance'])})"):
            return
        ok, res = self._guard(lambda: self.db.part_payment(loan["loan_id"], amount))
        if not ok:
            return
        messagebox.showinfo(
            "Part-Payment Done",
            f"{format_inr(res['payment'])} paid.\nOutstanding principal: {format_inr(res['outstanding'])}\n"
            f"Account balance: {format_inr(res['balance'])}")
        self.r_part.delete(0, "end")
        self._after_loan_change()

    def _close_loan(self):
        loan = self._active_loan_or_none()
        if not loan:
            return
        quote = loan_calc.closure_quote(loan["outstanding_amount"], loan["interest_rate"])
        if not messagebox.askyesno(
                "Confirm Loan Closure",
                f"Close loan #{loan['loan_id']} with full payment?\n\n"
                f"Outstanding principal : {format_inr(quote['principal'])}\n"
                f"Interest (this cycle) : {format_inr(quote['interest'])}\n"
                f"Foreclosure charge ({loan_calc.FORECLOSURE_CHARGE_PERCENT}%) : {format_inr(quote['charge'])}\n"
                f"{'-' * 40}\n"
                f"TOTAL PAYABLE         : {format_inr(quote['total'])}\n\n"
                f"Debit from account {loan['account_number']} "
                f"(balance {format_inr(loan['account_balance'])})"):
            return
        ok, res = self._guard(lambda: self.db.close_loan(loan["loan_id"], quote["total"]))
        if not ok:
            return
        messagebox.showinfo(
            "Loan Closed ✓",
            f"Loan #{loan['loan_id']} is fully paid and CLOSED.\n\n"
            f"Total paid now: {format_inr(res['total'])}\nAccount balance: {format_inr(res['balance'])}")
        self._after_loan_change()


if __name__ == "__main__":
    app = BankPayrollApp()
    app.mainloop()