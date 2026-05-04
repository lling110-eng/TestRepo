"""
NetSuite client — looks up customers by email and posts email messages to
their Communication tab using the NetSuite REST Record API with
Token-Based Authentication (OAuth 1.0a).

NetSuite setup required:
  1. Setup > Integration > Manage Integrations → create an integration and
     copy the Consumer Key / Secret.
  2. Setup > Users/Roles > Access Tokens → generate a token for the integration
     and copy the Token Key / Secret.
  3. Ensure the role assigned to the token has REST Web Services permission and
     permission to create Message records.
"""

import base64
import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlencode

import requests

from .config import Config

logger = logging.getLogger(__name__)


class NetSuiteClient:
    def __init__(self, config: Config):
        self._config = config
        # NetSuite REST base URL — account ID must use underscores, not hyphens
        account = config.NETSUITE_ACCOUNT_ID.lower().replace("-", "_")
        self._base_url = f"https://{account}.suitetalk.api.netsuite.com/services/rest"

    # ── OAuth 1.0a signing ────────────────────────────────────────────────────

    def _oauth_header(self, method: str, url: str) -> str:
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time()))
        realm = self._config.NETSUITE_ACCOUNT_ID.upper()

        oauth_params = {
            "oauth_consumer_key": self._config.NETSUITE_CONSUMER_KEY,
            "oauth_nonce": nonce,
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": timestamp,
            "oauth_token": self._config.NETSUITE_TOKEN_KEY,
            "oauth_version": "1.0",
        }

        # Build the signature base string
        param_string = urlencode(sorted(oauth_params.items()))
        base_string = "&".join([
            method.upper(),
            quote(url, safe=""),
            quote(param_string, safe=""),
        ])

        signing_key = "&".join([
            quote(self._config.NETSUITE_CONSUMER_SECRET, safe=""),
            quote(self._config.NETSUITE_TOKEN_SECRET, safe=""),
        ])

        signature = hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        oauth_params["oauth_signature"] = base64.b64encode(signature).decode()

        header_value = f'OAuth realm="{realm}", ' + ", ".join(
            f'{k}="{quote(str(v), safe="")}"'
            for k, v in sorted(oauth_params.items())
        )
        return header_value

    def _headers(self, method: str, url: str, content_type: str = "application/json") -> dict:
        return {
            "Authorization": self._oauth_header(method, url),
            "Content-Type": content_type,
            "Prefer": "transient",
        }

    # ── customer lookup ───────────────────────────────────────────────────────

    def find_customer_by_email(self, email: str) -> Optional[dict]:
        """
        Search for a customer whose email matches exactly.
        Returns dict with 'id' (internal ID) and 'entityid' if found, else None.
        """
        url = f"{self._base_url}/query/v1/suiteql"
        sql = (
            "SELECT id, entityid, companyname, email "
            "FROM customer "
            f"WHERE LOWER(email) = '{email.lower().replace(chr(39), '')}' "
            "AND isinactive = 'F'"
        )
        payload = {"q": sql}

        resp = requests.post(
            url,
            headers=self._headers("POST", url),
            json=payload,
            timeout=30,
        )

        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        items = resp.json().get("items", [])
        if not items:
            return None

        customer = items[0]
        logger.info(
            "Found NetSuite customer: entityid=%s id=%s for email=%s",
            customer.get("entityid"),
            customer.get("id"),
            email,
        )
        return customer

    # ── create message ────────────────────────────────────────────────────────

    def post_email_to_customer(
        self,
        customer_internal_id: str,
        subject: str,
        body: str,
        sender_email: str,
        recipient_email: str,
        sent_datetime: datetime,
    ) -> dict:
        """
        Create a Message record linked to the customer so it appears on the
        customer's Communication tab in NetSuite.
        """
        url = f"{self._base_url}/record/v1/message"

        date_str = sent_datetime.astimezone(timezone.utc).strftime("%Y-%m-%d")
        time_str = sent_datetime.astimezone(timezone.utc).strftime("%H:%M")

        payload = {
            "entity": {"id": str(customer_internal_id)},
            "subject": subject or "(no subject)",
            "message": body or "",
            "authorEmail": sender_email,
            "recipientEmail": recipient_email,
            "messageDate": date_str,
            "time": time_str,
            "incoming": False,
            "emailed": True,
        }

        resp = requests.post(
            url,
            headers=self._headers("POST", url),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()

        # NetSuite returns 204 with a Location header on success
        location = resp.headers.get("Location", "")
        message_id = location.rstrip("/").split("/")[-1] if location else "unknown"

        logger.info(
            "Created NetSuite message id=%s for customer %s (subject: %s)",
            message_id,
            customer_internal_id,
            subject,
        )
        return {"id": message_id, "location": location}
