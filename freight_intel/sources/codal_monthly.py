"""Codal «گزارش فعالیت ماهانه» -> monthly production / domestic sales / export sales (I1, I2).

Production companies publish a product table whose columns include a one-month block
(«دوره یک ماهه منتهی به ...») with «مقدار تولید» and «مقدار فروش», and rows that end with
«جمع فروش داخلی», «جمع فروش صادراتی» and «جمع». The parser reads every HTML table on the page,
flattens multi-row headers, and picks those cells. Layouts differ between companies and years,
so the result carries `confidence` and every figure should be spot-checked on first use.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

from ..jalali import parse_any_date
from ..normalize import normalize

_NUM = re.compile(r"\(?-?[\d,]+(?:\.\d+)?\)?")


@dataclass
class MonthlyFigures:
    period_end: date | None
    production: float | None
    domestic_sales: float | None
    export_sales: float | None
    confidence: str  # high = all three found, partial = some found


def _num(v) -> float | None:
    if v is None:
        return None
    s = normalize(str(v)).replace(" ", "")
    m = _NUM.fullmatch(s) or _NUM.search(s)
    if not m or not any(ch.isdigit() for ch in m.group(0)):
        return None
    t = m.group(0)
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    val = float(t.strip("()-").replace(",", ""))
    return -val if neg else val


def _flat_columns(df) -> list[str]:
    cols = []
    for c in df.columns:
        parts = c if isinstance(c, tuple) else (c,)
        cols.append(normalize(" | ".join(str(p) for p in parts if not str(p).startswith("Unnamed"))))
    return cols


def _pick_col(cols: list[str], must: list[str], avoid: list[str]) -> int | None:
    for i, c in enumerate(cols):
        if all(re.search(m, c) for m in must) and not any(re.search(a, c) for a in avoid):
            return i
    return None


def parse_monthly_html(html: str) -> MonthlyFigures:
    import pandas as pd
    try:
        tables = pd.read_html(io.StringIO(html), header=[0, 1])
    except ValueError:
        tables = []
    if not tables:
        try:
            tables = pd.read_html(io.StringIO(html))
        except ValueError:
            tables = []
    period = None
    m = re.search(r"منتهی\s*به\s*(1[34]\d{2}\s*/\s*\d{1,2}\s*/\s*\d{1,2})", normalize(html))
    if m:
        period = parse_any_date(m.group(1))
    best = MonthlyFigures(period, None, None, None, "none")
    for df in tables:
        cols = _flat_columns(df)
        prod_c = _pick_col(cols, [r"یک\s*ماهه", r"تولید"], [r"مبلغ", r"نرخ"])
        sale_c = _pick_col(cols, [r"یک\s*ماهه", r"(?:مقدار|تعداد)\s*فروش"], [r"مبلغ", r"نرخ"])
        if prod_c is None and sale_c is None:
            continue
        rows = df.values.tolist()
        label = lambda r: normalize(" ".join(str(x) for x in r[:2]))
        dom = exp = tot_prod = None
        for r in rows:
            lb = label(r)
            if re.search(r"جمع\s*فروش\s*داخلی", lb) and sale_c is not None:
                dom = _num(r[sale_c])
            elif re.search(r"جمع\s*فروش\s*صادراتی", lb) and sale_c is not None:
                exp = _num(r[sale_c])
            elif re.fullmatch(r"(?:nan\s*)?جمع(?:\s*کل)?(?:\s*nan)?", lb.strip()) and prod_c is not None:
                tot_prod = _num(r[prod_c])
        found = sum(x is not None for x in (tot_prod, dom, exp))
        if found:
            conf = "high" if found == 3 else "partial"
            cand = MonthlyFigures(period, tot_prod, dom, exp, conf)
            if found > sum(x is not None for x in (best.production, best.domestic_sales, best.export_sales)):
                best = cand
    return best


def observations_from_history(history: list[tuple], today: date, ref: str = "codal.ir monthly"):
    """history: [(period_end, production, domestic, export, ref)] sorted by period -> [I1, I2] observations."""
    from ..scoring import i1_inventory_buildup, i2_export_share_rise
    rows = [h for h in history if h[1] is not None and h[2] is not None and h[3] is not None]
    if len(rows) < 4:
        return []
    last, prev = rows[-1], rows[-4:-1]
    out = []
    avg_prod = sum(r[1] for r in prev) / 3
    o1 = i1_inventory_buildup(last[1], last[2] + last[3], avg_prod, last[0], ref=last[4] or ref)
    shares = [r[3] / (r[2] + r[3]) for r in rows[-7:-1] if (r[2] + r[3])]
    o2 = i2_export_share_rise(last[3], last[2] + last[3], shares, last[0], ref=last[4] or ref)
    return [o for o in (o1, o2) if o]
