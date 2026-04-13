"""
ScraperAgent – Searches one or more shops and returns the cheapest result.

Responsibilities:
- Build search URLs for each requested shop
- Fetch the HTML and delegate parsing to shop-specific parsers
- Return structured result dicts (price, title, url, shop)
- Honour rate-limiting delays between requests
"""

import logging
import time
from typing import Optional
from urllib.parse import quote_plus

import requests

from config import (
    SHOP_SEARCH_URLS,
    SHOP_DISPLAY_NAMES,
    DEFAULT_SHOPS,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    REQUEST_DELAY,
)
from .shop_scrapers import SHOP_PARSERS

logger = logging.getLogger(__name__)


class ScraperResult:
    """Plain data holder for a single scrape result."""

    def __init__(
        self,
        item_id: str,
        query: str,
        price: Optional[float],
        title: str,
        url: str,
        shop: str = "",
        error: Optional[str] = None,
    ) -> None:
        self.item_id = item_id
        self.query = query
        self.price = price
        self.title = title
        self.url = url
        self.shop = shop                        # shop key, e.g. "amazon"
        self.shop_display = SHOP_DISPLAY_NAMES.get(shop, shop)
        self.error = error

    def ok(self) -> bool:
        return self.error is None and self.price is not None

    def __repr__(self) -> str:
        return (
            f"ScraperResult(item_id={self.item_id!r}, shop={self.shop!r}, "
            f"price={self.price}, title={self.title!r}, error={self.error!r})"
        )


class ScraperAgent:
    """Fetches and parses search result pages from one or more shops."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(REQUEST_HEADERS)
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_item(
        self,
        item_id: str,
        query: str,
        shops: Optional[list[str]] = None,
    ) -> ScraperResult:
        """
        Search *shops* for *query* and return the result with the lowest price.

        Args:
            item_id: ID of the watchlist item (passed through for correlation).
            query:   Search term.
            shops:   List of shop keys to search (defaults to DEFAULT_SHOPS).

        Returns:
            A ScraperResult with price/url/shop on success, or error set on failure.
        """
        if not shops:
            shops = DEFAULT_SHOPS

        best: Optional[ScraperResult] = None
        last_error: Optional[str] = None

        for shop_key in shops:
            result = self._scrape_one_shop(item_id, query, shop_key)
            if result.ok():
                if best is None or (result.price is not None and result.price < best.price):
                    best = result
            else:
                last_error = result.error

        if best is not None:
            return best

        return ScraperResult(
            item_id, query, None, "", "", error=last_error or "Price not found in any shop"
        )

    def scrape_all(self, items: list[dict]) -> list[ScraperResult]:
        """
        Scrape a list of watchlist items sequentially.

        Args:
            items: List of dicts with keys 'id', 'query', and optionally 'shops'.

        Returns:
            List of ScraperResults in the same order.
        """
        results = []
        for item in items:
            shops = item.get("shops") or DEFAULT_SHOPS
            result = self.scrape_item(item["id"], item["query"], shops)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Per-shop fetching
    # ------------------------------------------------------------------

    def _scrape_one_shop(
        self, item_id: str, query: str, shop_key: str
    ) -> ScraperResult:
        """Fetch and parse a single shop's search page."""
        url_template = SHOP_SEARCH_URLS.get(shop_key)
        if not url_template:
            return ScraperResult(
                item_id, query, None, "", "", shop=shop_key,
                error=f"Unknown shop key: {shop_key!r}"
            )

        url = url_template.format(query=quote_plus(query))
        logger.info("Scraping %s for '%s' → %s", shop_key, query, url)

        self._rate_limit()

        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("HTTP error [%s] for '%s': %s", shop_key, query, exc)
            return ScraperResult(
                item_id, query, None, "", url, shop=shop_key, error=str(exc)
            )

        parser = SHOP_PARSERS.get(shop_key)
        if parser is None:
            return ScraperResult(
                item_id, query, None, "", url, shop=shop_key,
                error=f"No parser for shop {shop_key!r}"
            )

        parsed = parser(response.text, url)
        if parsed:
            price, title, product_url = parsed
            return ScraperResult(item_id, query, price, title, product_url, shop=shop_key)

        logger.warning("No price found [%s] for '%s'.", shop_key, query)
        return ScraperResult(
            item_id, query, None, "", url, shop=shop_key,
            error="Price not found in page"
        )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Sleep if needed to honour REQUEST_DELAY between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.monotonic()

