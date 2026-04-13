"""
OrchestratorAgent – Coordinates the periodic scrape-evaluate-store cycle.

Responsibilities:
- Run a background scheduler that triggers scrapes every N minutes
- Delegate fetching to ScraperAgent, evaluation to NotifierAgent,
  and persistence to StorageAgent
- Emit status events so the GUI can display live progress
- Expose start / stop / run_now controls
"""

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

from config import SCRAPE_INTERVAL_MINUTES
from .scraper_agent import ScraperAgent
from .storage_agent import StorageAgent
from .notifier_agent import NotifierAgent, Alert

logger = logging.getLogger(__name__)


class RunStatus:
    """Snapshot of a single orchestration run."""

    def __init__(self) -> None:
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.items_checked: int = 0
        self.items_ok: int = 0
        self.items_failed: int = 0
        self.alerts_fired: int = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "items_checked": self.items_checked,
            "items_ok": self.items_ok,
            "items_failed": self.items_failed,
            "alerts_fired": self.alerts_fired,
            "errors": list(self.errors),
        }


class OrchestratorAgent:
    """Manages the scraping lifecycle and coordinates all sub-agents."""

    def __init__(
        self,
        storage: StorageAgent,
        scraper: ScraperAgent,
        notifier: NotifierAgent,
        interval_minutes: int = SCRAPE_INTERVAL_MINUTES,
    ) -> None:
        self._storage = storage
        self._scraper = scraper
        self._notifier = notifier
        self._interval = interval_minutes * 60  # convert to seconds

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        self._last_status: Optional[RunStatus] = None
        self._status_callbacks: list[Callable[[RunStatus], None]] = []

    # ------------------------------------------------------------------
    # Lifecycle controls (called from GUI or main.py)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler thread."""
        if self._running:
            logger.warning("OrchestratorAgent is already running.")
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._scheduler_loop, name="OrchestratorThread", daemon=True
        )
        self._thread.start()
        logger.info(
            "OrchestratorAgent started (interval=%d min).",
            self._interval // 60,
        )

    def stop(self) -> None:
        """Signal the scheduler thread to stop and wait for it."""
        if not self._running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._running = False
        logger.info("OrchestratorAgent stopped.")

    def run_now(self) -> RunStatus:
        """Trigger a single scrape cycle immediately (blocking, safe to call from GUI)."""
        return self._run_cycle()

    def run_now_async(self) -> None:
        """Trigger a single scrape cycle in a background thread (non-blocking)."""
        t = threading.Thread(target=self._run_cycle, name="ImmediateRun", daemon=True)
        t.start()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_status(self) -> Optional[RunStatus]:
        return self._last_status

    # ------------------------------------------------------------------
    # Status subscription (GUI hooks in here)
    # ------------------------------------------------------------------

    def subscribe_status(self, callback: Callable[[RunStatus], None]) -> None:
        self._status_callbacks.append(callback)

    def unsubscribe_status(self, callback: Callable[[RunStatus], None]) -> None:
        self._status_callbacks = [cb for cb in self._status_callbacks if cb is not callback]

    # ------------------------------------------------------------------
    # Internal scheduler
    # ------------------------------------------------------------------

    def _scheduler_loop(self) -> None:
        """Main loop: run cycle, then sleep until next interval."""
        while not self._stop_event.is_set():
            self._run_cycle()
            # Sleep in small increments so we react quickly to stop()
            remaining = self._interval
            while remaining > 0 and not self._stop_event.is_set():
                sleep_chunk = min(5, remaining)
                self._stop_event.wait(sleep_chunk)
                remaining -= sleep_chunk

    def _run_cycle(self) -> RunStatus:
        """Execute one full scrape-evaluate-persist cycle."""
        status = RunStatus()
        status.started_at = datetime.now().isoformat()
        logger.info("--- Orchestrator: starting scrape cycle ---")

        watchlist = self._storage.get_watchlist()
        if not watchlist:
            logger.info("Watchlist is empty, nothing to scrape.")
            status.finished_at = datetime.now().isoformat()
            self._last_status = status
            self._emit_status(status)
            return status

        status.items_checked = len(watchlist)

        # Scrape
        results = self._scraper.scrape_all(watchlist)

        # Persist prices & evaluate alerts
        alerts: list[Alert] = []
        for result in results:
            if result.ok():
                status.items_ok += 1
                self._storage.append_price(result.item_id, result.price, result.url, result.shop)
                item = self._storage.get_item(result.item_id)
                if item:
                    alert = self._notifier.evaluate(item, result.price, result.url)
                    if alert:
                        alerts.append(alert)
            else:
                status.items_failed += 1
                status.errors.append(
                    f"{result.query}: {result.error}"
                )
                logger.warning("Scrape failed for '%s': %s", result.query, result.error)

        status.alerts_fired = len(alerts)
        status.finished_at = datetime.now().isoformat()
        self._last_status = status

        logger.info(
            "--- Cycle done: %d ok, %d failed, %d alerts ---",
            status.items_ok,
            status.items_failed,
            status.alerts_fired,
        )

        self._emit_status(status)
        return status

    def _emit_status(self, status: RunStatus) -> None:
        for cb in list(self._status_callbacks):
            try:
                cb(status)
            except Exception as exc:
                logger.error("Status callback raised: %s", exc)
