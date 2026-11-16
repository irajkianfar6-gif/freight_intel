"""Entity resolution: company name -> registry record (national ID is the key).

rrk.ir and ilenc.ir use captchas and have no public API, so lookups are done by a person
(or an approved data provider) and cached in data/registry.csv with these columns:
national_id,name,city,activity,registered_at,website,phone,prior_export(yes/no),checked_at,ref_url
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from .jalali import parse_any_date
from .normalize import normalize_key

try:
    from rapidfuzz import fuzz as _fuzz
except Exception:  # pragma: no cover
    _fuzz = None

_LEGAL_FORMS = re.compile(
    r"\b(شرکت|سهامی\s*خاص|سهامی\s*عام|سهامی|با\s*مسئولیت\s*محدود|با\s*مسیولیت\s*محدود|"
    r"تعاونی|مسئولیت\s*محدود|مسیولیت\s*محدود|co|ltd|llc|plc|pjsc|inc|company|ltd\.)\b", re.I)
NATIONAL_ID_RX = re.compile(r"(?<!\d)\d{11}(?!\d)")


def clean_name(name: str | None) -> str:
    k = normalize_key(name)
    k = _LEGAL_FORMS.sub(" ", k)
    return re.sub(r"\s+", " ", k).strip()


def similarity(a: str, b: str) -> float:
    a, b = clean_name(a), clean_name(b)
    if not a or not b:
        return 0.0
    if _fuzz is not None:
        return _fuzz.token_sort_ratio(a, b) / 100.0
    return SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()


@dataclass
class RegistryRecord:
    national_id: str
    name: str
    city: str = ""
    activity: str = ""
    registered_at: date | None = None
    website: str = ""
    phone: str = ""
    prior_export: bool = False
    ref_url: str = ""


class Registry:
    def __init__(self, records: list[RegistryRecord] | None = None):
        self.records = records or []
        self.by_id = {r.national_id: r for r in self.records}

    @classmethod
    def from_csv(cls, path: str | Path) -> "Registry":
        p = Path(path)
        if not p.exists():
            return cls([])
        recs = []
        with p.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                recs.append(RegistryRecord(
                    national_id=(row.get("national_id") or "").strip(),
                    name=row.get("name", ""), city=row.get("city", ""),
                    activity=row.get("activity", ""),
                    registered_at=parse_any_date(row.get("registered_at")),
                    website=row.get("website", ""), phone=row.get("phone", ""),
                    prior_export=(row.get("prior_export", "").strip().lower() in {"yes", "1", "true", "بله"}),
                    ref_url=row.get("ref_url", "")))
        return cls(recs)

    def names(self) -> list[str]:
        return [r.name for r in self.records]

    def match(self, name: str | None = None, national_id: str | None = None,
              city: str | None = None, threshold: float = 0.9) -> tuple[RegistryRecord | None, float]:
        if national_id and national_id in self.by_id:
            return self.by_id[national_id], 1.0
        if not name:
            return None, 0.0
        best, best_s = None, 0.0
        for r in self.records:
            s = similarity(name, r.name)
            if city and r.city and normalize_key(city) != normalize_key(r.city):
                s -= 0.05  # same name in another city is weaker evidence
            if s > best_s:
                best, best_s = r, s
        return (best, round(best_s, 3)) if best_s >= threshold else (None, round(best_s, 3))
