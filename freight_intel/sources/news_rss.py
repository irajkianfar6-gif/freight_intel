"""RSS collector: site feeds and Google News search feeds in Persian."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

from ..jalali import parse_any_date
from ..models import Document


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=fa&gl=IR&ceid=IR:fa"


def parse_feed(xml_text: str, source: str) -> list[Document]:
    try:
        import feedparser  # optional, handles Atom and broken feeds better
        feed = feedparser.parse(xml_text)
        items = [(e.get("title", ""), e.get("link", ""), e.get("published") or e.get("updated"),
                  e.get("summary", "")) for e in feed.entries]
    except ImportError:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
        items = [(i.findtext("title", ""), i.findtext("link", ""), i.findtext("pubDate"),
                  i.findtext("description", "")) for i in root.iter("item")]
    docs = []
    for title, link, pub, summary in items:
        docs.append(Document(source=source, source_group="news", url=link,
                             text=f"{title}\n{_strip_html(summary)}", published_at=parse_any_date(pub)))
    return docs


def _strip_html(s: str) -> str:
    if not s or "<" not in s:
        return s or ""
    from bs4 import BeautifulSoup
    return BeautifulSoup(s, "lxml").get_text(" ", strip=True)


def fetch_feed(fetcher, url: str, source: str | None = None) -> list[Document]:
    return parse_feed(fetcher.get(url).text, source or url)
