"""Iran Mercantile Exchange (ime.co.ir) trade reports.

ime.co.ir offers the trade report as an Excel download from its reports page. Download it
(manually or with a Playwright job) and point config `ime_excel_paths` at the files.
Column titles differ between report types, so they are mapped in config `ime_columns`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd

from ..jalali import parse_any_date
from ..models import Document
from ..normalize import normalize
from ..patterns import HARD_PATTERNS
from ..scoring import i9_periodicity

DEFAULT_COLUMNS = {
    "commodity": "نام کالا", "supplier": "تولید کننده", "volume": "حجم قرارداد",
    "delivery_place": "محل تحویل", "trade_date": "تاریخ معامله", "hall": "تالار",
    "delivery_date": "تاریخ تحویل", "price": "قیمت پایانی میانگین موزون",
}


def read_report(path: str, columns: dict | None = None) -> list[dict]:
    cols = {**DEFAULT_COLUMNS, **(columns or {})}
    df = pd.read_excel(path)
    df.columns = [normalize(str(c)) for c in df.columns]
    inv = {normalize(v): k for k, v in cols.items()}
    df = df.rename(columns={c: inv[c] for c in df.columns if c in inv})
    missing = [k for k in ("commodity", "supplier", "volume", "trade_date") if k not in df.columns]
    if missing:
        raise ValueError(f"IME report columns not found: {missing}. Map them in config ime_columns.")
    return df.to_dict("records")


def is_export_row(row: dict) -> bool:
    text = normalize(f"{row.get('hall', '')} {row.get('delivery_place', '')}")
    return bool(HARD_PATTERNS["H2"][0].search(text))


def rows_to_documents(rows: list[dict], report_url: str = "https://www.ime.co.ir") -> list[Document]:
    docs = []
    for r in rows:
        if not is_export_row(r):
            continue
        text = (f"عرضه صادراتی {r.get('commodity', '')} توسط {r.get('supplier', '')} "
                f"حجم {r.get('volume', '')} تن، تحویل {r.get('delivery_place', '')}، "
                f"تالار {r.get('hall', '')}، مهلت تحویل {r.get('delivery_date', '')}")
        docs.append(Document(source="ime:trade_report", source_group="ime", url=report_url, text=text,
                             published_at=parse_any_date(r.get("trade_date")),
                             company_hint=str(r.get("supplier", "")) or None))
    return docs


def periodicity_observations(rows: list[dict], today: date) -> dict[str, list]:
    """supplier -> [I9 Observation] built from repeated export offers."""
    by_supplier = defaultdict(list)
    for r in rows:
        if is_export_row(r):
            d = parse_any_date(r.get("trade_date"))
            if d:
                by_supplier[str(r.get("supplier", ""))].append(d)
    out = {}
    for sup, ds in by_supplier.items():
        o = i9_periodicity(ds, today, ref="ime.co.ir trade reports")
        if o:
            out[sup] = [o]
    return out
