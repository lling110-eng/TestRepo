"""
Entry point for the Outlook → NetSuite email sync.

Usage:
    # Run once immediately:
    python run.py --once

    # Run on a recurring schedule (default: every 5 minutes):
    python run.py

    # Override poll interval:
    POLL_INTERVAL_MINUTES=10 python run.py
"""

import argparse
import logging
import sys
import time

import schedule

from outlook_netsuite.config import Config
from outlook_netsuite.sync import OutlookNetSuiteSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Sync Outlook sent emails to NetSuite")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync pass and exit (useful for cron jobs)",
    )
    args = parser.parse_args()

    try:
        config = Config()
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    syncer = OutlookNetSuiteSync(config)

    def run_sync():
        try:
            stats = syncer.run_once()
            logger.info(
                "Sync result — fetched: %d | posted: %d | skipped: %d | errors: %d",
                stats["fetched"],
                stats["posted"],
                stats["skipped"],
                stats["errors"],
            )
        except Exception as exc:
            logger.error("Sync failed: %s", exc, exc_info=True)

    if args.once:
        run_sync()
        return

    interval = config.POLL_INTERVAL_MINUTES
    logger.info("Starting scheduler — polling every %d minute(s). Press Ctrl+C to stop.", interval)
    schedule.every(interval).minutes.do(run_sync)

    # Run immediately on startup, then follow the schedule
    run_sync()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
