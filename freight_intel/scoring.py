"""Section 3: leading indicators, weighted decay score, class and ship window."""
from __future__ import annotations

import calendar
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class IndicatorSpec:
    code: str
    name: str
    weight: float
    half_life_days: float | None  # None = no decay (calendar driven)
    window_days: tuple[int, int]  # ship window relative to observed_at; (0,0) = observation supplies it
    group: str                    # capacity | market | context


INDICATORS: dict[str, IndicatorSpec] = {s.code: s for s in [
    IndicatorSpec("I1", "انباشت موجودی", 12, 45, (0, 60), "capacity"),
    IndicatorSpec("I2", "افزایش سهم فروش صادراتی", 10, 60, (0, 90), "capacity"),
    IndicatorSpec("I3", "بهره‌برداری طرح توسعه", 15, 90, (0, 0), "capacity"),
    IndicatorSpec("I4", "تقویم فصلی", 12, None, (0, 0), "context"),
    IndicatorSpec("I5", "حضور در نمایشگاه خارجی", 8, 120, (30, 180), "market"),
    IndicatorSpec("I6", "تغییر تعرفه یا توافق تجاری", 8, 90, (0, 90), "market"),
    IndicatorSpec("I7", "استخدام کارشناس صادرات", 8, 60, (30, 120), "market"),
    IndicatorSpec("I8", "تغییرات در روزنامه رسمی", 7, 120, (60, 180), "market"),
    IndicatorSpec("I9", "تکرار عرضه صادراتی در بورس", 15, 90, (0, 0), "capacity"),
    IndicatorSpec("I10", "تغییر ظرفیت کریدور", 5, 45, (0, 90), "context"),
]}
assert abs(sum(s.weight for s in INDICATORS.values()) - 100) < 1e-9

SYNERGY_BONUS = 10.0
HARD_SIGNAL_BONUS = 20.0     # a V2-verified H1..H5 signal on the same company
DIVERSITY_CAP = 59.0         # fewer than 2 independent source groups
CLASS_THRESHOLDS = (40.0, 70.0)
NON_COMPANY_GROUPS = {"calendar", "policy", "corridor"}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


@dataclass
class Observation:
    code: str
    strength: float               # s_i in [0,1]
    observed_at: date
    source_group: str
    reliability: float = 1.0      # r_i
    window: tuple[date, date] | None = None
    evidence_ref: str | None = None
    note: str = ""


@dataclass
class ShipWindow:
    start: date
    end: date
    basis: list[str]
    uncertain: bool

    def to_dict(self) -> dict:
        return {"from": self.start.isoformat(), "to": self.end.isoformat(),
                "basis": self.basis, "uncertain": self.uncertain}


@dataclass
class ScoreResult:
    demand_score: float
    demand_class: str
    contributions: dict[str, float]
    synergy_bonus: float
    hard_bonus: float
    diversity_capped: bool
    ship_window: ShipWindow | None
    source_groups: list[str] = field(default_factory=list)


def decay(spec: IndicatorSpec, observed_at: date, today: date) -> float:
    if spec.half_life_days is None:
        return 1.0
    age = max(0, (today - observed_at).days)
    return 0.5 ** (age / spec.half_life_days)


def classify(score: float, hard_verified: bool) -> str:
    lo, hi = CLASS_THRESHOLDS
    if score >= hi:
        return "definite" if hard_verified else "high"
    return "medium" if score >= lo else "low"


def score_company(observations: list[Observation], today: date, hard_verified: bool = False,
                  hard_source_groups: set[str] | None = None) -> ScoreResult:
    best: dict[str, tuple[float, Observation]] = {}
    for o in observations:
        spec = INDICATORS[o.code]
        c = spec.weight * clamp(o.strength) * decay(spec, o.observed_at, today) * clamp(o.reliability)
        if c > best.get(o.code, (0.0, None))[0]:
            best[o.code] = (c, o)  # one indicator counts once (no double counting)
    raw = sum(c for c, _ in best.values())
    groups = {INDICATORS[k].group for k, (c, _) in best.items() if c > 0}
    synergy = SYNERGY_BONUS if {"capacity", "market"} <= groups else 0.0
    hard = HARD_SIGNAL_BONUS if hard_verified else 0.0
    score = min(100.0, raw + synergy + hard)
    # sector-level evidence (calendar, policy, corridor) says nothing about the company itself
    src_groups = ({o.source_group for _, o in best.values()} | (hard_source_groups or set())) - NON_COMPANY_GROUPS
    capped = len(src_groups) < 2 and score > DIVERSITY_CAP
    if capped:
        score = DIVERSITY_CAP
    return ScoreResult(
        demand_score=round(score, 1),
        demand_class=classify(score, hard_verified and not capped),
        contributions={k: round(c, 2) for k, (c, _) in best.items()},
        synergy_bonus=synergy, hard_bonus=hard, diversity_capped=capped,
        ship_window=estimate_window(best, today), source_groups=sorted(src_groups))


