"""Push lead cards into a monday.com board (upsert by «شناسه سرنخ»).

Uses the monday GraphQL API with your own personal token: export MONDAY_API_TOKEN=...
Columns are found by TITLE at runtime, so the board only needs columns with the titles in
COLUMN_TITLES (missing ones are skipped). «وضعیت پیگیری» is set to «جدید» only when an item
is created and never overwritten; «مسئول پیگیری» is never written (sales assigns it).
"""
from __future__ import annotations

import json
import os

API_URL = "https://api.monday.com/v2"

T = {  # lead field -> column title on the board
    "lead_id": "شناسه سرنخ", "national_id": "شناسه ملی", "industry": "صنعت", "demand_type": "نوع نیاز",
    "demand_class": "طبقه تقاضا", "demand_score": "امتیاز تقاضا", "confidence": "امتیاز اطمینان",
    "ship_window": "بازه حمل", "commodity": "کالا", "hs_code": "کد HS", "qty": "تناژ یا حجم",
    "unit": "واحد", "exit_point": "مرز یا بندر خروجی", "destination": "کشور مقصد", "mode": "شیوه حمل",
    "level": "سطح راستی‌آزمایی", "sanctions": "غربالگری تحریمی", "deductions": "دلایل کسر امتیاز",
    "evidence": "شواهد و منابع", "unknowns": "نیازمند استعلام", "follow_up": "وضعیت پیگیری",
}
CREATE_ONLY = {"follow_up"}
GROUPS = {"ready": "آماده ارسال به فروش", "review": "نیازمند بررسی", "rejected": "رد شده",
          "unidentified": "صاحب بار شناسایی نشده"}
LABELS = {
    "demand_type": {"immediate": "فوری", "potential": "بالقوه"},
    "demand_class": {"definite": "قطعی", "high": "بالا", "medium": "متوسط", "low": "کم"},
    "mode": {"sea": "دریایی", "road": "جاده‌ای", "rail": "ریلی", "multimodal": "ترکیبی"},
    "industry": {"petrochemical": "پتروشیمی", "steel": "فولاد", "mining": "معدنی", "construction": "مصالح ساختمانی",
                 "agri": "کشاورزی", "industrial": "کالای صنعتی"},
    "sanctions": {"no_match": "بدون تطابق", "potential_match": "تطابق احتمالی", "not_checked": "بررسی نشده",
                  "error": "خطا در بررسی"},
}


def lead_group(lead: dict) -> str:
    if lead["verification"]["rejected"]:
        return GROUPS["rejected"]
    if not lead["shipper"].get("company_name"):
        return GROUPS["unidentified"]
    return GROUPS["ready"] if lead["ready_for_sales"] else GROUPS["review"]


def lead_fields(lead: dict) -> tuple[str, dict]:
    """Returns (item name, {field: python value})."""
    sh, de, ca, ve = lead["shipper"], lead["demand"], lead["cargo"], lead["verification"]
    q = ca.get("qty") or {}
    win = de.get("ship_window")
    ev = "\n".join(f"{e['signal_code']} | {e['source']} | {e.get('published_at') or '-'} | {e.get('url') or '-'}"
                   for e in lead["evidence"])
    name = sh.get("company_name") or ("شماره " + ", ".join(sh.get("contact_phones_public") or []) or lead["lead_id"])
    return name, {
        "lead_id": lead["lead_id"], "national_id": sh.get("national_id"),
        "industry": LABELS["industry"].get(sh.get("industry") or ""),
        "demand_type": LABELS["demand_type"].get(de["demand_type"]),
        "demand_class": LABELS["demand_class"].get(de["demand_class"]),
        "demand_score": de["demand_score"], "confidence": lead["confidence"]["score"],
        "ship_window": (win["from"], win["to"]) if win else None,
        "commodity": ca.get("commodity"), "hs_code": ca.get("hs_code"), "qty": q.get("value"), "unit": q.get("unit"),
        "exit_point": ca.get("exit_point"), "destination": ca.get("destination_country"),
        "mode": LABELS["mode"].get(ca.get("suggested_mode") or ""), "level": ve["level"],
        "sanctions": LABELS["sanctions"].get(ve["sanctions_screening"].get("result", "not_checked")),
        "deductions": "\n".join(f"{d['points']}: {d['reason']}" for d in lead["confidence"]["deductions"]),
        "evidence": ev,
        "unknowns": "\n".join(f"{u['field']}: {u['reason']} ← {u['action']}" for u in lead["unknowns"]),
        "follow_up": "جدید",
    }


