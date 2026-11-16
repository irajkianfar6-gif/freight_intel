"""Telegram through the official API (Telethon), for more volume than the t.me/s preview.

Needs env TELEGRAM_API_ID, TELEGRAM_API_HASH (from my.telegram.org) and a session file created
once interactively (`python -m freight_intel.sources.telegram_api login`). Only read public
channels the account has access to; respect Telegram's terms and rate limits.
"""
from __future__ import annotations

import os
import sys

from ..models import Document


def fetch(channels: list[str], limit: int = 200, min_ids: dict[str, int] | None = None,
          session: str = "data/telegram.session") -> list[Document]:
    from telethon.sync import TelegramClient  # optional dependency
    api_id, api_hash = int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"]
    docs = []
    with TelegramClient(session, api_id, api_hash) as client:
        for ch in channels:
            kw = {"limit": limit}
            if min_ids and ch in min_ids:
                kw["min_id"] = min_ids[ch]
            for msg in client.iter_messages(ch, **kw):
                if not msg.message:
                    continue
                docs.append(Document(source=f"telegram:{ch}", source_group="social", channel=ch,
                                     url=f"https://t.me/{ch}/{msg.id}", text=msg.message,
                                     published_at=msg.date.date() if msg.date else None))
    return docs


if __name__ == "__main__" and sys.argv[1:] == ["login"]:
    from telethon.sync import TelegramClient
    with TelegramClient("data/telegram.session", int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"]) as c:
        print("logged in as", c.get_me().username)
