"""Download the IME trade-report Excel with a headless browser (Playwright).

The report page is interactive (date pickers, export button), so the steps are a recipe in
config, checked once against the live page:
  ime_download:
    url: "<ime.co.ir trade report page>"
    steps:
      - {action: fill,  selector: "<from-date input>", value: "{jalali_from}"}
      - {action: fill,  selector: "<to-date input>",   value: "{jalali_to}"}
      - {action: click, selector: "<search button>"}
    download_selector: "<export to Excel button>"
    out_dir: data/ime
Install: pip install playwright && playwright install chromium
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


def gregorian_to_jalali(d: date) -> str:
    gy, gm, gd = d.year, d.month, d.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def download_report(cfg: dict, day_from: date, day_to: date | None = None) -> Path:
    from playwright.sync_api import sync_playwright  # optional dependency
    day_to = day_to or day_from
    values = {"jalali_from": gregorian_to_jalali(day_from), "jalali_to": gregorian_to_jalali(day_to)}
    out_dir = Path(cfg.get("out_dir", "data/ime"))
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="fa-IR")
        page.goto(cfg["url"], wait_until="networkidle")
        for st in cfg.get("steps", []):
            sel = st["selector"]
            if st["action"] == "fill":
                page.fill(sel, st["value"].format(**values))
            elif st["action"] == "click":
                page.click(sel)
            elif st["action"] == "select":
                page.select_option(sel, st["value"].format(**values))
            page.wait_for_load_state("networkidle")
        with page.expect_download() as dl:
            page.click(cfg["download_selector"])
        target = out_dir / f"ime_{day_from.isoformat()}_{day_to.isoformat()}.xlsx"
        dl.value.save_as(str(target))
        browser.close()
    return target


def yesterday_report(cfg: dict, today: date) -> Path:
    return download_report(cfg, today - timedelta(days=1))
