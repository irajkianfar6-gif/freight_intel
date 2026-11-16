"""Data records shared by every stage."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from .normalize import normalize_key

SOURCE_RELIABILITY = {"official": 1.0, "media": 0.8, "social": 0.5, "unverified": 0.3}
# source_group -> reliability class
SOURCE_GROUP_CLASS = {
    "tenders": "official", "ime": "official", "codal": "official", "registry": "official",
    "customs": "official", "ports": "official", "rail_road": "official", "exhibitions": "official",
    "news": "media", "b2b": "social", "jobs": "media", "social": "social", "freight_board": "social",
}
# useful life (days) of an immediate signal, by source_group
SIGNAL_TTL_DAYS = {"social": 3, "freight_board": 3, "tenders": 30, "ime": 30, "codal": 90,
                   "news": 30, "b2b": 30, "jobs": 60}


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_key(text).encode("utf-8")).hexdigest()[:16]


def reliability_for(source_group: str) -> float:
    return SOURCE_RELIABILITY[SOURCE_GROUP_CLASS.get(source_group, "unverified")]


@dataclass
class Document:
    """One raw unit of text from a source: a post, a news item, a tender row, a disclosure."""
    source: str
    source_group: str
    url: str
    text: str
    published_at: date | None = None
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    company_hint: str | None = None
    national_id_hint: str | None = None
    channel: str | None = None  # e.g. Telegram channel, for broker detection


@dataclass
class Signal:
    code: str
    source: str
    source_group: str
    url: str
    text: str
    published_at: date | None
    retrieved_at: datetime
    reliability: float
    company_name: str | None = None
    national_id: str | None = None
    commodity: str | None = None
    hs4: str | None = None
    industry: str | None = None
    qty_value: float | None = None
    qty_unit: str | None = None
    exit_point: str | None = None
    destination_country: str | None = None
    mode_hint: str | None = None
    incoterm: str | None = None
    phones: list[str] = field(default_factory=list)
    channel: str | None = None
    content_hash: str = ""

    def evidence(self) -> dict:
        return {
            "signal_code": self.code,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "retrieved_at": self.retrieved_at.isoformat(timespec="seconds"),
            "extract": self.text[:500],
            "source_reliability": self.reliability,
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        d["retrieved_at"] = self.retrieved_at.isoformat(timespec="seconds")
        return d
