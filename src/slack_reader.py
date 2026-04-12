"""Read messages from Slack channels using the Slack SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from slack_sdk import WebClient

from src.models import ChannelSource, RawSlackMessage, CHANNEL_CONFIG


class SlackReaderProtocol(Protocol):
    def read_channel(
        self, channel: ChannelSource, oldest: datetime, latest: datetime
    ) -> list[RawSlackMessage]: ...


class SlackReader:
    def __init__(self, token: str) -> None:
        self._client = WebClient(token=token)

    def read_channel(
        self, channel: ChannelSource, oldest: datetime, latest: datetime
    ) -> list[RawSlackMessage]:
        channel_id = CHANNEL_CONFIG[channel]
        messages: list[RawSlackMessage] = []
        cursor = None

        while True:
            kwargs: dict = {
                "channel": channel_id,
                "oldest": str(oldest.timestamp()),
                "latest": str(latest.timestamp()),
                "limit": 100,
                "inclusive": True,
            }
            if cursor:
                kwargs["cursor"] = cursor

            resp = self._client.conversations_history(**kwargs)
            for msg in resp.get("messages", []):
                ts = msg.get("ts", "")
                messages.append(
                    RawSlackMessage(
                        channel=channel,
                        channel_id=channel_id,
                        timestamp=ts,
                        datetime_utc=datetime.utcfromtimestamp(float(ts)),
                        author=msg.get("username", msg.get("user", "unknown")),
                        author_id=msg.get("user", msg.get("bot_id", "")),
                        text=msg.get("text", ""),
                        thread_reply_count=msg.get("reply_count", 0),
                        reactions=[
                            r["name"] for r in msg.get("reactions", [])
                        ],
                    )
                )

            metadata = resp.get("response_metadata", {})
            cursor = metadata.get("next_cursor")
            if not cursor:
                break

        return messages

    def read_all_channels(
        self, oldest: datetime, latest: datetime
    ) -> dict[ChannelSource, list[RawSlackMessage]]:
        result = {}
        for channel in ChannelSource:
            result[channel] = self.read_channel(channel, oldest, latest)
        return result
