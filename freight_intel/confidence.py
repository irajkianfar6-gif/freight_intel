"""Section 4: confidence score 0..100 with an explicit reason for every deduction."""
from __future__ import annotations

DEDUCTIONS: dict[str, tuple[int, str]] = {
    "no_registry_match": (25, "تطبیق در روزنامه رسمی یا سامانه شناسه ملی یافت نشد"),
    "sanctions_pending": (20, "غربالگری تحریمی انجام نشده یا تطابق احتمالی در حال بررسی است"),
    "suspected_broker": (20, "مشکوک به واسطه (متن یا شماره تکراری در کانال‌ها و کالاهای مختلف)"),
    "single_source_group": (15, "شواهد فقط از یک گروه منبع"),
    "qty_unknown": (10, "تناژ یا حجم در هیچ منبعی ذکر نشده"),
    "origin_or_exit_unknown": (10, "مبدا یا مرز و بندر خروجی مشخص نیست"),
    "stale": (10, "عمر داده بیش از نیمی از عمر مفید آن است"),
    "destination_unknown": (5, "کشور مقصد مشخص نیست"),
    "no_contact": (5, "کانال تماس رسمی یافت نشد"),
}


def compute_confidence(flags: set[str]) -> tuple[int, list[dict]]:
    score, out = 100, []
    for key in DEDUCTIONS:
        if key in flags:
            pts, reason = DEDUCTIONS[key]
            score -= pts
            out.append({"code": key, "reason": reason, "points": -pts})
    return max(0, score), out
