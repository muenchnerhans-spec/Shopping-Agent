"""
MainWindow – tkinter GUI for the Idealo Price Tracker.

Tabs:
  1. Watchlist  – Add / remove / edit tracked items; see current prices.
  2. History    – Plot or list price history for a selected item.
  3. Alerts     – Log of all triggered price alerts.
  4. Settings   – Scrape interval and e-mail notification preferences.
"""

import logging
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class MainWindow:
    """Root application window."""

    def __init__(
        self,
        orchestrator,   # OrchestratorAgent
        storage,        # StorageAgent
        notifier,       # NotifierAgent
        apply_email_settings: Optional[Callable] = None,
    ) -> None:
        self._orch = orchestrator
        self._storage = storage
        self._notifier = notifier
        self._apply_email_settings = apply_email_settings

        self._root = tk.Tk()
        self._root.title("Idealo Price Tracker")
        self._root.geometry("900x600")
        self._root.minsize(700, 450)

        self._build_ui()
        self._register_callbacks()
        self._refresh_watchlist()
        self._load_email_settings()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the tkinter main loop (blocks until window is closed)."""
        self._root.mainloop()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_toolbar()

        notebook = ttk.Notebook(self._root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._tab_watchlist = ttk.Frame(notebook)
        self._tab_history = ttk.Frame(notebook)
        self._tab_alerts = ttk.Frame(notebook)
        self._tab_settings = ttk.Frame(notebook)

        notebook.add(self._tab_watchlist, text="Watchlist")
        notebook.add(self._tab_history, text="Preisverlauf")
        notebook.add(self._tab_alerts, text="Preisalarme")
        notebook.add(self._tab_settings, text="Einstellungen")

        self._build_watchlist_tab()
        self._build_history_tab()
        self._build_alerts_tab()
        self._build_settings_tab()

        self._build_statusbar()

    # ---- Toolbar --------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self._root)
        bar.pack(fill=tk.X, padx=4, pady=(4, 0))

        ttk.Button(bar, text="Jetzt prüfen", command=self._on_run_now).pack(
            side=tk.LEFT, padx=2
        )
        self._btn_start_stop = ttk.Button(
            bar, text="Scheduler starten", command=self._on_toggle_scheduler
        )
        self._btn_start_stop.pack(side=tk.LEFT, padx=2)

        self._lbl_next_run = ttk.Label(bar, text="")
        self._lbl_next_run.pack(side=tk.RIGHT, padx=8)

    # ---- Watchlist tab --------------------------------------------------

    def _build_watchlist_tab(self) -> None:
        frame = self._tab_watchlist

        # Input form
        form = ttk.LabelFrame(frame, text="Neues Produkt hinzufügen")
        form.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(form, text="Name:").grid(row=0, column=0, padx=4, pady=3, sticky=tk.W)
        self._entry_name = ttk.Entry(form, width=28)
        self._entry_name.grid(row=0, column=1, padx=4, pady=3, sticky=tk.W)

        ttk.Label(form, text="Suchbegriff:").grid(row=0, column=2, padx=4, pady=3, sticky=tk.W)
        self._entry_query = ttk.Entry(form, width=32)
        self._entry_query.grid(row=0, column=3, padx=4, pady=3, sticky=tk.W)

        ttk.Label(form, text="Zielpreis (€):").grid(row=1, column=0, padx=4, pady=3, sticky=tk.W)
        self._entry_target = ttk.Entry(form, width=12)
        self._entry_target.grid(row=1, column=1, padx=4, pady=3, sticky=tk.W)

        ttk.Label(form, text="Alarm bei Preisfall (%):").grid(
            row=1, column=2, padx=4, pady=3, sticky=tk.W
        )
        self._entry_drop = ttk.Entry(form, width=10)
        self._entry_drop.insert(0, "5")
        self._entry_drop.grid(row=1, column=3, padx=4, pady=3, sticky=tk.W)

        ttk.Button(form, text="Hinzufügen", command=self._on_add_item).grid(
            row=1, column=4, padx=8, pady=3
        )

        # Table
        cols = ("name", "query", "last_price", "target_price", "last_checked")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("name", text="Name")
        self._tree.heading("query", text="Suchbegriff")
        self._tree.heading("last_price", text="Letzter Preis")
        self._tree.heading("target_price", text="Zielpreis")
        self._tree.heading("last_checked", text="Zuletzt geprüft")
        self._tree.column("name", width=160)
        self._tree.column("query", width=200)
        self._tree.column("last_price", width=110, anchor=tk.CENTER)
        self._tree.column("target_price", width=100, anchor=tk.CENTER)
        self._tree.column("last_checked", width=160, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)

        self._tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0), side=tk.LEFT)
        scroll.pack(fill=tk.Y, pady=(4, 0), side=tk.LEFT)

        # Buttons below table
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(btn_frame, text="Entfernen", command=self._on_remove_item).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Aktualisieren", command=self._refresh_watchlist).pack(
            side=tk.LEFT, padx=2
        )

    # ---- History tab ----------------------------------------------------

    def _build_history_tab(self) -> None:
        frame = self._tab_history

        top = ttk.Frame(frame)
        top.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(top, text="Produkt:").pack(side=tk.LEFT)
        self._combo_history_item = ttk.Combobox(top, state="readonly", width=30)
        self._combo_history_item.pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Laden", command=self._on_load_history).pack(side=tk.LEFT)

        cols = ("timestamp", "price", "url")
        self._tree_history = ttk.Treeview(
            frame, columns=cols, show="headings", selectmode="browse"
        )
        self._tree_history.heading("timestamp", text="Zeitpunkt")
        self._tree_history.heading("price", text="Preis (€)")
        self._tree_history.heading("url", text="URL")
        self._tree_history.column("timestamp", width=180)
        self._tree_history.column("price", width=100, anchor=tk.CENTER)
        self._tree_history.column("url", width=480)

        self._tree_history.bind("<Double-1>", self._on_history_double_click)

        scroll_h = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree_history.yview)
        self._tree_history.configure(yscrollcommand=scroll_h.set)
        self._tree_history.pack(fill=tk.BOTH, expand=True, padx=8, pady=4, side=tk.LEFT)
        scroll_h.pack(fill=tk.Y, pady=4, side=tk.LEFT)

    # ---- Alerts tab -----------------------------------------------------

    def _build_alerts_tab(self) -> None:
        frame = self._tab_alerts

        cols = ("timestamp", "item", "old_price", "new_price", "reason")
        self._tree_alerts = ttk.Treeview(
            frame, columns=cols, show="headings", selectmode="browse"
        )
        self._tree_alerts.heading("timestamp", text="Zeitpunkt")
        self._tree_alerts.heading("item", text="Produkt")
        self._tree_alerts.heading("old_price", text="Alt (€)")
        self._tree_alerts.heading("new_price", text="Neu (€)")
        self._tree_alerts.heading("reason", text="Grund")
        self._tree_alerts.column("timestamp", width=160)
        self._tree_alerts.column("item", width=160)
        self._tree_alerts.column("old_price", width=80, anchor=tk.CENTER)
        self._tree_alerts.column("new_price", width=80, anchor=tk.CENTER)
        self._tree_alerts.column("reason", width=300)

        scroll_a = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree_alerts.yview)
        self._tree_alerts.configure(yscrollcommand=scroll_a.set)
        self._tree_alerts.pack(fill=tk.BOTH, expand=True, padx=8, pady=6, side=tk.LEFT)
        scroll_a.pack(fill=tk.Y, pady=6, side=tk.LEFT)

        btn_f = ttk.Frame(frame)
        btn_f.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(btn_f, text="Log leeren", command=self._on_clear_alerts).pack(side=tk.LEFT)

    # ---- Settings tab ---------------------------------------------------

    def _build_settings_tab(self) -> None:
        frame = self._tab_settings

        # Scheduler section
        sched_frame = ttk.LabelFrame(frame, text="Scheduler")
        sched_frame.pack(fill=tk.X, padx=16, pady=12)

        ttk.Label(sched_frame, text="Prüfintervall (Minuten):").grid(
            row=0, column=0, padx=8, pady=6, sticky=tk.W
        )
        self._spin_interval = tk.Spinbox(sched_frame, from_=1, to=1440, width=6)
        from config import SCRAPE_INTERVAL_MINUTES
        self._spin_interval.delete(0, tk.END)
        self._spin_interval.insert(0, str(SCRAPE_INTERVAL_MINUTES))
        self._spin_interval.grid(row=0, column=1, padx=8, pady=6, sticky=tk.W)

        ttk.Button(sched_frame, text="Übernehmen", command=self._on_apply_interval).grid(
            row=0, column=2, padx=12, pady=6
        )

        # E-Mail section
        email_frame = ttk.LabelFrame(frame, text="E-Mail Benachrichtigungen")
        email_frame.pack(fill=tk.X, padx=16, pady=8)

        self._var_email_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            email_frame,
            text="E-Mail Benachrichtigungen aktivieren",
            variable=self._var_email_enabled,
        ).grid(row=0, column=0, columnspan=4, padx=8, pady=4, sticky=tk.W)

        fields = [
            ("SMTP Host:", "_entry_smtp_host", 1, 0, False),
            ("SMTP Port:", "_entry_smtp_port", 1, 2, False),
            ("Benutzername:", "_entry_email_user", 2, 0, False),
            ("Passwort:", "_entry_email_pass", 2, 2, True),
            ("Absender:", "_entry_email_sender", 3, 0, False),
            ("Empfänger:", "_entry_email_recipient", 3, 2, False),
        ]
        widths = {"_entry_smtp_port": 6}
        for label_text, attr, row, col, is_password in fields:
            ttk.Label(email_frame, text=label_text).grid(
                row=row, column=col, padx=8, pady=4, sticky=tk.W
            )
            entry = ttk.Entry(
                email_frame,
                width=widths.get(attr, 26),
                show="*" if is_password else "",
            )
            entry.grid(row=row, column=col + 1, padx=4, pady=4, sticky=tk.W)
            setattr(self, attr, entry)

        self._var_smtp_tls = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            email_frame, text="STARTTLS verwenden", variable=self._var_smtp_tls
        ).grid(row=4, column=0, columnspan=2, padx=8, pady=4, sticky=tk.W)

        btn_email_row = ttk.Frame(email_frame)
        btn_email_row.grid(row=5, column=0, columnspan=4, padx=8, pady=6, sticky=tk.W)
        ttk.Button(btn_email_row, text="Speichern", command=self._on_save_email_settings).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_email_row, text="Test-E-Mail senden", command=self._on_test_email).pack(
            side=tk.LEFT, padx=4
        )

    # ---- Statusbar ------------------------------------------------------

    def _build_statusbar(self) -> None:
        self._status_var = tk.StringVar(value="Bereit.")
        bar = ttk.Label(
            self._root,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
        )
        bar.pack(fill=tk.X, side=tk.BOTTOM, padx=2, pady=2)

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def _register_callbacks(self) -> None:
        self._orch.subscribe_status(self._on_run_status)
        self._notifier.subscribe(self._on_alert)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_add_item(self) -> None:
        name = self._entry_name.get().strip()
        query = self._entry_query.get().strip()
        if not name or not query:
            messagebox.showwarning("Eingabe fehlt", "Bitte Name und Suchbegriff angeben.")
            return

        target_price: Optional[float] = None
        drop_pct: Optional[float] = None
        try:
            raw = self._entry_target.get().strip()
            if raw:
                target_price = float(raw.replace(",", "."))
        except ValueError:
            messagebox.showerror("Ungültige Eingabe", "Zielpreis muss eine Zahl sein.")
            return
        try:
            raw = self._entry_drop.get().strip()
            if raw:
                drop_pct = float(raw.replace(",", "."))
        except ValueError:
            messagebox.showerror("Ungültige Eingabe", "Preisfall-Prozent muss eine Zahl sein.")
            return

        self._storage.add_item(name, query, target_price, drop_pct)
        self._entry_name.delete(0, tk.END)
        self._entry_query.delete(0, tk.END)
        self._entry_target.delete(0, tk.END)
        self._refresh_watchlist()
        self._set_status(f"'{name}' hinzugefügt.")

    def _on_remove_item(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Kein Produkt gewählt", "Bitte ein Produkt auswählen.")
            return
        item_id = self._tree.item(sel[0], "tags")[0]
        name = self._tree.item(sel[0], "values")[0]
        if messagebox.askyesno("Entfernen", f"'{name}' aus der Watchlist entfernen?"):
            self._storage.remove_item(item_id)
            self._refresh_watchlist()
            self._set_status(f"'{name}' entfernt.")

    def _on_run_now(self) -> None:
        self._set_status("Prüfe Preise…")
        self._orch.run_now_async()

    def _on_toggle_scheduler(self) -> None:
        if self._orch.is_running:
            self._orch.stop()
            self._btn_start_stop.config(text="Scheduler starten")
            self._set_status("Scheduler gestoppt.")
        else:
            self._orch.start()
            self._btn_start_stop.config(text="Scheduler stoppen")
            self._set_status("Scheduler gestartet.")

    def _on_load_history(self) -> None:
        name = self._combo_history_item.get()
        if not name:
            return
        # Find item id by name
        items = {item["name"]: item["id"] for item in self._storage.get_watchlist()}
        item_id = items.get(name)
        if not item_id:
            return
        history = self._storage.get_history(item_id)
        self._tree_history.delete(*self._tree_history.get_children())
        for entry in reversed(history):
            self._tree_history.insert(
                "",
                tk.END,
                values=(
                    entry.get("timestamp", "")[:16],
                    f"{entry['price']:.2f}",
                    entry.get("url", ""),
                ),
            )

    def _on_history_double_click(self, _event) -> None:
        sel = self._tree_history.selection()
        if not sel:
            return
        url = self._tree_history.item(sel[0], "values")[2]
        if url and url.startswith("http"):
            webbrowser.open(url)

    def _on_clear_alerts(self) -> None:
        self._notifier.clear_log()
        self._tree_alerts.delete(*self._tree_alerts.get_children())

    def _on_apply_interval(self) -> None:
        try:
            minutes = int(self._spin_interval.get())
        except ValueError:
            messagebox.showerror("Ungültig", "Bitte eine ganze Zahl eingeben.")
            return
        self._orch._interval = minutes * 60
        self._set_status(f"Intervall auf {minutes} Minuten gesetzt.")

    def _on_save_email_settings(self) -> None:
        """Persist e-mail settings and apply them to the NotifierAgent."""
        settings = self._storage.get_settings()
        settings.update(self._collect_email_form())
        self._storage.save_settings(settings)
        self._apply_email_to_notifier(settings)
        self._set_status("E-Mail Einstellungen gespeichert.")

    def _on_test_email(self) -> None:
        """Send a test e-mail using the current form values (without saving)."""
        cfg = self._collect_email_form()
        if not cfg.get("email_smtp_host") or not cfg.get("email_recipient"):
            messagebox.showwarning(
                "Fehlende Angaben", "Bitte SMTP Host und Empfänger-Adresse eingeben."
            )
            return
        # Temporarily apply form settings so the notifier can send the test mail.
        self._apply_email_to_notifier({**cfg, "email_enabled": True})
        try:
            self._notifier.send_test_email()
            messagebox.showinfo("Erfolg", "Test-E-Mail wurde erfolgreich gesendet.")
        except Exception as exc:
            messagebox.showerror("Fehler", f"E-Mail konnte nicht gesendet werden:\n{exc}")
        finally:
            # Restore whatever was previously saved so we don't accidentally keep
            # unsaved changes active after the test.
            self._apply_email_to_notifier(self._storage.get_settings())

    # ------------------------------------------------------------------
    # E-Mail helpers
    # ------------------------------------------------------------------

    def _collect_email_form(self) -> dict:
        """Read e-mail settings from the form widgets into a dict."""
        try:
            port = int(self._entry_smtp_port.get().strip() or "587")
        except ValueError:
            port = 587
        return {
            "email_enabled": self._var_email_enabled.get(),
            "email_smtp_host": self._entry_smtp_host.get().strip(),
            "email_smtp_port": port,
            "email_smtp_use_tls": self._var_smtp_tls.get(),
            "email_username": self._entry_email_user.get().strip(),
            "email_password": self._entry_email_pass.get(),
            "email_sender": self._entry_email_sender.get().strip(),
            "email_recipient": self._entry_email_recipient.get().strip(),
        }

    def _apply_email_to_notifier(self, settings: dict) -> None:
        """Push settings dict into the NotifierAgent."""
        if self._apply_email_settings is not None:
            self._apply_email_settings(self._notifier, settings)

    def _load_email_settings(self) -> None:
        """Populate e-mail form from persisted settings on startup."""
        settings = self._storage.get_settings()
        self._var_email_enabled.set(settings.get("email_enabled", False))
        self._entry_smtp_host.insert(0, settings.get("email_smtp_host", ""))
        self._entry_smtp_port.insert(0, str(settings.get("email_smtp_port", 587)))
        self._var_smtp_tls.set(settings.get("email_smtp_use_tls", True))
        self._entry_email_user.insert(0, settings.get("email_username", ""))
        self._entry_email_pass.insert(0, settings.get("email_password", ""))
        self._entry_email_sender.insert(0, settings.get("email_sender", ""))
        self._entry_email_recipient.insert(0, settings.get("email_recipient", ""))
        # Apply to notifier so alerts work immediately after restart
        self._apply_email_to_notifier(settings)

    # ------------------------------------------------------------------
    # Agent callbacks (called from background threads → schedule to main)
    # ------------------------------------------------------------------

    def _on_run_status(self, status) -> None:
        """Called by OrchestratorAgent after each cycle (may be in another thread)."""
        self._root.after(0, self._apply_run_status, status)

    def _apply_run_status(self, status) -> None:
        self._refresh_watchlist()
        msg = (
            f"Letzter Lauf: {status.finished_at[:16] if status.finished_at else '–'} | "
            f"{status.items_ok} ok, {status.items_failed} Fehler, "
            f"{status.alerts_fired} Alarm(e)"
        )
        self._set_status(msg)

    def _on_alert(self, alert) -> None:
        """Called by NotifierAgent when an alert fires (may be in another thread)."""
        self._root.after(0, self._append_alert, alert)

    def _append_alert(self, alert) -> None:
        self._tree_alerts.insert(
            "",
            0,
            values=(
                alert.timestamp[:16],
                alert.item_name,
                f"{alert.old_price:.2f}" if alert.old_price is not None else "–",
                f"{alert.new_price:.2f}",
                alert.reason,
            ),
        )

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_watchlist(self) -> None:
        items = self._storage.get_watchlist()

        # Update main table
        self._tree.delete(*self._tree.get_children())
        names = []
        for item in items:
            price_str = f"{item['last_price']:.2f} €" if item.get("last_price") is not None else "–"
            target_str = f"{item['target_price']:.2f} €" if item.get("target_price") is not None else "–"
            checked_str = (item.get("last_checked") or "–")[:16]
            self._tree.insert(
                "",
                tk.END,
                values=(item["name"], item["query"], price_str, target_str, checked_str),
                tags=(item["id"],),
            )
            names.append(item["name"])

        # Update history combobox
        self._combo_history_item["values"] = names

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)
