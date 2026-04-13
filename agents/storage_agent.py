"""
StorageAgent – Manages the watchlist and price history on disk.

Responsibilities:
- Load / save the watchlist (items the user wants to track)
- Append new price snapshots to the price history
- Provide query methods for the GUI and OrchestratorAgent
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from config import WATCHLIST_FILE, PRICE_HISTORY_FILE, DATA_DIR

logger = logging.getLogger(__name__)


class StorageAgent:
    """Persistent storage for watchlist items and their price history."""

    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self._watchlist: dict[str, dict] = {}
        self._price_history: dict[str, list[dict]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load watchlist and price history from disk."""
        self._watchlist = self._read_json(WATCHLIST_FILE, default={})
        self._price_history = self._read_json(PRICE_HISTORY_FILE, default={})
        logger.debug(
            "StorageAgent loaded %d items, %d history entries.",
            len(self._watchlist),
            len(self._price_history),
        )

    def _save_watchlist(self) -> None:
        self._write_json(WATCHLIST_FILE, self._watchlist)

    def _save_history(self) -> None:
        self._write_json(PRICE_HISTORY_FILE, self._price_history)

    @staticmethod
    def _read_json(path: str, default) -> dict | list:
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read %s: %s – starting fresh.", path, exc)
            return default

    @staticmethod
    def _write_json(path: str, data) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.error("Could not write %s: %s", path, exc)

    # ------------------------------------------------------------------
    # Watchlist API
    # ------------------------------------------------------------------

    def get_watchlist(self) -> list[dict]:
        """Return all watched items as a list of dicts."""
        return list(self._watchlist.values())

    def get_item(self, item_id: str) -> Optional[dict]:
        return self._watchlist.get(item_id)

    def add_item(
        self,
        name: str,
        query: str,
        target_price: Optional[float] = None,
        alert_on_drop_pct: Optional[float] = None,
        shops: Optional[list] = None,
    ) -> dict:
        """
        Add a new item to the watchlist.

        Args:
            name:              Human-readable label.
            query:             Search string used on the selected shops.
            target_price:      Optional absolute price threshold for alerts.
            alert_on_drop_pct: Alert when price drops by this % from the reference price.
            shops:             List of shop keys to search (None → all shops).

        Returns:
            The newly created item dict.
        """
        from config import DEFAULT_SHOPS
        item_id = self._generate_id(name)
        item = {
            "id": item_id,
            "name": name,
            "query": query,
            "shops": shops if shops is not None else list(DEFAULT_SHOPS),
            "target_price": target_price,
            "alert_on_drop_pct": alert_on_drop_pct,
            "last_price": None,
            "last_shop": None,
            "last_checked": None,
            "added_at": datetime.now().isoformat(),
        }
        self._watchlist[item_id] = item
        self._save_watchlist()
        logger.info("Added item '%s' (id=%s).", name, item_id)
        return item

    def update_item(self, item_id: str, **kwargs) -> bool:
        """Update editable fields of an existing item."""
        if item_id not in self._watchlist:
            logger.warning("update_item: unknown id %s", item_id)
            return False
        allowed = {"name", "query", "shops", "target_price", "alert_on_drop_pct"}
        for key, value in kwargs.items():
            if key in allowed:
                self._watchlist[item_id][key] = value
        self._save_watchlist()
        return True

    def remove_item(self, item_id: str) -> bool:
        """Remove an item from the watchlist (history is kept)."""
        if item_id not in self._watchlist:
            return False
        del self._watchlist[item_id]
        self._save_watchlist()
        logger.info("Removed item %s.", item_id)
        return True

    def set_last_price(self, item_id: str, price: float, shop: str = "") -> None:
        """Update the cached last-seen price on an item."""
        if item_id in self._watchlist:
            self._watchlist[item_id]["last_price"] = price
            self._watchlist[item_id]["last_shop"] = shop
            self._watchlist[item_id]["last_checked"] = datetime.now().isoformat()
            self._save_watchlist()

    # ------------------------------------------------------------------
    # Price history API
    # ------------------------------------------------------------------

    def append_price(self, item_id: str, price: float, url: str = "", shop: str = "") -> dict:
        """
        Append a price snapshot for an item.

        Returns the snapshot dict that was stored.
        """
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "price": price,
            "url": url,
            "shop": shop,
        }
        if item_id not in self._price_history:
            self._price_history[item_id] = []
        self._price_history[item_id].append(snapshot)
        self._save_history()
        self.set_last_price(item_id, price, shop)
        return snapshot

    def get_history(self, item_id: str) -> list[dict]:
        """Return full price history for an item, oldest first."""
        return list(self._price_history.get(item_id, []))

    def get_latest_snapshot(self, item_id: str) -> Optional[dict]:
        history = self._price_history.get(item_id, [])
        return history[-1] if history else None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id(name: str) -> str:
        """Create a short filesystem-safe ID from a name."""
        base = "".join(ch if ch.isalnum() else "_" for ch in name.lower())[:24]
        suffix = datetime.now().strftime("%Y%m%d%H%M%S%f")[-6:]
        return f"{base}_{suffix}"
