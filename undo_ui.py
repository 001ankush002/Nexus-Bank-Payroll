"""Undo Window screen - recent transactions ko thodi der ke andar reverse karo."""
from tkinter import ttk, messagebox

import customtkinter as ctk

import config as cfg
import undo_db

KIND_LABELS = {
    "deposit": "💰 Deposit",
    "withdraw": "💸 Withdraw",
    "transfer": "🔁 Transfer",
    "emi": "💳 Loan EMI",
}


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
    return wrapper, tree


class UndoFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        undo_db.init_table()
        self._tick_job = None

        ctk.CTkLabel(self, text="Undo Window", font=ctk.CTkFont(size=26, weight="bold")).pack(
            anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            self,
            text=f"Deposit, Withdraw, Transfer aur Loan EMI payments {undo_db.WINDOW_SECONDS} seconds "
                 "tak one-click undo ho sakte hain - koi approval ki zarurat nahi.",
            font=ctk.CTkFont(size=13), text_color="gray", wraplength=760, justify="left").pack(
            anchor="w", pady=(0, 16))

        wrapper, self.tree = _tree(self, [
            ("Type", 110, "w"), ("Account", 90, "center"), ("Amount", 110, "e"),
            ("Details", 280, "w"), ("Time Left", 90, "center")], height=12)
        wrapper.pack(fill="both", expand=True, pady=(0, 10))

        bar = ctk.CTkFrame(self, fg_color=cfg.BG_CARD, corner_radius=15)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="↩ Undo Selected", fg_color=cfg.RED, hover_color="#d63031",
                      command=self.undo_selected).pack(side="left", padx=20, pady=14)
        self.status = ctk.CTkLabel(bar, text="", text_color="gray")
        self.status.pack(side="left", padx=10)

        self._tick()

    def destroy(self):
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        super().destroy()

    def _tick(self):
        self.refresh()
        self._tick_job = self.after(1000, self._tick)

    def refresh(self):
        selected = self.tree.selection()
        keep = selected[0] if selected else None
        try:
            rows = undo_db.get_active()
        except Exception as e:
            self.status.configure(text=f"Database error: {e}", text_color=cfg.RED)
            return
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            label = KIND_LABELS.get(r["kind"], r["kind"])
            details = r["description"] or "-"
            self.tree.insert("", "end", iid=str(r["undo_id"]), values=(
                label, r["account_number"], f"₹{float(r['amount']):,.2f}", details,
                f"{r['seconds_left']}s"))
        if keep and keep in self.tree.get_children():
            self.tree.selection_set(keep)
        self.status.configure(
            text=f"{len(rows)} transaction(s) undoable right now." if rows else
                 "No transactions in the undo window right now.", text_color="gray")

    def undo_selected(self):
        selected = self.tree.selection()
        if not selected:
            return messagebox.showinfo("Select a transaction", "Pehle table se ek row select karo.")
        undo_id = int(selected[0])
        values = self.tree.item(selected[0], "values")
        if not messagebox.askyesno(
                "Confirm Undo",
                f"{values[0]}  of  {values[2]}\n{values[3]}\n\n"
                "Ye turant reverse ho jaayega - kisi approval ki zarurat nahi. Undo karein?"):
            return
        try:
            desc = undo_db.undo(undo_id)
        except Exception as e:
            return messagebox.showerror("Undo Failed", str(e))
        messagebox.showinfo("Undone ✓", desc)
        self.refresh()