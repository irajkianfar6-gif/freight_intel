"""Sales-ready Excel workbook (right-to-left): leads, evidence, follow-up questions."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

CLASS_FA = {"definite": "قطعی", "high": "بالا", "medium": "متوسط", "low": "کم"}
TYPE_FA = {"immediate": "فوری", "potential": "بالقوه"}
FILL = {"definite": "C6EFCE", "high": "DDEBF7", "medium": "FFF2CC", "low": "F2F2F2"}


def _sheet(wb, title, header):
    ws = wb.create_sheet(title)
    ws.sheet_view.rightToLeft = True
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "A2"
    return ws


def export_xlsx(leads: list[dict], path: str | Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    ws = _sheet(wb, "سرنخ‌ها", ["شناسه سرنخ", "صاحب بار", "شناسه ملی", "نوع نیاز", "طبقه", "امتیاز تقاضا",
                                "احتمال ۶ ماهه", "از", "تا", "کالا", "کد HS", "تناژ یا حجم", "واحد",
                                "مرز یا بندر", "مقصد", "شیوه حمل", "راستی‌آزمایی", "تحریم", "اطمینان",
                                "آماده فروش", "رد شده", "عوامل منفی"])
    ev = _sheet(wb, "شواهد", ["شناسه سرنخ", "کد سیگنال", "منبع", "تاریخ", "لینک", "متن", "اعتبار منبع"])
    un = _sheet(wb, "نیازمند استعلام", ["شناسه سرنخ", "صاحب بار", "مورد", "دلیل", "اقدام"])
    for L in leads:
        d, c, q = L["demand"], L["cargo"], L["cargo"]["qty"] or {}
        w = d.get("ship_window") or {}
        hw = "؛ ".join(h["note"] + " (" + h["scope"] + ")" for h in d["score_breakdown"].get("headwinds", []))
        ws.append([L["lead_id"], L["shipper"]["company_name"], L["shipper"]["national_id"], TYPE_FA[d["demand_type"]],
                   CLASS_FA[d["demand_class"]], d["demand_score"], d.get("probability_6m"), w.get("from"), w.get("to"),
                   c["commodity"], c["hs_code"], q.get("value"), q.get("unit"), c["exit_point"], c["destination_country"],
                   c["suggested_mode"], L["verification"]["level"], L["verification"]["sanctions_screening"].get("result"),
                   L["confidence"]["score"], "بله" if L["ready_for_sales"] else "خیر",
                   "بله" if L["verification"]["rejected"] else "خیر", hw])
        ws.cell(ws.max_row, 5).fill = PatternFill("solid", fgColor=FILL[d["demand_class"]])
        for e in L["evidence"]:
            ev.append([L["lead_id"], e["signal_code"], e["source"], e.get("published_at"), e.get("url"),
                       (e.get("extract") or "")[:300], e.get("source_reliability")])
        for u in L["unknowns"]:
            un.append([L["lead_id"], L["shipper"]["company_name"], u["field"], u["reason"], u["action"]])
    for sh in (ws, ev, un):
        for col in sh.columns:
            width = min(50, max(10, max(len(str(x.value or "")) for x in col) + 2))
            sh.column_dimensions[col[0].column_letter].width = width
            for x in col[1:]:
                x.alignment = Alignment(wrap_text=width >= 50, vertical="top")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    wb.save(p)
    return p
