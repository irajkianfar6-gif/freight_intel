"""Offline end-to-end demo on SYNTHETIC records (tests/fixtures). No network, no real companies."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .jalali import parse_any_date
from .models import Document
from .pipeline import Pipeline, export
from .resolve import Registry
from .sources.ime import periodicity_observations, rows_to_documents
from .storage import Store

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def run_demo(today: date, out_dir: str = "outputs") -> list[dict]:
    store = Store(":memory:")
    registry = Registry.from_csv(FIX / "demo_registry.csv")
    docs = []
    for d in json.loads((FIX / "demo_docs.json").read_text(encoding="utf-8")):
        d["published_at"] = parse_any_date(d.get("published_at"))
        docs.append(Document(**d))
    rows = json.loads((FIX / "demo_ime_rows.json").read_text(encoding="utf-8"))
    docs += rows_to_documents(rows)
    store.add_documents(docs)
    for sup, obs in periodicity_observations(rows, today).items():
        for o in obs:
            store.add_observation(sup, None, o)
    p = Pipeline({}, store, registry)
    p.process(today)
    leads = p.build_leads(today, screen=False)
    jp, cp, xp = export(leads, out_dir, "demo_leads")
    for L in leads:
        print(f"{L['shipper']['company_name'] or '(unidentified)'} | {L['demand']['demand_type']} | "
              f"{L['demand']['demand_class']} {L['demand']['demand_score']} | {L['verification']['level']} | "
              f"conf {L['confidence']['score']} | rejected={L['verification']['rejected']}")
    print("written:", jp, cp, xp)
    return leads
