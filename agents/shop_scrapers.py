"""
shop_scrapers.py – Shop-specific HTML parsers.

Each public ``parse_<shop>`` function receives:
    html         (str)  – raw HTML response text
    fallback_url (str)  – the search URL that was fetched (used when no
                           product URL can be extracted)

It returns either a tuple ``(price: float, title: str, url: str)`` for the
cheapest / first matching result, or ``None`` when nothing could be parsed.

A SHOP_PARSERS mapping ties shop keys (as defined in config.SHOP_SEARCH_URLS)
to their parser function.
"""

import json
import logging
import re
from typing import Callable, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helper – reused across parsers
# ---------------------------------------------------------------------------

_PRICE_PATTERNS = [
    r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*€",
    r"€\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))",
    r"(\d+[.,]\d{2})\s*€",
    r"€\s*(\d+[.,]\d{2})",
]


def _extract_price(text: str) -> Optional[float]:
    """Return the first Euro price found in *text*, or None."""
    for pattern in _PRICE_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return _to_float(m.group(1))
    return None


def _to_float(value: str) -> Optional[float]:
    """Normalise German / English decimal strings to float."""
    v = value.strip().replace("\u00a0", "")
    if "," in v and "." in v:
        if v.index(",") < v.index("."):
            v = v.replace(",", "")
        else:
            v = v.replace(".", "").replace(",", ".")
    elif "," in v:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def _parse_json_ld(soup: BeautifulSoup) -> Optional[tuple]:
    """Generic JSON-LD price extraction – shared across all shops."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
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
            price = _to_float(str(price_str))
            if price is not None:
                return price, name, url
    return None


# ---------------------------------------------------------------------------
# Idealo
# ---------------------------------------------------------------------------

def parse_idealo(html: str, fallback_url: str) -> Optional[tuple]:
    soup = BeautifulSoup(html, "html.parser")

    result = _parse_json_ld(soup)
    if result:
        return result

    # Offer-card heuristics
    cards = soup.select("[class*='offerList'], [class*='offer-'], [class*='sr-resultList']")
    if not cards:
        cards = soup.find_all(["article", "li"], limit=20)
    for card in cards:
        price = _extract_price(card.get_text(" ", strip=True))
        if price is None:
            continue
        title_tag = card.find(["h2", "h3", "h4", "a"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        link_tag = card.find("a", href=True)
        url = link_tag["href"] if link_tag else fallback_url
        if not url.startswith("http"):
            url = "https://www.idealo.de" + url
        return price, title, url

    # Final fallback
    price = _extract_price(soup.get_text(" ", strip=True))
    if price is not None:
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        return price, title, fallback_url
    return None


# ---------------------------------------------------------------------------
# Amazon.de
# ---------------------------------------------------------------------------

def parse_amazon(html: str, fallback_url: str) -> Optional[tuple]:
    soup = BeautifulSoup(html, "html.parser")

    result = _parse_json_ld(soup)
    if result:
        return result

    # Amazon search result cards contain span.a-price > span.a-offscreen
    # which holds the full price string like "29,99 €".
    for card in soup.select("div[data-component-type='s-search-result']"):
        price_tag = card.select_one("span.a-price > span.a-offscreen")
        if price_tag is None:
            continue
        price = _extract_price(price_tag.get_text())
        if price is None:
            continue
        title_tag = card.select_one("h2 span") or card.select_one("h2")
        title = title_tag.get_text(strip=True) if title_tag else ""
        link_tag = card.select_one("h2 a[href]")
        if link_tag:
            href = link_tag["href"]
            url = href if href.startswith("http") else "https://www.amazon.de" + href
        else:
            url = fallback_url
        return price, title, url

    # Fallback: generic price scan
    price = _extract_price(soup.get_text(" ", strip=True))
    if price is not None:
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        return price, title, fallback_url
    return None


# ---------------------------------------------------------------------------
# MediaMarkt.de  (Ceconomy / Next.js platform)
# ---------------------------------------------------------------------------

def _parse_ceconomy(html: str, fallback_url: str, base_url: str) -> Optional[tuple]:
    """Shared parser for MediaMarkt and Saturn (same technical platform)."""
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: JSON-LD
    result = _parse_json_ld(soup)
    if result:
        return result

    # Strategy 2: __NEXT_DATA__ embedded JSON
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            data = json.loads(next_data_tag.string)
            products = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("searchResult", {})
                    .get("products", [])
            )
            if not products:
                # Alternate path in page data
                products = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("productList", {})
                        .get("products", [])
                )
            for product in products:
                price_val = (
                    product.get("price", {}).get("final")
                    or product.get("price", {}).get("regular")
                )
                if price_val is None:
                    continue
                price = _to_float(str(price_val))
                if price is None:
                    continue
                title = product.get("name", "") or product.get("title", "")
                slug = product.get("slug") or product.get("url", "")
                url = (base_url + slug) if slug and not slug.startswith("http") else (slug or fallback_url)
                return price, title, url
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # Strategy 3: CSS selectors for price elements
    for card in soup.select("[data-test*='product'], article, [class*='product']"):
        price_text = card.get_text(" ", strip=True)
        price = _extract_price(price_text)
        if price is None:
            continue
        title_tag = card.find(["h2", "h3", "h4", "a"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        url = href if href.startswith("http") else (base_url + href if href else fallback_url)
        return price, title, url

    # Fallback
    price = _extract_price(soup.get_text(" ", strip=True))
    if price is not None:
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        return price, title, fallback_url
    return None


def parse_mediamarkt(html: str, fallback_url: str) -> Optional[tuple]:
    return _parse_ceconomy(html, fallback_url, "https://www.mediamarkt.de")


def parse_saturn(html: str, fallback_url: str) -> Optional[tuple]:
    return _parse_ceconomy(html, fallback_url, "https://www.saturn.de")


# ---------------------------------------------------------------------------
# Galaxus.de
# ---------------------------------------------------------------------------

def parse_galaxus(html: str, fallback_url: str) -> Optional[tuple]:
    soup = BeautifulSoup(html, "html.parser")

    result = _parse_json_ld(soup)
    if result:
        return result

    # Galaxus embeds product data in a <script id="__NEXT_DATA__"> tag as well
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            data = json.loads(next_data_tag.string)
            # Search results are usually in props.pageProps.searchResult.products
            products = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("searchResult", {})
                    .get("products", [])
            )
            for product in products:
                price_val = (
                    product.get("salesInformation", {}).get("currentPrice", {}).get("amountIncl")
                    or product.get("price")
                )
                if price_val is None:
                    continue
                price = _to_float(str(price_val))
                if price is None:
                    continue
                title = product.get("name", "") or product.get("nameSingular", "")
                slug = product.get("productUrl") or product.get("url", "")
                url = (
                    ("https://www.galaxus.de" + slug)
                    if slug and not slug.startswith("http")
                    else (slug or fallback_url)
                )
                return price, title, url
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # CSS fallback
    for card in soup.select("article, [class*='productTile'], [class*='product-']"):
        price = _extract_price(card.get_text(" ", strip=True))
        if price is None:
            continue
        title_tag = card.find(["h2", "h3", "a"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        url = href if href.startswith("http") else ("https://www.galaxus.de" + href if href else fallback_url)
        return price, title, url

    price = _extract_price(soup.get_text(" ", strip=True))
    if price is not None:
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        return price, title, fallback_url
    return None


# ---------------------------------------------------------------------------
# Alza.de
# ---------------------------------------------------------------------------

def parse_alza(html: str, fallback_url: str) -> Optional[tuple]:
    soup = BeautifulSoup(html, "html.parser")

    result = _parse_json_ld(soup)
    if result:
        return result

    # Alza uses a standard product listing; prices are in .price-box__price
    # or spans with class containing "bigPrice" / "price"
    for card in soup.select(".box, article, [class*='product']"):
        price_tag = card.select_one(
            ".price-box__price, [class*='bigPrice'], [class*='price-vatin']"
        )
        if price_tag is None:
            price_text = card.get_text(" ", strip=True)
        else:
            price_text = price_tag.get_text(" ", strip=True)
        price = _extract_price(price_text)
        if price is None:
            continue
        title_tag = card.select_one(
            "[class*='name'], [class*='title'], h2, h3, a"
        )
        title = title_tag.get_text(strip=True) if title_tag else ""
        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        url = href if href.startswith("http") else ("https://www.alza.de" + href if href else fallback_url)
        return price, title, url

    price = _extract_price(soup.get_text(" ", strip=True))
    if price is not None:
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        return price, title, fallback_url
    return None


# ---------------------------------------------------------------------------
# Otto.de
# ---------------------------------------------------------------------------

def parse_otto(html: str, fallback_url: str) -> Optional[tuple]:
    soup = BeautifulSoup(html, "html.parser")

    result = _parse_json_ld(soup)
    if result:
        return result

    # Otto embeds search results in a <script type="text/javascript"> block
    # as window.__INITIAL_STATE__ or similar.  Try a lightweight regex first.
    for script_tag in soup.find_all("script"):
        script_text = script_tag.string or ""
        if "initialState" not in script_text and "searchResult" not in script_text:
            continue
        # Look for a price JSON pattern like "price":{"regular":{"value":99.99}}
        m = re.search(r'"price"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', script_text)
        if m:
            price = _to_float(m.group(1))
            if price:
                # Try to grab a product name nearby
                nm = re.search(r'"(?:name|title)"\s*:\s*"([^"]+)"', script_text)
                title = nm.group(1) if nm else ""
                return price, title, fallback_url

    # CSS / article fallback
    for card in soup.select(
        "article, [class*='product'], li[class*='tile']"
    ):
        price = _extract_price(card.get_text(" ", strip=True))
        if price is None:
            continue
        title_tag = card.find(["h2", "h3", "a"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        url = href if href.startswith("http") else ("https://www.otto.de" + href if href else fallback_url)
        return price, title, url

    price = _extract_price(soup.get_text(" ", strip=True))
    if price is not None:
        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(strip=True) if title_tag else ""
        return price, title, fallback_url
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SHOP_PARSERS: dict[str, Callable] = {
    "idealo":     parse_idealo,
    "amazon":     parse_amazon,
    "mediamarkt": parse_mediamarkt,
    "saturn":     parse_saturn,
    "galaxus":    parse_galaxus,
    "alza":       parse_alza,
    "otto":       parse_otto,
}
