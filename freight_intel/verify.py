"""Section 2.2: cross-verification matrix, levels V0..V3, rejection and broker detection."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .models import SIGNAL_TTL_DAYS, Signal
from .resolve import RegistryRecord

# signal code -> source groups that count as an independent confirmation
INDEPENDENT_SOURCES = {
    "H1": {"registry", "official_site"},
    "H2": {"codal", "registry", "ports"},
    "H3": {"ime", "ports", "news", "customs"},
    "H4": {"registry", "ime", "codal", "news"},
    "H5": {"codal", "ime", "official_site", "ports"},
    "H6": {"customs", "b2b_history"},
}
NEW_COMPANY_DAYS = 180
LARGE_LOT_MT = 500
BROKER_SAME_TEXT_CHANNELS = 5
BROKER_PHONE_COMMODITIES = 3


@dataclass
class Verification:
    level: str
    checks: list[dict] = field(default_factory=list)
    rejected: bool = False
    reject_reasons: list[str] = field(default_factory=list)
    suspected_broker: bool = False
    stale: bool = False


def detect_brokers(signals: list[Signal]) -> tuple[set[str], set[str]]:
    """Returns (content hashes, phones) that look like intermediaries."""
    hash_channels, phone_goods = defaultdict(set), defaultdict(set)
    for s in signals:
        hash_channels[s.content_hash].add(s.channel or s.source)
        for p in s.phones:
            phone_goods[p].add(s.commodity or s.content_hash)
    hashes = {h for h, ch in hash_channels.items() if len(ch) >= BROKER_SAME_TEXT_CHANNELS}
    phones = {p for p, g in phone_goods.items() if len(g) >= BROKER_PHONE_COMMODITIES}
    return hashes, phones


def is_stale(sig: Signal, today: date) -> bool:
    if not sig.published_at:
        return False
    ttl = SIGNAL_TTL_DAYS.get(sig.source_group, 30)
    return (today - sig.published_at).days > ttl / 2


def verify(signals: list[Signal], registry_rec: RegistryRecord | None, registry_ref: str,
           extra_source_groups: set[str], today: date,
           broker_hashes: set[str] = frozenset(), broker_phones: set[str] = frozenset()) -> Verification:
    checks: list[dict] = []
    groups = {s.source_group for s in signals} | set(extra_source_groups)
    codes = {s.code for s in signals}

    checks.append({"check": "registry_match", "source": "rrk.ir / ilenc.ir",
                   "result": "matched" if registry_rec else "not_found",
                   "ref": registry_ref if registry_rec else ""})
    if registry_rec:
        groups.add("registry")

    independent = False
    for code in codes:
        own = {s.source_group for s in signals if s.code == code}
        confirm = (groups - own) & INDEPENDENT_SOURCES.get(code, set())
        ok = bool(confirm)
        independent |= ok
        checks.append({"check": f"independent_confirmation_{code}", "source": ",".join(sorted(confirm)) or "-",
                       "result": "matched" if ok else "missing", "ref": ""})

    prior = bool(registry_rec and registry_rec.prior_export)
    checks.append({"check": "prior_export_history", "source": "registry cache / news / ime",
                   "result": "yes" if prior else "unknown", "ref": ""})

    level = "V0"
    if registry_rec:
        level = "V1"
        if independent and len(groups) >= 2:
            level = "V2"
            if prior:
                level = "V3"

    v = Verification(level=level, checks=checks)
    v.suspected_broker = any(s.content_hash in broker_hashes or set(s.phones) & set(broker_phones)
                             for s in signals)
    v.stale = all(is_stale(s, today) for s in signals) if signals else False

    max_qty = max((s.qty_value or 0) for s in signals if s.qty_unit == "MT") if any(
        s.qty_unit == "MT" for s in signals) else 0
    if v.suspected_broker and not registry_rec:
        v.rejected = True
        v.reject_reasons.append("الگوی واسطه بدون هویت حقوقی تاییدشده")
    if registry_rec and registry_rec.registered_at and \
            (today - registry_rec.registered_at).days < NEW_COMPANY_DAYS and max_qty >= LARGE_LOT_MT:
        v.rejected = True
        v.reject_reasons.append("شرکت کمتر از ۶ ماه پیش ثبت شده و محموله بزرگ اعلام کرده")
    if v.stale and codes and codes <= {"H4", "H6"}:
        v.rejected = True
        v.reject_reasons.append("آگهی منقضی شده است")
    return v
