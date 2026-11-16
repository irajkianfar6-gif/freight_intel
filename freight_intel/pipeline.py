"""Orchestration: collect (on schedule) -> process -> build leads -> export."""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import sanctions
from .calibration import load_probability_fn
from .extract import extract_signals, find_company, indicator_observations
from .leads import build_lead
from .resolve import Registry, clean_name
from .sector import sector_observations
from .sources.codal_monthly import observations_from_history
from .storage import Store
from .verify import detect_brokers

log = logging.getLogger("freight_intel")

# Section 1 monitoring frequencies (hours); config `every_hours` on a source overrides them
FREQUENCY_HOURS = {"telegram": 1, "freight_board": 6, "tenders": 12, "news": 24, "codal": 24, "ime": 24,
                   "registry": 24, "ais": 24, "jobs": 168, "b2b": 168, "exhibitions": 720, "comtrade": 720}


class Pipeline:
    def __init__(self, cfg: dict, store: Store, registry: Registry, fetcher=None):
        self.cfg, self.store, self.registry, self.fetcher = cfg, store, registry, fetcher

    # ---- 1. collect --------------------------------------------------------
    def _due(self, key: str, kind: str, every: float | None, now: datetime, due_only: bool) -> bool:
        if not due_only:
            return True
        last = self.store.last_run(key)
        return last is None or now - last >= timedelta(hours=every or FREQUENCY_HOURS.get(kind, 24))

    def collect(self, today: date, due_only: bool = False, now: datetime | None = None) -> int:
        from .sources import (ais, codal, codal_monthly, comtrade, gazette_csv, html_list, ime, ime_download,
                              news_rss, telegram_web)
        now = now or datetime.utcnow()
        src, f, total = self.cfg.get("sources", {}), self.fetcher, 0

        def run(key, kind, fn, every=None):
            nonlocal total
            if not self._due(key, kind, every, now, due_only):
                return
            try:
                docs = fn() or []
                n = self.store.add_documents(docs)
                total += n
                self.store.record_run(key, "ok", n, now)
                log.info("%s: %d documents (%d new)", key, len(docs), n)
            except Exception as e:  # one broken source must not stop the run
                self.store.record_run(key, f"error: {str(e)[:150]}", 0, now)
                log.warning("%s failed: %s", key, e)

        for ch in src.get("telegram_channels", []):
            run(f"telegram:{ch}", "telegram", lambda ch=ch: telegram_web.fetch_channel(f, ch, src.get("telegram_pages", 1)))
        if src.get("telegram_api", {}).get("channels"):
            from .sources import telegram_api
            run("telegram_api", "telegram", lambda: telegram_api.fetch(src["telegram_api"]["channels"]))
        for q in src.get("google_news_queries", []):
            run(f"gnews:{q}", "news", lambda q=q: news_rss.fetch_feed(f, news_rss.google_news_url(q), f"gnews:{q}"))
        for url in src.get("rss_feeds", []):
            run(f"rss:{url}", "news", lambda url=url: news_rss.fetch_feed(f, url))

        for sym in src.get("codal", {}).get("symbols", []):
            def _codal(sym=sym):
                docs = codal.letters_to_documents(codal.search(f, sym))
                for d in docs:
                    if d.source == "codal:material_disclosure":
                        d.text += "\n" + codal.fetch_letter_text(f, d.url)
                    elif d.source == "codal:monthly_activity":
                        fig = codal_monthly.parse_monthly_html(f.get(d.url).text)
                        if fig.confidence != "none":
                            self.store.add_monthly(d.company_hint or sym, fig.period_end or d.published_at,
                                                   fig.production, fig.domestic_sales, fig.export_sales, d.url)
                return docs
            run(f"codal:{sym}", "codal", _codal)

        ime_paths = list(src.get("ime_excel_paths", []))
        if self.cfg.get("ime_download"):
            def _dl():
                ime_paths.append(str(ime_download.yesterday_report(self.cfg["ime_download"], today)))
                return []
            run("ime_download", "ime", _dl)
        for path in ime_paths:
            def _ime(path=path):
                rows = ime.read_report(path, self.cfg.get("ime_columns"))
                for sup, obs in ime.periodicity_observations(rows, today).items():
                    for o in obs:
                        self.store.add_observation(sup, None, o)
                return ime.rows_to_documents(rows)
            run(f"ime:{path}", "ime", _ime)

        for path in src.get("gazette_csv_paths", []):
            run(f"gazette:{path}", "registry", lambda path=path: gazette_csv.read_notices(path))
        for hc in src.get("html_lists", []):
            run(f"html:{hc.get('name')}", hc.get("source_group", "tenders"),
                lambda hc=hc: html_list.fetch_list(f, hc), hc.get("every_hours"))

        ct = src.get("comtrade")
        if ct:
            def _ct():
                for row in comtrade.fetch_mirror(f, ct["reporters"], ct["hs_codes"], str(ct.get("period", today.year - 1))):
                    self.store.add_trade_flow(row["reporter"], row["hs"], row["period"], row["value_usd"], row["net_kg"])
                return []
            run("comtrade", "comtrade", _ct)
        if self.cfg.get("ais"):
            def _ais():
                for so in ais.port_trend_observations(f, self.cfg["ais"], today):
                    self.store.add_sector_observation(so)
                return []
            run("ais", "ais", _ais)
        self.store.commit()
        return total

    # ---- 2. process --------------------------------------------------------
    def process(self, today: date) -> dict:
        known = self.registry.names()
        n = {"signals": 0, "company_observations": 0, "sector_observations": 0}
        for doc_id, doc in self.store.unprocessed():
            for s in extract_signals(doc, known):
                self.store.add_signal(doc_id, s)
                n["signals"] += 1
            company = doc.company_hint or find_company(doc.text, known)
            if company:
                for o in indicator_observations(doc, today):
                    self.store.add_observation(company, doc.national_id_hint, o)
                    n["company_observations"] += 1
            for so in sector_observations(doc, today):
                self.store.add_sector_observation(so)
                n["sector_observations"] += 1
            self.store.mark_processed(doc_id)
        self.store.commit()
        return n

    # ---- 3. build leads ----------------------------------------------------
    def company_key(self, name, nid, phones) -> tuple[str | None, str | None]:
        rec, _ = self.registry.match(name, nid)
        if rec:
            return f"nid:{rec.national_id}", rec.name
        if nid:
            return f"nid:{nid}", name
        if name:
            return f"name:{clean_name(name)}", name
        if phones:
            return f"phone:{phones[0]}", None  # unidentified owner: identification queue
        return None, None

    def build_leads(self, today: date, screen: bool = True, calibration_path: str | None = None) -> list[dict]:
        sigs = self.store.signals()
        hashes, phones = detect_brokers(sigs)
        groups, names = defaultdict(lambda: ([], [])), {}
        for s in sigs:
            k, nm = self.company_key(s.company_name, s.national_id, s.phones)
            if k:
                groups[k][0].append(s)
                names.setdefault(k, nm)
        for company, nid, o in self.store.observations():
            k, nm = self.company_key(company, nid, [])
            if k:
                groups[k][1].append(o)
                names.setdefault(k, nm)
        for company in self.store.monthly_companies():
            k, nm = self.company_key(company, None, [])
            if k:
                groups[k][1].extend(observations_from_history(self.store.monthly(company), today))
                names.setdefault(k, nm)
        sector = self.store.sector_observations()
        flows = self.store.trade_flow_keys()
        prob = load_probability_fn(calibration_path or self.cfg.get("calibration_path", "data/calibration.json"))
        leads = []
        for k, (ss, oo) in groups.items():
            nm = names.get(k)
            sres = sanctions.screen([nm]) if (screen and nm) else {"result": "not_checked", "hits": []}
            lead = build_lead(k, nm, ss, oo, self.registry, sres, today, hashes, phones, sector, flows, prob)
            self.store.upsert_lead(k, lead)
            self.store.add_lead_snapshot(lead, today)
            leads.append(lead)
        self.store.commit()
        return sorted(leads, key=lambda L: (-L["demand"]["demand_score"], -L["confidence"]["score"]))


