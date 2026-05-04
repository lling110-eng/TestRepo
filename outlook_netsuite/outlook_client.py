"""
Outlook client — fetches sent emails via Microsoft Graph API using app-only auth.

Required Azure AD app permissions (application, not delegated):
  Mail.Read
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import msal
import requests

from .config import Config

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class OutlookClient:
    def __init__(self, config: Config):
        self._config = config
        self._token: Optional[str] = None

    # ── auth ──────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        app = msal.ConfidentialClientApplication(
            client_id=self._config.AZURE_CLIENT_ID,
            client_credential=self._config.AZURE_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{self._config.AZURE_TENANT_ID}",
        )
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise RuntimeError(f"Failed to acquire Graph token: {result.get('error_description')}")
        return result["access_token"]

    def _headers(self) -> dict:
        if not self._token:
            self._token = self._get_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _get(self, url: str, params: dict = None) -> dict:
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 401:
            # Token expired — refresh once
            self._token = self._get_token()
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── public API ────────────────────────────────────────────────────────────

    def get_sent_emails_since(self, since: datetime) -> list[dict]:
        """
        Return all emails from the user's Sent Items folder sent after `since`.
        Each item contains: id, subject, bodyPreview, body, sentDateTime,
        sender, toRecipients, ccRecipients.
        """
        since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        user = self._config.OUTLOOK_USER_EMAIL

        url = f"{GRAPH_BASE}/users/{user}/mailFolders/SentItems/messages"
        params = {
            "$filter": f"sentDateTime ge {since_str}",
            "$select": "id,subject,bodyPreview,body,sentDateTime,sender,toRecipients,ccRecipients",
            "$orderby": "sentDateTime asc",
            "$top": 50,
        }

        emails = []
        while url:
            data = self._get(url, params)
            emails.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            params = None  # nextLink already includes params
            logger.debug("Fetched %d sent emails so far", len(emails))

        return emails

    def extract_recipients(self, email: dict) -> list[str]:
        """Return a flat list of all To + CC recipient email addresses."""
        addresses = []
        for field in ("toRecipients", "ccRecipients"):
            for r in email.get(field) or []:
                addr = r.get("emailAddress", {}).get("address", "").strip().lower()
                if addr:
                    addresses.append(addr)
        return addresses

    def get_body_text(self, email: dict) -> str:
        """Return plain-text body, falling back to bodyPreview."""
        body = email.get("body", {})
        content = body.get("content", "").strip()
        if not content:
            content = email.get("bodyPreview", "")
        # Strip HTML tags for plain-text storage if body is HTML
        if body.get("contentType", "").lower() == "html":
            try:
                import re
                content = re.sub(r"<[^>]+>", "", content)
                content = re.sub(r"\s+", " ", content).strip()
            except Exception:
                pass
        return content
