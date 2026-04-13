"""
NotifierAgent – Evaluates price results and fires alerts.

Responsibilities:
- Compare new price against target_price and alert_on_drop_pct thresholds
- Emit desktop notifications (via plyer) when thresholds are breached
- Keep a callback registry so the GUI can subscribe to alerts
- Log all alerts to a structured list for display in the GUI
"""

import logging
from datetime import datetime
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
        """Send desktop notification and call registered GUI callbacks."""
        self._desktop_notify(alert)
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

    @staticmethod
    def _check_desktop() -> bool:
        try:
            import plyer  # noqa: F401
            return True
        except ImportError:
            logger.debug("plyer not installed – desktop notifications disabled.")
            return False