def format_value(col_type: str, value):
    if value is None or value == "":
        return None
    if col_type == "status":
        return {"label": str(value)}
    if col_type == "dropdown":
        return {"labels": [str(value)]}
    if col_type == "numbers":
        return str(value)
    if col_type == "timeline":
        return {"from": value[0], "to": value[1]}
    if col_type == "date":
        return {"date": str(value)}
    if col_type == "long_text":
        return {"text": str(value)[:2000]}
    if col_type == "link":
        return {"url": str(value), "text": str(value)}
    return str(value)  # text and anything else


class MondayClient:
    def __init__(self, token: str | None = None, session=None):
        self.token = token or os.environ["MONDAY_API_TOKEN"]
        if session is None:
            import requests
            session = requests.Session()
        self.s = session

    def gql(self, query: str, variables: dict | None = None) -> dict:
        r = self.s.post(API_URL, json={"query": query, "variables": variables or {}},
                        headers={"Authorization": self.token, "Content-Type": "application/json"}, timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(json.dumps(body["errors"], ensure_ascii=False)[:500])
        return body["data"]


def push_leads(leads: list[dict], board_id: int, client: MondayClient, only_ready: bool = False) -> dict:
    meta = client.gql("query($b:[ID!]){boards(ids:$b){columns{id title type} groups{id title}}}",
                      {"b": [board_id]})["boards"][0]
    cols = {c["title"]: c for c in meta["columns"]}
    groups = {g["title"]: g["id"] for g in meta["groups"]}
    id_col = cols.get(T["lead_id"])
    if not id_col:
        raise ValueError(f"board has no «{T['lead_id']}» column")
    stats = {"created": 0, "updated": 0, "skipped": 0, "missing_columns": sorted(set(T.values()) - set(cols))}
    for lead in leads:
        if only_ready and not lead["ready_for_sales"]:
            stats["skipped"] += 1
            continue
        name, fields = lead_fields(lead)
        found = client.gql(
            "query($b:ID!,$c:String!,$v:String!){items_page_by_column_values(board_id:$b,limit:1,"
            "columns:[{column_id:$c,column_values:[$v]}]){items{id}}}",
            {"b": str(board_id), "c": id_col["id"], "v": lead["lead_id"]})["items_page_by_column_values"]["items"]
        values = {}
        for key, val in fields.items():
            col = cols.get(T[key])
            if not col or (found and key in CREATE_ONLY):
                continue
            fv = format_value(col["type"], val)
            if fv is not None:
                values[col["id"]] = fv
        if found:
            client.gql("mutation($b:ID!,$i:ID!,$v:JSON!){change_multiple_column_values(board_id:$b,item_id:$i,"
                       "column_values:$v,create_labels_if_missing:true){id}}",
                       {"b": str(board_id), "i": found[0]["id"], "v": json.dumps(values, ensure_ascii=False)})
            stats["updated"] += 1
        else:
            client.gql("mutation($b:ID!,$g:String,$n:String!,$v:JSON!){create_item(board_id:$b,group_id:$g,"
                       "item_name:$n,column_values:$v,create_labels_if_missing:true){id}}",
                       {"b": str(board_id), "g": groups.get(lead_group(lead)), "n": name[:255],
                        "v": json.dumps(values, ensure_ascii=False)})
            stats["created"] += 1
    return stats


OUTCOME_LABELS = {"برنده": 1, "از دست رفته": 0}


def fetch_outcomes(client: MondayClient, board_id: int) -> dict[str, int]:
    """{lead_id: 1|0} from items whose «وضعیت پیگیری» is برنده or از دست رفته."""
    meta = client.gql("query($b:[ID!]){boards(ids:$b){columns{id title}}}", {"b": [board_id]})["boards"][0]
    ids = {c["title"]: c["id"] for c in meta["columns"]}
    lid, fol = ids.get(T["lead_id"]), ids.get(T["follow_up"])
    if not lid or not fol:
        raise ValueError("board needs «شناسه سرنخ» and «وضعیت پیگیری» columns")
    out, cursor = {}, None
    q_first = ("query($b:[ID!],$c:[String!]){boards(ids:$b){items_page(limit:500){cursor items{"
               "column_values(ids:$c){id text}}}}}")
    q_next = "query($k:String!,$c:[String!]){next_items_page(limit:500,cursor:$k){cursor items{column_values(ids:$c){id text}}}}"
    while True:
        if cursor is None:
            page = client.gql(q_first, {"b": [board_id], "c": [lid, fol]})["boards"][0]["items_page"]
        else:
            page = client.gql(q_next, {"k": cursor, "c": [lid, fol]})["next_items_page"]
        for it in page["items"]:
            vals = {cv["id"]: cv["text"] for cv in it["column_values"]}
            if vals.get(fol) in OUTCOME_LABELS and vals.get(lid):
                out[vals[lid]] = OUTCOME_LABELS[vals[fol]]
        cursor = page.get("cursor")
        if not cursor:
            return out
