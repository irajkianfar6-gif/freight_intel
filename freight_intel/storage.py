"""SQLite store: raw documents, signals, observations, leads."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime

from .models import Document, Signal
from .scoring import Observation

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, uid TEXT UNIQUE, source TEXT, source_group TEXT,
  url TEXT, text TEXT, published_at TEXT, retrieved_at TEXT, company_hint TEXT, national_id_hint TEXT,
  channel TEXT, processed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY, doc_id INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, company TEXT, national_id TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS leads (company_key TEXT PRIMARY KEY, lead_id TEXT, json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS lead_history (lead_id TEXT, as_of TEXT, json TEXT, PRIMARY KEY (lead_id, as_of));
CREATE TABLE IF NOT EXISTS sector_observations (id INTEGER PRIMARY KEY, uid TEXT UNIQUE, scope_type TEXT,
  scope_value TEXT, polarity INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS monthly_figures (company TEXT, period_end TEXT, production REAL, domestic_sales REAL,
  export_sales REAL, ref TEXT, PRIMARY KEY (company, period_end));
CREATE TABLE IF NOT EXISTS trade_flows (reporter TEXT, hs TEXT, period TEXT, value_usd REAL, net_kg REAL,
  PRIMARY KEY (reporter, hs, period));
CREATE TABLE IF NOT EXISTS runs (source_key TEXT PRIMARY KEY, last_run TEXT, status TEXT, n INTEGER);
"""


