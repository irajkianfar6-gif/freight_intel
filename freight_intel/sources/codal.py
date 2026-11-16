"""codal.ir disclosures through its public search endpoint.

The endpoint is NOT documented or guaranteed by Codal; field names below are the ones it
returns today and may change. Keep request volume low (one call per symbol per run).
"""
from __future__ import annotations

from ..jalali import parse_any_date
from ..models import Document

SEARCH_URL = "https://search.codal.ir/api/search/v2/q"
SITE = "https://www.codal.ir"

LETTER_CLASSES = {
    "monthly_activity": ("گزارش فعالیت ماهانه",),
    "material_disclosure": ("افشای اطلاعات با اهمیت", "اطلاعات و صورت‌های مالی"),
    "management_report": ("گزارش تفسیری", "گزارش فعالیت هیئت مدیره"),
    "capital_increase": ("افزایش سرمایه",),
}


def classify_letter(title: str) -> str:
    for cls, keys in LETTER_CLASSES.items():
        if any(k.replace("‌", " ") in title.replace("‌", " ") for k in keys):
            return cls
    return "other"


def search(fetcher, symbol: str | None = None, page: int = 1) -> list[dict]:
    params = {"PageNumber": page, "search": "true", "Childs": "true", "Mains": "true",
              "Audited": "true", "NotAudited": "true", "Consolidatable": "true",
              "NotConsolidatable": "true", "Category": -1, "LetterType": -1, "Length": -1,
              "CompanyType": -1, "CompanyState": -1, "AuditorRef": -1, "TracingNo": -1,
              "Publisher": "false", "IsNotAudited": "false"}
    if symbol:
        params["Symbol"] = symbol
    r = fetcher.get(SEARCH_URL, params=params, headers={"Accept": "application/json"})
    return r.json().get("Letters", []) or []


def letters_to_documents(letters: list[dict]) -> list[Document]:
    docs = []
    for L in letters:
        title = L.get("Title", "")
        url = L.get("Url", "")
        docs.append(Document(
            source=f"codal:{classify_letter(title)}", source_group="codal",
            url=(SITE + url) if url.startswith("/") else url,
            text=f"{L.get('CompanyName', '')} ({L.get('Symbol', '')})\n{title}",
            published_at=parse_any_date(L.get("PublishDateTime") or L.get("SentDateTime")),
            company_hint=L.get("CompanyName") or None))
    return docs


def fetch_letter_text(fetcher, url: str) -> str:
    """Body text of one disclosure page (needed to detect H3 inside material disclosures)."""
    from bs4 import BeautifulSoup
    return BeautifulSoup(fetcher.get(url).text, "lxml").get_text("\n", strip=True)
