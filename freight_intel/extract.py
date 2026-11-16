"""Turns a Document into zero or more Signals (Section 2, pattern layer)."""
from __future__ import annotations

from .models import Document, Signal, content_hash, reliability_for
from .normalize import normalize, normalize_key
from .patterns import (COMMODITY_GAZ, COMPANY_PREFIX_RX, COMPANY_STOPWORDS, CONTAINER_RX, DEST_GAZ,
                       EXIT_GAZ, H6_BUY_RX, H6_IRAN_RX, HARD_PATTERNS, INCOTERM_RX, MOBILE_RX,
                       MODE_HINTS, QTY_RX)


def detect_codes(norm: str) -> list[str]:
    codes = [code for code, (rx, _) in HARD_PATTERNS.items() if rx.search(norm)]
    if H6_BUY_RX.search(norm) and H6_IRAN_RX.search(norm):
        codes.append("H6")
    return codes


def parse_quantity(norm: str) -> tuple[float | None, str | None]:
    m = QTY_RX.search(norm)
    if m:
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000
        return val, "MT"
    m = CONTAINER_RX.search(norm)
    if m:
        return float(int(m.group(1)) * (2 if m.group(2) == "40" else 1)), "TEU"
    return None, None


def find_first(gaz, norm: str):
    best = None
    for rx, key, meta in gaz:
        m = rx.search(norm)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), key, meta)
    return (best[1], best[2]) if best else (None, None)


def find_company(norm: str, known_names: list[str] | None = None) -> str | None:
    if known_names:
        key = normalize_key(norm)
        for name in sorted(known_names, key=len, reverse=True):
            nk = normalize_key(name)
            if nk and nk in key:
                return name
    m = COMPANY_PREFIX_RX.search(norm)
    if not m:
        return None
    words = m.group(0).split()
    out = [words[0]]
    for w in words[1:]:
        if w in COMPANY_STOPWORDS:
            break
        out.append(w)
    return " ".join(out) if len(out) > 1 else None


def infer_mode(norm: str, exit_meta) -> str | None:
    if exit_meta:
        return exit_meta[0]
    for mode, rx in MODE_HINTS.items():
        if rx.search(norm):
            return mode
    return None


def extract_signals(doc: Document, known_names: list[str] | None = None) -> list[Signal]:
    norm = normalize(doc.text)
    codes = detect_codes(norm)
    if not codes:
        return []
    qty, unit = parse_quantity(norm)
    commodity, cmeta = find_first(COMMODITY_GAZ, norm)
    exit_point, emeta = find_first(EXIT_GAZ, norm)
    _, dest = find_first(DEST_GAZ, norm)
    if dest is None and emeta and emeta[1]:
        dest = emeta[1]  # a land border implies the neighbour, at least as transit
    inc = INCOTERM_RX.search(norm)
    company = doc.company_hint or find_company(norm, known_names)
    common = dict(
        source=doc.source, source_group=doc.source_group, url=doc.url, text=norm,
        published_at=doc.published_at, retrieved_at=doc.retrieved_at,
        reliability=reliability_for(doc.source_group), company_name=company,
        national_id=doc.national_id_hint, commodity=commodity,
        hs4=cmeta[0] if cmeta else None, industry=cmeta[1] if cmeta else None,
        qty_value=qty, qty_unit=unit, exit_point=exit_point, destination_country=dest,
        mode_hint=infer_mode(norm, emeta), incoterm=inc.group(1).upper() if inc else None,
        phones=sorted(set(MOBILE_RX.findall(norm))), channel=doc.channel,
        content_hash=content_hash(norm),
    )
    return [Signal(code=c, **common) for c in codes]


# ---- Leading-indicator events found in text (Section 3) ---------------------
import re as _re
from datetime import timedelta as _td

from .jalali import JALALI_RX, parse_any_date
from .scoring import i3_commissioning, simple_observation

I3_RX = _re.compile(r"بهره\s*برداری|راه\s*اندازی\s*(?:خط|واحد|فاز)|افتتاح\s*(?:خط|واحد|طرح)|افزایش\s*ظرفیت")
I5_RX = _re.compile(r"نمایشگاه|پاویون|غرفه|exhibitor|pavilion", _re.I)
I7_RX = _re.compile(r"(?:کارشناس|مدیر|مسئول|مسیول)\s*(?:بازرگانی\s*خارجی|صادرات|فروش\s*صادراتی)|"
                    r"اینکوترمز|incoterms|export\s+(?:manager|specialist)", _re.I)
I8_RX = _re.compile(r"(?:موضوع\s*فعالیت|موضوع\s*شرکت)[^\n]{0,120}(?:صادرات|واردات)|افزایش\s*سرمایه|تاسیس\s*شعبه")


def indicator_observations(doc: Document, today) -> list:
    """Returns Observations (I3, I5, I7, I8) for the company named in the document."""
    norm = normalize(doc.text)
    when = doc.published_at or today
    ref = doc.url
    out = []
    if doc.source_group == "jobs" and I7_RX.search(norm):
        out.append(simple_observation("I7", when, "jobs", 1.0, ref=ref, note="آگهی استخدام صادرات"))
    if doc.source_group in ("exhibitions", "news") and I5_RX.search(norm) and \
            (doc.source_group == "exhibitions" or _re.search(r"خارج|بین\s*المللی|پاویون\s*ملی", norm)):
        out.append(simple_observation("I5", when, doc.source_group, 1.0, ref=ref, note="حضور در نمایشگاه"))
    if doc.source_group in ("registry", "official_gazette") and I8_RX.search(norm):
        out.append(simple_observation("I8", when, "registry", 1.0, ref=ref, note="آگهی تغییرات"))
    if doc.source_group in ("codal", "news") and I3_RX.search(norm):
        dates = [parse_any_date(m.group(0)) for m in JALALI_RX.finditer(norm)]
        future = [d for d in dates if d and d >= when]
        if future:
            o = i3_commissioning(min(future), when, today, doc.source_group,
                                 1.0 if doc.source_group == "codal" else 0.8, ref)
        else:  # date not stated: assume the event is near the publication date
            o = simple_observation("I3", when, doc.source_group, 0.6, ref=ref, note="بهره‌برداری بدون تاریخ")
            o.window = (when + _td(days=30), when + _td(days=120))
        if o:
            out.append(o)
    return out
