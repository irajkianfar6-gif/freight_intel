"""Jalali (Shamsi) date parsing without external dependencies."""
from __future__ import annotations

import re
from datetime import date, datetime

from .normalize import normalize

JALALI_RX = re.compile(r"(?<!\d)(1[34]\d{2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)")
ISO_RX = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    months = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return date(gy, gm + 1, gd)


def parse_any_date(value) -> date | None:
    """Accepts date/datetime, ISO strings, or Jalali strings (Persian digits allowed)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = normalize(str(value))
    m = ISO_RX.search(s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = JALALI_RX.search(s)
    if m:
        try:
            return jalali_to_gregorian(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    try:
        from email.utils import parsedate_to_datetime  # RSS dates
        return parsedate_to_datetime(s).date()
    except Exception:
        return None
