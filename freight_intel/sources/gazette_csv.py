"""Official Gazette (rrk.ir) notices, imported from a CSV filled by a researcher.

rrk.ir has a captcha and no API, so notices are copied by hand into a CSV with columns:
company,national_id,published_at,text,url   (published_at may be Jalali, e.g. 1405/08/20)
Each row becomes a 'registry' document; extract.indicator_observations turns
«موضوع فعالیت ... صادرات», «افزایش سرمایه», «تاسیس شعبه» into indicator I8.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ..jalali import parse_any_date
from ..models import Document


def read_notices(path: str | Path) -> list[Document]:
    p = Path(path)
    if not p.exists():
        return []
    docs = []
    with p.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not (row.get("text") or "").strip():
                continue
            docs.append(Document(source="rrk:notice", source_group="registry", url=row.get("url") or "https://rrk.ir",
                                 text=row["text"], published_at=parse_any_date(row.get("published_at")),
                                 company_hint=row.get("company") or None,
                                 national_id_hint=(row.get("national_id") or "").strip() or None))
    return docs