def export(leads: list[dict], out_dir: str | Path, prefix: str = "leads") -> tuple[Path, Path, Path]:
    from .report_xlsx import export_xlsx
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp, cp = out / f"{prefix}.json", out / f"{prefix}.csv"
    jp.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")
    cols = ["lead_id", "company_name", "national_id", "industry", "demand_type", "demand_class", "demand_score",
            "probability_6m", "ship_from", "ship_to", "commodity", "hs_code", "qty", "unit", "exit_point",
            "destination_country", "suggested_mode", "verification_level", "sanctions", "confidence", "deductions",
            "ready_for_sales", "evidence_urls"]
    with cp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for L in leads:
            win, q = L["demand"]["ship_window"] or {}, L["cargo"]["qty"] or {}
            w.writerow([L["lead_id"], L["shipper"]["company_name"], L["shipper"]["national_id"], L["shipper"]["industry"],
                        L["demand"]["demand_type"], L["demand"]["demand_class"], L["demand"]["demand_score"],
                        L["demand"].get("probability_6m"), win.get("from"), win.get("to"), L["cargo"]["commodity"],
                        L["cargo"]["hs_code"], q.get("value"), q.get("unit"), L["cargo"]["exit_point"],
                        L["cargo"]["destination_country"], L["cargo"]["suggested_mode"], L["verification"]["level"],
                        L["verification"]["sanctions_screening"].get("result"), L["confidence"]["score"],
                        "؛ ".join(d["reason"] for d in L["confidence"]["deductions"]), L["ready_for_sales"],
                        " ".join(sorted({e["url"] for e in L["evidence"] if e.get("url")}))])
    xp = export_xlsx(leads, out / f"{prefix}.xlsx")
    return jp, cp, xp
