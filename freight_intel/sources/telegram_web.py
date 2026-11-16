"""Public Telegram channels through the t.me/s/<channel> web preview (no login).

Only public channels are reachable this way. For larger volumes use Telethon with
a dedicated account and the official API (api_id/api_hash from my.telegram.org).
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..jalali import parse_any_date
from ..models import Document

BASE = "https://t.me/s/"


def parse_channel_html(html: str, channel: str) -> list[Document]:
    soup = BeautifulSoup(html, "lxml")
    docs = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        time_el = msg.select_one("time[datetime]")
        post = msg["data-post"]  # "<channel>/<id>"
        docs.append(Document(
            source=f"telegram:{channel}", source_group="social", channel=channel,
            url=f"https://t.me/{post}", text=text_el.get_text("\n", strip=True),
            published_at=parse_any_date(time_el["datetime"]) if time_el else None))
    return docs


def fetch_channel(fetcher, channel: str, pages: int = 1) -> list[Document]:
    out, before = [], None
    for _ in range(pages):
        url = BASE + channel + (f"?before={before}" if before else "")
        docs = parse_channel_html(fetcher.get(url).text, channel)
        if not docs:
            break
        out.extend(docs)
        ids = [int(d.url.rsplit("/", 1)[-1]) for d in docs if d.url.rsplit("/", 1)[-1].isdigit()]
        if not ids:
            break
        before = min(ids)
    return out
