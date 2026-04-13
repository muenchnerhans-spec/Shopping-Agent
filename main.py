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

    if args.headless:
        logger.info("Running in headless mode.")
        status = orchestrator.run_now()
        logger.info("Done: %s", status.to_dict())
        sys.exit(0)

    # GUI mode
    from gui import MainWindow

    window = MainWindow(orchestrator, storage, notifier)
    window.run()


if __name__ == "__main__":
    main()
