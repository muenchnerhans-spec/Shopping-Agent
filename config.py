"""
Central configuration for the Shopping Agent Price Tracker.
"""

# Scheduling
SCRAPE_INTERVAL_MINUTES = 60  # How often to check prices

# Idealo base URL (kept for backwards-compat imports)
IDEALO_BASE_URL = "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html"
IDEALO_SEARCH_URL = "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={query}"

# Search URLs per shop – use {query} as placeholder for quote_plus(query)
SHOP_SEARCH_URLS: dict[str, str] = {
    "idealo":     "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={query}",
    "amazon":     "https://www.amazon.de/s?k={query}&language=de_DE",
    "mediamarkt": "https://www.mediamarkt.de/de/search.html?query={query}",
    "saturn":     "https://www.saturn.de/de/search.html?query={query}",
    "galaxus":    "https://www.galaxus.de/search?q={query}",
    "alza":       "https://www.alza.de/search.htm?exps={query}",
    "otto":       "https://www.otto.de/suche/{query}/",
}

# Human-readable display names for each shop key
SHOP_DISPLAY_NAMES: dict[str, str] = {
    "idealo":     "Idealo",
    "amazon":     "Amazon",
    "mediamarkt": "MediaMarkt",
    "saturn":     "Saturn",
    "galaxus":    "Galaxus",
    "alza":       "Alza",
    "otto":       "Otto",
}

# Shops enabled by default when a new item is added
DEFAULT_SHOPS: list[str] = list(SHOP_SEARCH_URLS.keys())

# HTTP request settings
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
REQUEST_TIMEOUT = 15  # seconds
REQUEST_DELAY = 2.0   # seconds between requests (be polite)

# Storage
DATA_DIR = "data"
WATCHLIST_FILE = "data/watchlist.json"
PRICE_HISTORY_FILE = "data/price_history.json"

# Notification thresholds
DEFAULT_PRICE_DROP_PERCENT = 5.0  # alert if price drops by this % or more
