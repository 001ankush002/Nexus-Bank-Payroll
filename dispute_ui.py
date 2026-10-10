"""Dispute Center - customer khud transaction freeze kare, admin resolve kare."""
from tkinter import ttk, messagebox

import customtkinter as ctk

import config as cfg
import dispute_db
import undo_db


def _tree(parent, columns, height=10):
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
    tree.tag_configure("open", foreground=cfg.ORANGE)
    tree.tag_configure("approved", foreground=cfg.GREEN)
    tree.tag_configure("rejected", foreground=cfg.RED)
    return wrapper, tree


class DisputeFrame(ctk.CTkFrame):
    TAB_FILE = "🚩 File a Dispute"
    TAB_RESOLVE = "🔍 Resolve Disputes"

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        dispute_db.init_table()

        ctk.CTkLabel(self, text="Dispute Center", font=ctk.CTkFont(size=26, weight="bold")).pack(
            anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            self,
            text=(f"Transactions up to {dispute_db.WINDOW_DAYS} days old can be disputed - much longer "
                 f"than the {undo_db.WINDOW_SECONDS}s Undo Window. Filing freezes the amount instantly; "
                 "an admin approves (refund) or rejects (release hold) later."),
            font=ctk.CTkFont(size=13), text_color="gray", wraplength=760, justify="left").pack(
            anchor="w", pady=(0, 16))

        self.tabs = ctk.CTkSegmentedButton(self, values=[self.TAB_FILE, self.TAB_RESOLVE],
                                           command=self._switch_tab, height=36)
        self.tabs.pack(anchor="w", pady=(0, 12))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

        self.tabs.set(self.TAB_FILE)
        self._switch_tab(self.TAB_FILE)

    def _switch_tab(self, tab):
        for w in self.body.winfo_children():
            w.destroy()
        if tab == self.TAB_RESOLVE:
            self._build_resolve()
        else:
            self._build_file()

    # ---------------------------------------------- Tab 1: File a Dispute
    def _build_file(self):
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        top = ctk.CTkFrame(body, fg_color=cfg.BG_CARD, corner_radius=15)
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="Account Number").pack(side="left", padx=(20, 8), pady=14)
        self.f_account = ctk.CTkEntry(top, width=140, placeholder_text="e.g. 10001")
        self.f_account.pack(side="left")
        self.f_account.bind("<Return>", lambda _e: self._load_transactions())
        ctk.CTkButton(top, text="🔍 Load Transactions", width=150,
                      command=self._load_transactions).pack(side="left", padx=12)
        self.f_held = ctk.CTkLabel(top, text="", text_color="gray")
        self.f_held.pack(side="right", padx=20)

        wrapper, self.f_tree = _tree(body, [
            ("Txn ID", 70, "center"), ("Type", 140, "w"), ("Amount", 110, "e"),
            ("Date", 150, "center"), ("Status", 110, "center")], height=9)
        wrapper.pack(fill="both", expand=True, pady=(0, 8))

        bottom = ctk.CTkFrame(body, fg_color=cfg.BG_CARD, corner_radius=15)
        bottom.pack(fill="x")
        ctk.CTkLabel(bottom, text="Reason for dispute").pack(anchor="w", padx=20, pady=(14, 4))
        self.f_reason = ctk.CTkEntry(bottom, width=500, placeholder_text="e.g. I don't recognize this transaction")
        self.f_reason.pack(anchor="w", padx=20)
        ctk.CTkButton(bottom, text="🚩 Freeze & File Dispute", fg_color=cfg.ORANGE, hover_color="#cc8400",
                      text_color="black", command=self._file).pack(anchor="w", padx=20, pady=16)

    def _load_transactions(self):
        try:
            acc = int(self.f_account.get())
        except ValueError:
            return messagebox.showerror("Error", "Sahi account number daalo.")
        try:
            rows = dispute_db.get_recent_transactions(acc)
            held = dispute_db.held_amount(acc)
        except Exception as e:
            return messagebox.showerror("Database Error", str(e))
        self.f_tree.delete(*self.f_tree.get_children())
        for r in rows:
            status = r["dispute_status"] or "-"
            self.f_tree.insert("", "end", iid=str(r["transaction_id"]), values=(
                r["transaction_id"], r["transaction_type"], f"₹{float(r['amount']):,.2f}",
                r["transaction_date"].strftime("%d-%b-%Y %I:%M %p"), status))
        self.f_held.configure(text=f"Currently frozen on this account: ₹{float(held):,.2f}")

    def _file(self):
        selected = self.f_tree.selection()
        if not selected:
            return messagebox.showinfo("Select a transaction", "Pehle table se ek transaction select karo.")
        txn_id = int(selected[0])
        status = self.f_tree.set(selected[0], "Status")
        if status != "-":
            return messagebox.showwarning("Already disputed", f"Ye transaction pehle hi {status} status me hai.")
        reason = self.f_reason.get().strip()
        if not reason:
            return messagebox.showwarning("Reason needed", "Dispute ki reason likhna zaroori hai.")
        amount_text = self.f_tree.set(selected[0], "Amount")
        if not messagebox.askyesno(
                "Confirm Freeze",
                f"Transaction #{txn_id} ({amount_text}) ko dispute karke turant freeze karein?\n\n"
                "Ye amount tab tak spend nahi ho sakega jab tak admin resolve na kare."):
            return
        try:
            result = dispute_db.file_dispute(txn_id, reason)
        except Exception as e:
            return messagebox.showerror("Dispute Failed", str(e))
        messagebox.showinfo(
            "Frozen ✓",
            f"Dispute #{result['dispute_id']} filed.\n₹{result['amount']:,.2f} is now frozen on "
            f"account {result['account_number']} until an admin resolves it.")
        self.f_reason.delete(0, "end")
        self._load_transactions()

    # ---------------------------------------------- Tab 2: Resolve Disputes
    def _build_resolve(self):
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(head, text="Open Disputes  (select one)", font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left")
        ctk.CTkButton(head, text="⟳", width=44, command=self._load_disputes).pack(side="right")

        wrapper, self.r_tree = _tree(body, [
            ("ID", 45, "center"), ("Account", 80, "center"), ("Customer", 130, "w"),
            ("Type", 110, "w"), ("Amount", 100, "e"), ("Reason", 220, "w"),
            ("Filed", 130, "center"), ("Status", 80, "center")], height=9)
        wrapper.pack(fill="both", expand=True, pady=(0, 8))
        self.r_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())

        card = ctk.CTkFrame(body, corner_radius=15, fg_color=cfg.BG_CARD)
        card.pack(fill="x")
        self.r_detail = ctk.CTkLabel(card, text="Select a dispute to review it.", justify="left",
                                     anchor="w", text_color="#d0d0d0")
        self.r_detail.pack(anchor="w", padx=20, pady=(16, 8))
        ctk.CTkLabel(card, text="Resolution note (optional)").pack(anchor="w", padx=20)
        self.r_note = ctk.CTkEntry(card, width=500, placeholder_text="e.g. Verified as unauthorized, refunding")
        self.r_note.pack(anchor="w", padx=20, pady=(4, 14))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(0, 18))
        ctk.CTkButton(row, text="✅ Approve (Refund)", fg_color=cfg.GREEN, hover_color="#1e9e52",
                      text_color="black", width=190, command=lambda: self._resolve(True)).pack(
            side="left", padx=(0, 10))
        ctk.CTkButton(row, text="❌ Reject (Release Hold)", fg_color=cfg.RED, hover_color="#d63031",
                      width=190, command=lambda: self._resolve(False)).pack(side="left")

        self._load_disputes()

    def _load_disputes(self):
        try:
            rows = dispute_db.get_disputes(status="Open")
        except Exception as e:
            return messagebox.showerror("Database Error", str(e))
        self.r_tree.delete(*self.r_tree.get_children())
        for d in rows:
            self.r_tree.insert("", "end", iid=str(d["dispute_id"]), tags=(d["status"].lower(),), values=(
                d["dispute_id"], d["account_number"], d["customer_name"], d["transaction_type"],
                f"₹{float(d['amount']):,.2f}", d["reason"] or "-",
                d["filed_at"].strftime("%d-%b-%Y %I:%M %p"), d["status"]))
        self._show_selected()

    def _show_selected(self):
        selected = self.r_tree.selection()
        if not selected:
            self.r_detail.configure(text="Select a dispute to review it.")
            return
        v = self.r_tree.item(selected[0], "values")
        self.r_detail.configure(
            text=f"Dispute #{v[0]}   •   Account {v[1]} ({v[2]})\n"
                 f"Original transaction: {v[3]}  -  {v[4]}\nReason: {v[5]}")

    def _resolve(self, approve):
        selected = self.r_tree.selection()
        if not selected:
            return messagebox.showinfo("Select a dispute", "Pehle table se ek dispute select karo.")
        dispute_id = int(selected[0])
        v = self.r_tree.item(selected[0], "values")
        action = "Approve (refund)" if approve else "Reject (release hold)"
        if not messagebox.askyesno("Confirm", f"Dispute #{dispute_id} ({v[4]}) ko {action} karein?"):
            return
        try:
            desc = dispute_db.resolve(dispute_id, approve, self.r_note.get().strip())
        except Exception as e:
            return messagebox.showerror("Resolve Failed", str(e))
        messagebox.showinfo("Resolved ✓", desc)
        self.r_note.delete(0, "end")
        self._load_disputes()