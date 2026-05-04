import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set. See .env.example.")
    return value


class Config:
    # Azure / Outlook
    AZURE_TENANT_ID: str = _require("AZURE_TENANT_ID")
    AZURE_CLIENT_ID: str = _require("AZURE_CLIENT_ID")
    AZURE_CLIENT_SECRET: str = _require("AZURE_CLIENT_SECRET")
    OUTLOOK_USER_EMAIL: str = _require("OUTLOOK_USER_EMAIL")

    # NetSuite
    NETSUITE_ACCOUNT_ID: str = _require("NETSUITE_ACCOUNT_ID")
    NETSUITE_CONSUMER_KEY: str = _require("NETSUITE_CONSUMER_KEY")
    NETSUITE_CONSUMER_SECRET: str = _require("NETSUITE_CONSUMER_SECRET")
    NETSUITE_TOKEN_KEY: str = _require("NETSUITE_TOKEN_KEY")
    NETSUITE_TOKEN_SECRET: str = _require("NETSUITE_TOKEN_SECRET")

    # Sync settings
    INITIAL_LOOKBACK_MINUTES: int = int(os.getenv("INITIAL_LOOKBACK_MINUTES", "60"))
    POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))
    SYNC_STATE_FILE: str = os.getenv("SYNC_STATE_FILE", ".sync_state.json")
