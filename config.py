"""
Central configuration for the Idealo Price Tracker.
"""

# Scheduling
SCRAPE_INTERVAL_MINUTES = 60  # How often to check prices

# Idealo base URL
IDEALO_BASE_URL = "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html"
IDEALO_SEARCH_URL = "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={query}"

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
SETTINGS_FILE = "data/settings.json"

# Notification thresholds
DEFAULT_PRICE_DROP_PERCENT = 5.0  # alert if price drops by this % or more

# E-Mail notifications (defaults; overridden at runtime via settings file)
EMAIL_ENABLED = False
EMAIL_SMTP_HOST = ""
EMAIL_SMTP_PORT = 587
EMAIL_SMTP_USE_TLS = True
EMAIL_USERNAME = ""
EMAIL_PASSWORD = ""
EMAIL_SENDER = ""
EMAIL_RECIPIENT = ""
