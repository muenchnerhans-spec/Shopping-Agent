"""
ScraperAgent – Searches idealo.de and extracts the lowest available price.

Responsibilities:
- Build the idealo search URL from a query string
- Fetch the HTML and parse the cheapest offer
- Return structured result dicts (price, title, url)
- Honour rate-limiting delays between requests
"""

import logging
import re
import time
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config import (
    IDEALO_SEARCH_URL,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    REQUEST_DELAY,
)

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
        error: Optional[str] = None,
    ) -> None:
        self.item_id = item_id
        self.query = query
        self.price = price
        self.title = title
        self.url = url
        self.error = error

    def ok(self) -> bool:
        return self.error is None and self.price is not None

    def __repr__(self) -> str:
        return (
            f"ScraperResult(item_id={self.item_id!r}, price={self.price}, "
            f"title={self.title!r}, error={self.error!r})"
        )


class ScraperAgent:
    """Fetches and parses idealo search result pages."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(REQUEST_HEADERS)
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_item(self, item_id: str, query: str) -> ScraperResult:
        """
        Search idealo for *query* and return the cheapest result.

        Args:
            item_id: ID of the watchlist item (passed through for correlation).
            query:   Search term.

        Returns:
            A ScraperResult with price/url on success, or error set on failure.
        """
        url = IDEALO_SEARCH_URL.format(query=quote_plus(query))
        logger.info("Scraping idealo for '%s' → %s", query, url)

        self._rate_limit()

        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("HTTP error for '%s': %s", query, exc)
            return ScraperResult(item_id, query, None, "", url, error=str(exc))

        return self._parse_response(item_id, query, response.text, url)

    def scrape_all(self, items: list[dict]) -> list[ScraperResult]:
        """
        Scrape a list of watchlist items sequentially.

        Args:
            items: List of dicts with keys 'id' and 'query'.

        Returns:
            List of ScraperResults in the same order.
        """
        results = []
        for item in items:
            result = self.scrape_item(item["id"], item["query"])
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self, item_id: str, query: str, html: str, source_url: str
    ) -> ScraperResult:
        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: structured JSON-LD price data
        result = self._parse_json_ld(soup)
        if result:
            price, title, url = result
            return ScraperResult(item_id, query, price, title, url or source_url)

        # Strategy 2: price from offer cards (idealo class names)
        result = self._parse_offer_cards(soup, source_url)
        if result:
            price, title, url = result
            return ScraperResult(item_id, query, price, title, url)

        # Strategy 3: fallback – scan all text for price-like patterns
        result = self._parse_price_fallback(soup, source_url)
        if result:
            price, title, url = result
            return ScraperResult(item_id, query, price, title, url)

        logger.warning("No price found for '%s'.", query)
        return ScraperResult(
            item_id, query, None, "", source_url, error="Price not found in page"
        )

    @staticmethod
    def _parse_json_ld(soup: BeautifulSoup) -> Optional[tuple]:
        """Try to extract price from JSON-LD <script> blocks."""
        import json as _json

        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(tag.string or "")
            except (_json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, list):
                data = data[0] if data else {}

            offers = data.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            price_str = offers.get("price") or data.get("price")
            url = offers.get("url") or data.get("url", "")
            name = data.get("name", "")

            if price_str:
                price = ScraperAgent._to_float(str(price_str))
                if price is not None:
                    return price, name, url
        return None

    @staticmethod
    def _parse_offer_cards(soup: BeautifulSoup, fallback_url: str) -> Optional[tuple]:
        """Parse idealo offer card elements (class-name heuristics)."""
        # idealo uses obfuscated class names that change; look for price patterns
        # near product list items.
        cards = soup.select(
            "[class*='offerList'], [class*='offer-'], [class*='sr-resultList']"
        )
        if not cards:
            # Try any article or li that contains a price-like text
            cards = soup.find_all(["article", "li"], limit=20)

        for card in cards:
            price_text = card.get_text(" ", strip=True)
            price = ScraperAgent._extract_price_from_text(price_text)
            if price is None:
                continue
            title_tag = card.find(["h2", "h3", "h4", "a"])
            title = title_tag.get_text(strip=True) if title_tag else ""
            link_tag = card.find("a", href=True)
            url = link_tag["href"] if link_tag else fallback_url
            if not url.startswith("http"):
                url = "https://www.idealo.de" + url
            return price, title, url
        return None

    @staticmethod
    def _parse_price_fallback(soup: BeautifulSoup, fallback_url: str) -> Optional[tuple]:
        """Last-resort: grab the first price-like string anywhere on the page."""
        text = soup.get_text(" ", strip=True)
        price = ScraperAgent._extract_price_from_text(text)
        if price is not None:
            title_tag = soup.find(["h1", "h2"])
            title = title_tag.get_text(strip=True) if title_tag else ""
            return price, title, fallback_url
        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Sleep if needed to honour REQUEST_DELAY between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.monotonic()

    @staticmethod
    def _extract_price_from_text(text: str) -> Optional[float]:
        """Find the first Euro-price pattern in arbitrary text."""
        # Matches: 1.234,56 €  |  €1,234.56  |  1234,56€  |  € 12.99
        patterns = [
            r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*€",
            r"€\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))",
            r"(\d+[.,]\d{2})\s*€",
            r"€\s*(\d+[.,]\d{2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return ScraperAgent._to_float(match.group(1))
        return None

    @staticmethod
    def _to_float(value: str) -> Optional[float]:
        """Normalize German/English decimal strings to float."""
        if not value:
            return None
        # Remove thousands separators and normalise decimal separator
        v = value.strip().replace("\u00a0", "")
        if "," in v and "." in v:
            if v.index(",") < v.index("."):
                # Format: 1,234.56
                v = v.replace(",", "")
            else:
                # Format: 1.234,56
                v = v.replace(".", "").replace(",", ".")
        elif "," in v:
            v = v.replace(",", ".")
        try:
            return float(v)
        except ValueError:
            return None
