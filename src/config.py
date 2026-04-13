"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta


def get_slack_bot_token() -> str:
    return os.environ["SLACK_BOT_TOKEN"]


def get_slack_webhook_url() -> str:
    return os.environ["SLACK_WEBHOOK_URL"]


def get_openai_api_key() -> str:
    return os.environ["OPENAI_API_KEY"]


def get_notify_user_id() -> str:
    return os.environ.get("SLACK_NOTIFY_USER_ID", "W8FL6URHQ")


def get_date_range() -> tuple[datetime, datetime]:
    """Return (start, end) for the analysis window.

    Start: March 24 of the current year (last week of March).
    End: current timestamp when the pull is initiated.
    """
    now = datetime.now(timezone.utc)
    start = datetime(now.year, 3, 24, tzinfo=timezone.utc)
    return start, now
