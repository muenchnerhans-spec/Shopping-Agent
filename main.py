"""
Idealo Price Tracker – Entry point.

Usage:
    python main.py          # open GUI (default)
    python main.py --headless  # run one scrape cycle without GUI, then exit
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _apply_email_settings(notifier, settings: dict) -> None:
    """Apply e-mail configuration from a settings dict to the notifier."""
    import config

    notifier.configure_email(
        enabled=settings.get("email_enabled", config.EMAIL_ENABLED),
        smtp_host=settings.get("email_smtp_host", config.EMAIL_SMTP_HOST),
        smtp_port=int(settings.get("email_smtp_port", config.EMAIL_SMTP_PORT)),
        use_tls=settings.get("email_smtp_use_tls", config.EMAIL_SMTP_USE_TLS),
        username=settings.get("email_username", config.EMAIL_USERNAME),
        password=settings.get("email_password", config.EMAIL_PASSWORD),
        sender=settings.get("email_sender", config.EMAIL_SENDER),
        recipient=settings.get("email_recipient", config.EMAIL_RECIPIENT),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Idealo Price Tracker")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run a single scrape cycle without the GUI and exit.",
    )
    args = parser.parse_args()

    # Instantiate agents
    from agents import StorageAgent, ScraperAgent, NotifierAgent, OrchestratorAgent

    storage = StorageAgent()
    scraper = ScraperAgent()
    notifier = NotifierAgent()
    orchestrator = OrchestratorAgent(storage, scraper, notifier)

    # Apply persisted e-mail settings (if any)
    _apply_email_settings(notifier, storage.get_settings())

    if args.headless:
        logger.info("Running in headless mode.")
        status = orchestrator.run_now()
        logger.info("Done: %s", status.to_dict())
        sys.exit(0)

    # GUI mode
    from gui import MainWindow

    window = MainWindow(orchestrator, storage, notifier, apply_email_settings=_apply_email_settings)
    window.run()


if __name__ == "__main__":
    main()
