"""
NotifierAgent – Evaluates price results and fires alerts.

Responsibilities:
- Compare new price against target_price and alert_on_drop_pct thresholds
- Emit desktop notifications (via plyer) when thresholds are breached
- Send e-mail notifications (via smtplib) when e-mail alerting is configured
- Keep a callback registry so the GUI can subscribe to alerts
- Log all alerts to a structured list for display in the GUI
"""

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from typing import Callable, Optional

from config import DEFAULT_PRICE_DROP_PERCENT

logger = logging.getLogger(__name__)


class Alert:
    """Represents a single triggered alert."""

    def __init__(
        self,
        item_id: str,
        item_name: str,
        old_price: Optional[float],
        new_price: float,
        url: str,
        reason: str,
    ) -> None:
        self.item_id = item_id
        self.item_name = item_name
        self.old_price = old_price
        self.new_price = new_price
        self.url = url
        self.reason = reason
        self.timestamp = datetime.now().isoformat()

    def summary(self) -> str:
        old = f"{self.old_price:.2f} €" if self.old_price is not None else "–"
        return (
            f"[{self.timestamp[:16]}] {self.item_name}: "
            f"{old} → {self.new_price:.2f} € ({self.reason})"
        )


class NotifierAgent:
    """Checks price results and dispatches alerts."""

    def __init__(self) -> None:
        self._alert_log: list[Alert] = []
        self._callbacks: list[Callable[[Alert], None]] = []
        self._desktop_available = self._check_desktop()

        # E-mail configuration (set via configure_email)
        self._email_enabled: bool = False
        self._email_smtp_host: str = ""
        self._email_smtp_port: int = 587
        self._email_smtp_use_tls: bool = True
        self._email_username: str = ""
        self._email_password: str = ""
        self._email_sender: str = ""
        self._email_recipient: str = ""

    # ------------------------------------------------------------------
    # E-mail configuration
    # ------------------------------------------------------------------

    def configure_email(
        self,
        *,
        enabled: bool,
        smtp_host: str,
        smtp_port: int,
        use_tls: bool,
        username: str,
        password: str,
        sender: str,
        recipient: str,
    ) -> None:
        """Update e-mail settings at runtime (called from GUI settings)."""
        self._email_enabled = enabled
        self._email_smtp_host = smtp_host
        self._email_smtp_port = smtp_port
        self._email_smtp_use_tls = use_tls
        self._email_username = username
        self._email_password = password
        self._email_sender = sender
        self._email_recipient = recipient

    # ------------------------------------------------------------------
    # Subscription API (used by GUI)
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[Alert], None]) -> None:
        """Register a callback that is called whenever an alert fires."""
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[Alert], None]) -> None:
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate(self, item: dict, new_price: float, url: str) -> Optional[Alert]:
        """
        Decide whether *new_price* for *item* triggers an alert.

        Args:
            item:      Watchlist item dict from StorageAgent.
            new_price: Freshly scraped price in euros.
            url:       Source URL of the best offer.

        Returns:
            An Alert if a threshold was breached, else None.
        """
        old_price: Optional[float] = item.get("last_price")
        alert: Optional[Alert] = None

        # 1. Absolute target price
        target = item.get("target_price")
        if target is not None and new_price <= target:
            reason = f"Zielpreis {target:.2f} € erreicht"
            alert = self._make_alert(item, old_price, new_price, url, reason)

        # 2. Percentage drop from last recorded price
        if alert is None and old_price is not None and old_price > 0:
            drop_pct = item.get("alert_on_drop_pct") or DEFAULT_PRICE_DROP_PERCENT
            actual_drop_pct = (old_price - new_price) / old_price * 100
            if actual_drop_pct >= drop_pct:
                reason = f"Preisfall {actual_drop_pct:.1f} % (≥ {drop_pct:.1f} %)"
                alert = self._make_alert(item, old_price, new_price, url, reason)

        if alert:
            self._dispatch(alert)

        return alert

    def evaluate_all(
        self, items: list[dict], results: list  # list[ScraperResult]
    ) -> list[Alert]:
        """
        Evaluate a batch of scraper results against their watchlist items.

        Args:
            items:   Watchlist items (same order as *results*).
            results: ScraperResult objects from ScraperAgent.

        Returns:
            List of triggered alerts.
        """
        from .scraper_agent import ScraperResult  # local import to avoid circular

        alerts = []
        item_map = {item["id"]: item for item in items}

        for result in results:
            if not isinstance(result, ScraperResult) or not result.ok():
                continue
            item = item_map.get(result.item_id)
            if item is None:
                continue
            alert = self.evaluate(item, result.price, result.url)
            if alert:
                alerts.append(alert)

        return alerts

    # ------------------------------------------------------------------
    # Alert log (read by GUI)
    # ------------------------------------------------------------------

    def get_alert_log(self) -> list[Alert]:
        """Return all alerts in chronological order."""
        return list(self._alert_log)

    def clear_log(self) -> None:
        self._alert_log.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_alert(
        self,
        item: dict,
        old_price: Optional[float],
        new_price: float,
        url: str,
        reason: str,
    ) -> Alert:
        alert = Alert(
            item_id=item["id"],
            item_name=item["name"],
            old_price=old_price,
            new_price=new_price,
            url=url,
            reason=reason,
        )
        self._alert_log.append(alert)
        logger.info("ALERT: %s", alert.summary())
        return alert

    def _dispatch(self, alert: Alert) -> None:
        """Send desktop notification, e-mail, and call registered GUI callbacks."""
        self._desktop_notify(alert)
        self._email_notify(alert)
        for cb in list(self._callbacks):
            try:
                cb(alert)
            except Exception as exc:
                logger.error("Alert callback raised: %s", exc)

    def _desktop_notify(self, alert: Alert) -> None:
        if not self._desktop_available:
            return
        try:
            from plyer import notification

            notification.notify(
                title=f"Preisalarm: {alert.item_name}",
                message=f"{alert.new_price:.2f} € – {alert.reason}",
                app_name="Idealo Price Tracker",
                timeout=8,
            )
        except Exception as exc:
            logger.debug("Desktop notification failed: %s", exc)

    def _email_notify(self, alert: Alert) -> None:
        """Send an e-mail alert via SMTP when e-mail alerting is enabled."""
        if not self._email_enabled:
            return
        if not self._email_smtp_host or not self._email_recipient:
            logger.warning("E-Mail alerting enabled but SMTP host or recipient is missing.")
            return

        old = f"{alert.old_price:.2f} €" if alert.old_price is not None else "–"
        subject = f"Preisalarm: {alert.item_name} – {alert.new_price:.2f} €"
        body = (
            f"Preisalarm für: {alert.item_name}\n\n"
            f"Alter Preis : {old}\n"
            f"Neuer Preis : {alert.new_price:.2f} €\n"
            f"Grund       : {alert.reason}\n"
            f"Zeitpunkt   : {alert.timestamp[:16]}\n"
            f"URL         : {alert.url}\n"
        )
        sender = self._email_sender or self._email_username
        try:
            self._smtp_send(
                self._email_smtp_host,
                self._email_smtp_port,
                self._email_smtp_use_tls,
                self._email_username,
                self._email_password,
                sender,
                self._email_recipient,
                subject,
                body,
            )
            logger.info("E-Mail alert sent to %s for '%s'.", self._email_recipient, alert.item_name)
        except Exception as exc:
            logger.error("Failed to send e-mail alert: %s", exc)

    def send_test_email(self) -> None:
        """
        Send a test e-mail using the current configuration.

        Raises an exception on failure so callers can display an error message.
        """
        if not self._email_smtp_host or not self._email_recipient:
            raise ValueError("SMTP Host und Empfänger müssen konfiguriert sein.")
        sender = self._email_sender or self._email_username
        subject = "Idealo Price Tracker – Test-E-Mail"
        body = "Dies ist eine Test-E-Mail vom Idealo Price Tracker."
        self._smtp_send(
            self._email_smtp_host,
            self._email_smtp_port,
            self._email_smtp_use_tls,
            self._email_username,
            self._email_password,
            sender,
            self._email_recipient,
            subject,
            body,
        )

    @staticmethod
    def _smtp_send(
        host: str,
        port: int,
        use_tls: bool,
        username: str,
        password: str,
        sender: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        """Build and deliver one e-mail via SMTP."""
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls(context=context)
                if username:
                    smtp.login(username, password)
                smtp.sendmail(sender, recipient, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.sendmail(sender, recipient, msg.as_string())

    @staticmethod
    def _check_desktop() -> bool:
        try:
            import plyer  # noqa: F401
            return True
        except ImportError:
            logger.debug("plyer not installed – desktop notifications disabled.")
            return False

