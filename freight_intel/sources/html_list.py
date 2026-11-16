"""Generic list-page scraper for tender aggregators and job boards.

Every site has its own markup, so CSS selectors live in config (`html_lists`), e.g.:
  - name: export_jobs
    url: "<list page URL with your search filter>"
    source_group: jobs          # tenders | jobs | exhibitions | b2b
    item: "<css selector of one result card>"
    title: "<css selector of the title inside the card>"
    link: "<css selector of the link inside the card>"
    company: "<css selector of the company name, optional>"
    date: "<css selector of the date, optional>"
Selectors must be checked against the live page before the first run; pages that render
with JavaScript need Playwright instead of requests.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..jalali import parse_any_date
from ..models import Document


def parse_list(html: str, cfg: dict) -> list[Document]:
    soup = BeautifulSoup(html, "lxml")
    docs = []
    for el in soup.select(cfg["item"]):
        t = el.select_one(cfg["title"]) if cfg.get("title") else el
        a = el.select_one(cfg["link"]) if cfg.get("link") else el.find("a")
        c = el.select_one(cfg["company"]) if cfg.get("company") else None
        d = el.select_one(cfg["date"]) if cfg.get("date") else None
        title = t.get_text(" ", strip=True) if t else ""
        if not title:
            continue
        docs.append(Document(
            source=f"html:{cfg['name']}", source_group=cfg.get("source_group", "tenders"),
            url=urljoin(cfg["url"], a["href"]) if a and a.has_attr("href") else cfg["url"],
            text=el.get_text("\n", strip=True),
            published_at=parse_any_date(d.get_text(strip=True)) if d else None,
            company_hint=c.get_text(" ", strip=True) if c else None))
    return docs


def fetch_list(fetcher, cfg: dict) -> list[Document]:
    return parse_list(fetcher.get(cfg["url"]).text, cfg)
