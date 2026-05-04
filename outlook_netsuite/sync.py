"""
Sync orchestrator — ties Outlook and NetSuite together.

For each sent email:
  1. Extract all recipient email addresses.
  2. For each recipient, look up a matching NetSuite customer by email.
  3. If found, post the email as a Message record on the customer's
     Communication tab.
  4. Persist the latest processed sentDateTime so the next run does not
     reprocess the same emails.
"""

import json
import logging
from datetime import datetime, timedelta, timezone  # timedelta used for watermark advance
from pathlib import Path

from .config import Config
from .netsuite_client import NetSuiteClient
from .outlook_client import OutlookClient

logger = logging.getLogger(__name__)


class SyncState:
    """Persists the last-processed email timestamp across runs."""

    def __init__(self, path: str):
        self._path = Path(path)

    def load(self) -> datetime:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                return datetime.fromisoformat(data["last_synced_at"])
            except Exception as exc:
                logger.warning("Could not read sync state (%s); starting from now.", exc)
        # No prior state — only process emails going forward from this moment
        return datetime.now(timezone.utc)

    def save(self, last_synced_at: datetime) -> None:
        self._path.write_text(json.dumps({"last_synced_at": last_synced_at.isoformat()}))


class OutlookNetSuiteSync:
    def __init__(self, config: Config):
        self._config = config
        self._outlook = OutlookClient(config)
        self._netsuite = NetSuiteClient(config)
        self._state = SyncState(config.SYNC_STATE_FILE)
        # Cache customer lookups within a run to avoid repeated API calls
        self._customer_cache: dict[str, dict | None] = {}

    def run_once(self) -> dict:
        """
        Fetch new sent emails since the last sync and post them to NetSuite.
        Returns a summary dict.
        """
        since = self._state.load()
        logger.info("Syncing sent emails since %s", since.isoformat())

        emails = self._outlook.get_sent_emails_since(since)
        logger.info("Fetched %d sent email(s) from Outlook", len(emails))

        stats = {"fetched": len(emails), "posted": 0, "skipped": 0, "errors": 0}
        latest_sent_at = since

        for email in emails:
            sent_at = datetime.fromisoformat(
                email["sentDateTime"].replace("Z", "+00:00")
            )
            if sent_at > latest_sent_at:
                latest_sent_at = sent_at

            try:
                posted = self._process_email(email, sent_at)
                if posted:
                    stats["posted"] += posted
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                logger.error("Error processing email '%s': %s", email.get("subject"), exc)
                stats["errors"] += 1

        # Advance the watermark by 1 second to exclude the last email next run
        self._state.save(latest_sent_at + timedelta(seconds=1))
        logger.info("Sync complete: %s", stats)
        return stats

    def _process_email(self, email: dict, sent_at: datetime) -> int:
        """
        Process a single email. Returns the number of NetSuite messages posted.
        """
        subject = email.get("subject", "(no subject)")
        body = self._outlook.get_body_text(email)
        sender_email = (
            email.get("sender", {})
            .get("emailAddress", {})
            .get("address", self._config.OUTLOOK_USER_EMAIL)
        )
        recipients = self._outlook.extract_recipients(email)

        if not recipients:
            logger.debug("Email '%s' has no addressable recipients — skipping.", subject)
            return 0

        posted = 0
        for recipient_email in recipients:
            customer = self._lookup_customer(recipient_email)
            if customer is None:
                logger.debug(
                    "No NetSuite customer found for %s — skipping.", recipient_email
                )
                continue

            self._netsuite.post_email_to_customer(
                customer_internal_id=str(customer["id"]),
                subject=subject,
                body=body,
                sender_email=sender_email,
                recipient_email=recipient_email,
                sent_datetime=sent_at,
            )
            logger.info(
                "Posted email '%s' → customer entityid=%s (%s)",
                subject,
                customer.get("entityid"),
                recipient_email,
            )
            posted += 1

        return posted

    def _lookup_customer(self, email: str) -> dict | None:
        """Cache-aware customer lookup by email address."""
        lower_email = email.lower()
        if lower_email not in self._customer_cache:
            self._customer_cache[lower_email] = (
                self._netsuite.find_customer_by_email(lower_email)
            )
        return self._customer_cache[lower_email]
