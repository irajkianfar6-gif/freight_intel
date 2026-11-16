"""Sector- and corridor-level indicators (I6 policy, I10 corridor) and how they reach companies.

A sector observation has a scope (hs4, industry, exit_point or destination) and a polarity:
+1 raises demand for every company in that scope (added as an Observation),
-1 is a headwind (export ban, new duty, border closure) that scales the demand score down.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .extract import find_first
from .models import Document
from .normalize import normalize
from .patterns import COMMODITY_GAZ, DEST_GAZ, EXIT_GAZ, term_rx
from .scoring import Observation

I6_POS_RX = re.compile(r"رفع\s*(?:ممنوعیت|محدودیت)|کاهش\s*(?:تعرفه|عوارض)|حذف\s*(?:عوارض|تعرفه)|"
                       r"(?:موافقت\s*نامه|توافق\s*نامه|توافق)\s*(?:تجارت\s*آزاد|تجارت\s*ترجیحی)|تعرفه\s*ترجیحی|"
                       r"free\s+trade\s+agreement|preferential\s+tariff", re.I)
I6_NEG_RX = re.compile(r"ممنوعیت\s*صادرات|(?:افزایش|وضع)\s*(?:تعرفه|عوارض)|توقف\s*صادرات|"
                       r"ضد\s*دامپینگ|anti\s*-?\s*dumping|export\s+ban", re.I)
I10_POS_RX = re.compile(r"(?:راه\s*اندازی|افتتاح|آغاز|برقراری)[^\n]{0,30}(?:قطار|خط\s*کشتیرانی|مسیر\s*ریلی|"
                        r"کریدور|سرویس\s*منظم)|قطار\s*(?:باری|کانتینری)[^\n]{0,40}(?:حرکت|راه\s*اندازی|وارد)")
I10_CONGESTION_RX = re.compile(r"صف\s*(?:طولانی\s*)?(?:کامیون|تریلی)|ازدحام[^\n]{0,20}(?:مرز|بندر)|"
                               r"تراکم\s*(?:کالا|بار)[^\n]{0,20}(?:بندر|گمرک)")
I10_NEG_RX = re.compile(r"(?:بسته\s*شدن|انسداد|توقف\s*تردد)[^\n]{0,20}(?:مرز|گذرگاه|مسیر)|مرز[^\n]{0,15}بسته\s*شد")
INDUSTRY_WORDS = {"پتروشیمی": "petrochemical", "پلیمر": "petrochemical", "فولاد": "steel", "آهن": "steel",
                  "معدن": "mining", "معدنی": "mining", "سیمان": "construction", "مصالح ساختمانی": "construction",
                  "کشاورزی": "agri", "محصولات کشاورزی": "agri", "میوه": "agri", "صیفی": "agri"}
_IND_GAZ = [(re.compile(r"(?<!\w)" + term_rx(k) + r"(?!\w)"), v) for k, v in
            sorted(INDUSTRY_WORDS.items(), key=lambda kv: -len(kv[0]))]


@dataclass
class SectorObservation:
    scope_type: str     # hs4 | industry | exit_point | destination
    scope_value: str
    polarity: int       # +1 tailwind, -1 headwind
    obs: Observation
    note: str = ""


def scopes_in_text(norm: str) -> list[tuple[str, str]]:
    out = []
    for rx, key, meta in COMMODITY_GAZ:
        if rx.search(norm):
            out.append(("hs4", meta[0]))
    for rx, ind in _IND_GAZ:
        if rx.search(norm):
            out.append(("industry", ind))
    for rx, key, _ in EXIT_GAZ:
        if rx.search(norm):
            out.append(("exit_point", key))
    for rx, key, iso in DEST_GAZ:
        if rx.search(norm):
            out.append(("destination", iso))
    return sorted(set(out))


def sector_observations(doc: Document, today: date) -> list[SectorObservation]:
    if doc.source_group not in ("news", "customs", "policy", "ports", "rail_road", "corridor"):
        return []
    norm = normalize(doc.text)
    when = doc.published_at or today
    rel = 1.0 if doc.source_group in ("customs", "policy", "ports", "rail_road") else 0.8
    found = []
    if I6_POS_RX.search(norm):
        found.append(("I6", +1, "policy", "تسهیل صادرات یا توافق تجاری"))
    elif I6_NEG_RX.search(norm):
        found.append(("I6", -1, "policy", "ممنوعیت یا عوارض صادراتی"))
    if I10_NEG_RX.search(norm):
        found.append(("I10", -1, "corridor", "بسته شدن یا توقف مسیر"))
    elif I10_POS_RX.search(norm):
        found.append(("I10", +1, "corridor", "ظرفیت جدید در کریدور"))
    elif I10_CONGESTION_RX.search(norm):
        found.append(("I10", +1, "corridor", "ازدحام: تقاضا برای مسیر یا شیوه جایگزین"))
    out = []
    scopes = scopes_in_text(norm)
    for code, pol, grp, note in found:
        wanted = {"I6": ("hs4", "industry", "destination"), "I10": ("exit_point", "destination")}[code]
        for st, sv in scopes:
            if st in wanted:
                o = Observation(code, 1.0, when, grp, rel, evidence_ref=doc.url, note=note)
                out.append(SectorObservation(st, sv, pol, o, note))
    return out


def company_scopes(signals: list, registry_activity: str | None) -> set[tuple[str, str]]:
    sc = set()
    for s in signals:
        if s.hs4: sc.add(("hs4", s.hs4))
        if s.industry: sc.add(("industry", s.industry))
        if s.exit_point: sc.add(("exit_point", s.exit_point))
        if s.destination_country: sc.add(("destination", s.destination_country))
    if registry_activity:
        norm = normalize(registry_activity)
        _, meta = find_first(COMMODITY_GAZ, norm)
        if meta:
            sc |= {("hs4", meta[0]), ("industry", meta[1])}
        for rx, ind in _IND_GAZ:
            if rx.search(norm):
                sc.add(("industry", ind))
    return sc


HEADWIND_FACTOR = 0.8
HEADWIND_FLOOR = 0.5
