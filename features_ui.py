"""Fund Transfer + Bulk Payroll screens (main.py ke theme ke saath match)."""
import re
from datetime import datetime
from tkinter import ttk, messagebox

import customtkinter as ctk

import config as cfg
import features_db as fdb
import undo_db


def _tree(parent, columns, height=8):
    """columns = [(heading, width, anchor)]  ->  (wrapper, treeview)  (main.py wala Nexus.Treeview style)"""
    wrapper = ctk.CTkFrame(parent, fg_color=cfg.BG_CARD, corner_radius=15)
    tree = ttk.Treeview(wrapper, columns=[c[0] for c in columns], show="headings",
                        style="Nexus.Treeview", selectmode="browse", height=height)
    for heading, width, anchor in columns:
        tree.heading(heading, text=heading)
        tree.column(heading, width=width, anchor=anchor, stretch=(anchor == "w"))
    scroll = ctk.CTkScrollbar(wrapper, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)
    scroll.pack(side="right", fill="y", padx=(0, 6), pady=12)
    tree.tag_configure("paid", foreground=cfg.GREEN)
    tree.tag_configure("unpaid", foreground=cfg.ORANGE)
    return wrapper, tree


def _header(parent, title, subtitle):
    ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w", pady=(0, 2))
    ctk.CTkLabel(parent, text=subtitle, font=ctk.CTkFont(size=13), text_color="gray").pack(
        anchor="w", pady=(0, 16))


class TransferFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        fdb.init_tables()
        _header(self, "Fund Transfer", "Send money from one account to another - safe debit + credit in one go")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(body, corner_radius=15, fg_color=cfg.BG_CARD)
        card.grid(row=0, column=0, sticky="n", padx=(0, 14))
        self.src = self._field(card, "From Account No.", "e.g. 10001")
        self.dst = self._field(card, "To Account No.", "e.g. 10002")
        self.amt = self._field(card, "Amount (₹)", "e.g. 5000")
        self.rem = self._field(card, "Remark (optional)", "e.g. Rent")
        ctk.CTkButton(card, text="🔁 Send Money", width=260, height=44, fg_color=cfg.GREEN,
                      hover_color="#1e9e52", text_color="black",
                      font=ctk.CTkFont(size=13, weight="bold"), command=self.send).pack(
            anchor="w", padx=40, pady=(24, 30))

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(right, text="Recent Transfers", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", pady=(0, 6))
        wrapper, self.tree = _tree(right, [("Reference", 140, "center"), ("From", 60, "center"),
                                           ("To", 60, "center"), ("Amount", 100, "e"),
                                           ("Date", 140, "center")], height=10)
        wrapper.pack(fill="both", expand=True)
        self.load()

    @staticmethod
    def _field(parent, label, placeholder):
        ctk.CTkLabel(parent, text=label, text_color="#c8c8c8").pack(anchor="w", padx=40, pady=(16, 4))
        e = ctk.CTkEntry(parent, width=260, height=38, placeholder_text=placeholder)
        e.pack(anchor="w", padx=40)
        return e

    def load(self):
        self.tree.delete(*self.tree.get_children())
        try:
            rows = fdb.recent_transfers()
        except Exception as e:
            return messagebox.showerror("Database Error", str(e))
        for r in rows:
            self.tree.insert("", "end", values=(r[0], r[1], r[2], f"₹{r[3]:,.2f}",
                                                r[4].strftime("%d-%b-%Y %I:%M %p")))

    def send(self):
        try:
            src, dst = int(self.src.get()), int(self.dst.get())
            amount = float(self.amt.get())
        except ValueError:
            return messagebox.showerror("Error", "Account number aur amount sahi daalo.")
        try:
            s, d = fdb.get_customer(src), fdb.get_customer(dst)
        except Exception as e:
            return messagebox.showerror("Database Error", str(e))
        if not s or not d:
            return messagebox.showerror("Error", "Sender ya receiver account nahi mila.")
        if not messagebox.askyesno("Confirm", f"{s[0]} (A/C {src})  →  {d[0]} (A/C {dst})\n"
                                              f"Amount: ₹{amount:,.2f}\n\nTransfer karein?"):
            return
        try:
            ref = fdb.transfer_funds(src, dst, amount, self.rem.get().strip())
        except Exception as e:
            return messagebox.showerror("Transfer Failed", str(e))
        try:
            undo_db.log("transfer", src, amount, counterparty=dst,
                        description=f"Transfer {ref}: {src} → {dst}")
        except Exception:
            pass  # undo table na bane to bhi asal transfer fail nahi hoga
        messagebox.showinfo(
            "Success",
            f"Transfer ho gaya!\nReference: {ref}\n\n"
            f"Undo available for {undo_db.WINDOW_SECONDS}s from the Undo Window page.")
        for w in (self.src, self.dst, self.amt, self.rem):
            w.delete(0, "end")
        self.load()


class BulkPayrollFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        fdb.init_tables()
        _header(self, "Bulk Payroll & Attendance", "Attendance set karo, phir ek click me sabhi employees ko salary do")

        top = ctk.CTkFrame(self, fg_color=cfg.BG_CARD, corner_radius=15)
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="Month (YYYY-MM)").pack(side="left", padx=(20, 5), pady=14)
        self.month = ctk.CTkEntry(top, width=100)
        self.month.insert(0, datetime.now().strftime("%Y-%m"))
        self.month.pack(side="left", padx=5)
        ctk.CTkLabel(top, text="Working days").pack(side="left", padx=(20, 5))
        self.wd = ctk.CTkEntry(top, width=60)
        self.wd.insert(0, "26")
        self.wd.pack(side="left", padx=5)
        ctk.CTkButton(top, text="Load", width=80, command=self.refresh).pack(side="left", padx=15)

        wrapper, self.tree = _tree(self, [
            ("ID", 45, "center"), ("Name", 130, "w"), ("Designation", 110, "w"), ("Basic", 80, "e"),
            ("Present", 60, "center"), ("Leave Ded.", 85, "e"), ("Tax", 75, "e"),
            ("Net Pay", 90, "e"), ("Status", 80, "center")], height=10)
        wrapper.pack(fill="both", expand=True, pady=(0, 8))

        bar = ctk.CTkFrame(self, fg_color=cfg.BG_CARD, corner_radius=15)
        bar.pack(fill="x")
        ctk.CTkLabel(bar, text="Selected employee ke Present days:").pack(side="left", padx=(20, 5), pady=14)
        self.present = ctk.CTkEntry(bar, width=60)
        self.present.pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Save Attendance", width=130, command=self.save_att).pack(side="left", padx=10)
        ctk.CTkButton(bar, text="💰 Pay All Employees", fg_color=cfg.GREEN, hover_color="#1e9e52",
                      text_color="black", command=self.pay_all).pack(side="right", padx=20)
        self.total = ctk.CTkLabel(bar, text="")
        self.total.pack(side="right", padx=10)
        self.refresh()

    def _params(self):
        m = self.month.get().strip()
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m):
            raise ValueError("Month format YYYY-MM hona chahiye (e.g. 2026-09).")
        wd = int(self.wd.get())
        if wd <= 0 or wd > 31:
            raise ValueError("Working days 1 se 31 ke beech hone chahiye.")
        return m, wd

    def refresh(self):
        try:
            m, wd = self._params()
            att, paid, emps = fdb.get_attendance(m), fdb.get_paid_ids(m), fdb.get_employees()
        except ValueError as e:
            return messagebox.showerror("Error", str(e))
        except Exception as e:
            return messagebox.showerror("Database Error", str(e))
        self.tree.delete(*self.tree.get_children())
        total = 0
        for eid, name, desig, basic, acct in emps:
            pr = att.get(eid, wd)
            s = fdb.calc_salary(basic, wd, pr)
            if eid not in paid:
                total += s["net"]
            self.tree.insert("", "end", iid=str(eid), tags=("paid" if eid in paid else "unpaid",), values=(
                eid, name, desig, f"{basic:,.0f}", pr, f"{s['leave_ded']:,.2f}",
                f"{s['tax']:,.2f}", f"{s['net']:,.2f}", "Paid ✓" if eid in paid else "Pending"))
        self.total.configure(text=f"Payable: ₹{total:,.2f}")

    def save_att(self):
        sel = self.tree.selection()
        if not sel:
            return messagebox.showwarning("Select", "Pehle table se employee select karo.")
        try:
            m, wd = self._params()
            fdb.set_attendance(int(sel[0]), m, wd, int(self.present.get()))
        except ValueError as e:
            return messagebox.showerror("Error", str(e))
        self.refresh()

    def pay_all(self):
        try:
            m, wd = self._params()
        except ValueError as e:
            return messagebox.showerror("Error", str(e))
        if not messagebox.askyesno("Confirm", f"{m} ki salary sabhi pending employees ko dein?"):
            return
        try:
            n, total = fdb.run_bulk_payroll(m, wd)
        except Exception as e:
            return messagebox.showerror("Payroll Failed", str(e))
        messagebox.showinfo("Done", f"{n} employees ko ₹{total:,.2f} pay kiya gaya.")
        self.refresh()