def _d(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def add_documents(self, docs: list[Document]) -> int:
        n = 0
        for d in docs:
            uid = hashlib.sha256(f"{d.url}|{d.channel}|{d.text}".encode()).hexdigest()
            cur = self.db.execute(
                "INSERT OR IGNORE INTO documents (uid,source,source_group,url,text,published_at,retrieved_at,"
                "company_hint,national_id_hint,channel) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uid, d.source, d.source_group, d.url, d.text, _d(d.published_at), _d(d.retrieved_at),
                 d.company_hint, d.national_id_hint, d.channel))
            n += cur.rowcount
        self.db.commit()
        return n

    def unprocessed(self) -> list[tuple[int, Document]]:
        rows = self.db.execute("SELECT id,source,source_group,url,text,published_at,retrieved_at,company_hint,"
                               "national_id_hint,channel FROM documents WHERE processed=0").fetchall()
        out = []
        for r in rows:
            out.append((r[0], Document(source=r[1], source_group=r[2], url=r[3], text=r[4],
                                       published_at=date.fromisoformat(r[5]) if r[5] else None,
                                       retrieved_at=datetime.fromisoformat(r[6]), company_hint=r[7],
                                       national_id_hint=r[8], channel=r[9])))
        return out

    def mark_processed(self, doc_id: int):
        self.db.execute("UPDATE documents SET processed=1 WHERE id=?", (doc_id,))

    def add_signal(self, doc_id: int, s: Signal):
        self.db.execute("INSERT INTO signals (doc_id,json) VALUES (?,?)", (doc_id, json.dumps(s.to_dict(), ensure_ascii=False)))

    def add_observation(self, company: str | None, national_id: str | None, o: Observation):
        d = asdict(o)
        d["observed_at"] = _d(o.observed_at)
        d["window"] = [_d(x) for x in o.window] if o.window else None
        self.db.execute("INSERT INTO observations (company,national_id,json) VALUES (?,?,?)",
                        (company, national_id, json.dumps(d, ensure_ascii=False)))

    def signals(self) -> list[Signal]:
        out = []
        for (j,) in self.db.execute("SELECT json FROM signals"):
            d = json.loads(j)
            d["published_at"] = date.fromisoformat(d["published_at"]) if d["published_at"] else None
            d["retrieved_at"] = datetime.fromisoformat(d["retrieved_at"])
            out.append(Signal(**d))
        return out

    def observations(self) -> list[tuple[str | None, str | None, Observation]]:
        out = []
        for company, nid, j in self.db.execute("SELECT company,national_id,json FROM observations"):
            d = json.loads(j)
            d["observed_at"] = date.fromisoformat(d["observed_at"])
            d["window"] = tuple(date.fromisoformat(x) for x in d["window"]) if d["window"] else None
            out.append((company, nid, Observation(**d)))
        return out

    def upsert_lead(self, key: str, lead: dict):
        self.db.execute("INSERT OR REPLACE INTO leads (company_key,lead_id,json,updated_at) VALUES (?,?,?,?)",
                        (key, lead["lead_id"], json.dumps(lead, ensure_ascii=False), datetime.utcnow().isoformat()))

    def commit(self):
        self.db.commit()

    # ---- sector observations -------------------------------------------------
    def add_sector_observation(self, so) -> None:
        d = asdict(so.obs)
        d["observed_at"] = _d(so.obs.observed_at)
        d["window"] = None
        uid = hashlib.sha256(f"{so.scope_type}|{so.scope_value}|{so.polarity}|{so.obs.code}|{so.obs.evidence_ref}|{d['observed_at']}".encode()).hexdigest()
        self.db.execute("INSERT OR IGNORE INTO sector_observations (uid,scope_type,scope_value,polarity,json) VALUES (?,?,?,?,?)",
                        (uid, so.scope_type, so.scope_value, so.polarity, json.dumps(d, ensure_ascii=False)))

    def sector_observations(self) -> list:
        from .sector import SectorObservation
        out = []
        for st, sv, pol, j in self.db.execute("SELECT scope_type,scope_value,polarity,json FROM sector_observations"):
            d = json.loads(j)
            d["observed_at"] = date.fromisoformat(d["observed_at"])
            d["window"] = None
            o = Observation(**d)
            out.append(SectorObservation(st, sv, pol, o, o.note))
        return out

    # ---- monthly figures (Codal) ---------------------------------------------
    def add_monthly(self, company: str, period_end: date, production, domestic, export, ref: str = ""):
        self.db.execute("INSERT OR REPLACE INTO monthly_figures VALUES (?,?,?,?,?,?)",
                        (company, _d(period_end), production, domestic, export, ref))

    def monthly(self, company: str) -> list[tuple]:
        return [(date.fromisoformat(p), a, b, c, r) for p, a, b, c, r in self.db.execute(
            "SELECT period_end,production,domestic_sales,export_sales,ref FROM monthly_figures WHERE company=? "
            "ORDER BY period_end", (company,))]

    def monthly_companies(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT company FROM monthly_figures")]

    # ---- trade flows (Comtrade mirror data) ----------------------------------
    def add_trade_flow(self, reporter: str, hs: str, period: str, value_usd, net_kg):
        self.db.execute("INSERT OR REPLACE INTO trade_flows VALUES (?,?,?,?,?)", (reporter, hs, period, value_usd, net_kg))

    def trade_flow_keys(self) -> set[tuple[str, str]]:
        """{(hs4, reporter ISO2)} with a positive import value from Iran."""
        return {(hs[:4], rep) for rep, hs, v in self.db.execute("SELECT reporter,hs,value_usd FROM trade_flows")
                if (v or 0) > 0}

    # ---- run bookkeeping (scheduler) -----------------------------------------
    def last_run(self, key: str) -> datetime | None:
        r = self.db.execute("SELECT last_run FROM runs WHERE source_key=? AND status='ok'", (key,)).fetchone()
        return datetime.fromisoformat(r[0]) if r else None

    def record_run(self, key: str, status: str, n: int, when: datetime | None = None):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)",
                        (key, (when or datetime.utcnow()).isoformat(timespec="seconds"), status, n))
        self.db.commit()

    # ---- lead history (calibration) ------------------------------------------
    def add_lead_snapshot(self, lead: dict, as_of: date):
        self.db.execute("INSERT OR REPLACE INTO lead_history VALUES (?,?,?)",
                        (lead["lead_id"], _d(as_of), json.dumps(lead, ensure_ascii=False)))

    def lead_history(self) -> list[tuple[str, date, dict]]:
        return [(lid, date.fromisoformat(a), json.loads(j)) for lid, a, j in
                self.db.execute("SELECT lead_id,as_of,json FROM lead_history ORDER BY as_of")]