def estimate_window(best: dict[str, tuple[float, Observation]], today: date) -> ShipWindow | None:
    spans = []
    for code, (c, o) in best.items():
        if c <= 0:
            continue
        spec = INDICATORS[code]
        if o.window:
            a, b = o.window
        elif spec.window_days != (0, 0):
            a = o.observed_at + timedelta(days=spec.window_days[0])
            b = o.observed_at + timedelta(days=spec.window_days[1])
        else:
            continue
        if b < today:
            continue
        spans.append((max(a, today), b, c, code))
    if not spans:
        return None
    basis = [s[3] for s in sorted(spans, key=lambda s: -s[2])]
    start, end = max(s[0] for s in spans), min(s[1] for s in spans)
    if start <= end:
        return ShipWindow(start, end, basis, False)
    # no common interval: weighted median of midpoints +/- weighted spread
    mids = sorted(((s[0].toordinal() + s[1].toordinal()) / 2, s[2]) for s in spans)
    total = sum(w for _, w in mids)
    acc, wm = 0.0, mids[-1][0]
    for m, w in mids:
        acc += w
        if acc >= total / 2:
            wm = m
            break
    spread = max(15.0, math.sqrt(sum(w * (m - wm) ** 2 for m, w in mids) / total))
    return ShipWindow(date.fromordinal(int(wm - spread)), date.fromordinal(int(wm + spread)), basis, True)


# ---- Indicator builders: raw public data -> Observation ---------------------
def i1_inventory_buildup(production: float, total_sales: float, avg_production_3m: float,
                         report_date: date, source_group: str = "codal", ref: str | None = None):
    if not avg_production_3m:
        return None
    ratio = (production - total_sales) / avg_production_3m
    s = clamp(ratio / 0.3)
    return Observation("I1", s, report_date, source_group, 1.0, evidence_ref=ref,
                       note=f"(تولید منهای فروش)/میانگین تولید = {ratio:.2f}") if s > 0 else None


def i2_export_share_rise(export_qty: float, total_sales_qty: float, past_shares: list[float],
                         report_date: date, source_group: str = "codal", ref: str | None = None):
    if not total_sales_qty or not past_shares:
        return None
    share = export_qty / total_sales_qty
    delta = share - statistics.mean(past_shares)
    s = clamp(delta / 0.2)
    return Observation("I2", s, report_date, source_group, 1.0, evidence_ref=ref,
                       note=f"سهم صادرات {share:.0%} در برابر میانگین {statistics.mean(past_shares):.0%}") if s > 0 else None


def i3_commissioning(commission_date: date, announced_at: date, today: date,
                     source_group: str = "codal", reliability: float = 1.0, ref: str | None = None):
    days = (commission_date - today).days
    if 0 <= days <= 90:
        s = 1.0
    elif 90 < days <= 180:
        s = 0.5
    elif -60 <= days < 0:
        s = 0.7  # just commissioned, first export lots still ahead
    else:
        return None
    win = (commission_date + timedelta(days=30), commission_date + timedelta(days=120))
    return Observation("I3", s, announced_at, source_group, reliability, win, ref,
                       f"بهره‌برداری {commission_date.isoformat()}")


# Approximate export seasons (Gregorian months). Review yearly against maj.ir and USDA FAS reports.
SEASONAL_EXPORT_MONTHS = {
    "0802": (9, 3), "0804": (9, 1), "0910": (11, 3), "0805": (12, 3), "0806": (9, 12),
    "0807": (6, 8), "0701": (6, 11), "0703": (5, 9), "0702": (11, 4),
    "2523": (12, 2),  # cement: domestic low season pushes exports
}


def _season_span(year: int, m1: int, m2: int) -> tuple[date, date]:
    y2 = year if m2 >= m1 else year + 1
    return date(year, m1, 1), date(y2, m2, calendar.monthrange(y2, m2)[1])


def i4_seasonal(hs4: str, today: date):
    months = SEASONAL_EXPORT_MONTHS.get(hs4)
    if not months:
        return None
    for y in (today.year - 1, today.year, today.year + 1):
        a, b = _season_span(y, *months)
        if a <= today <= b:
            return Observation("I4", 1.0, today, "calendar", 1.0, (today, b), note="داخل فصل صادرات")
        if 0 < (a - today).days <= 60:
            return Observation("I4", 0.6, today, "calendar", 1.0, (a, b), note="شروع فصل در ۶۰ روز آینده")
    return None


def i9_periodicity(offer_dates: list[date], today: date, source_group: str = "ime", ref: str | None = None):
    ds = sorted(set(offer_dates))
    if len(ds) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
    if len(gaps) < 2:
        return None
    mean = statistics.mean(gaps)
    cv = statistics.pstdev(gaps) / mean if mean else 1.0
    s = clamp(1 - cv)
    med = statistics.median(gaps)
    nxt = ds[-1] + timedelta(days=med)
    while nxt + timedelta(days=med / 2) < today:
        nxt += timedelta(days=med)
    win = (nxt - timedelta(days=med / 2), nxt + timedelta(days=med / 2))
    return Observation("I9", s, ds[-1], source_group, 1.0, win, ref,
                       f"{len(ds)} عرضه، فاصله میانه {med:.0f} روز") if s > 0 else None


def simple_observation(code: str, observed_at: date, source_group: str, strength: float = 1.0,
                       reliability: float | None = None, ref: str | None = None, note: str = ""):
    """I5, I6, I7, I8, I10: event-type indicators."""
    from .models import reliability_for
    r = reliability if reliability is not None else reliability_for(source_group)
    return Observation(code, clamp(strength), observed_at, source_group, r, evidence_ref=ref, note=note)
