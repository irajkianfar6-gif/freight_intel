"""python -m freight_intel.cli {collect|process|build|run|demo|push-monday|calibrate|status}"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from .pipeline import Pipeline, export
from .resolve import Registry
from .storage import Store


def load_config(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="freight_intel")
    ap.add_argument("command", choices=["collect", "process", "build", "run", "demo", "push-monday", "calibrate", "status"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, default: today")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--due-only", action="store_true", help="collect only sources whose interval has passed")
    ap.add_argument("--no-sanctions", action="store_true", help="skip screening (leads stay not ready)")
    ap.add_argument("--board", type=int, help="monday board id (push-monday, calibrate --from-monday)")
    ap.add_argument("--leads", default="outputs/leads.json")
    ap.add_argument("--only-ready", action="store_true")
    ap.add_argument("--outcomes", help="calibrate: CSV with lead_id,shipped")
    ap.add_argument("--from-monday", action="store_true", help="calibrate: read outcomes from the monday board")
    ap.add_argument("--min-samples", type=int, default=200)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = date.fromisoformat(a.today) if a.today else date.today()

    if a.command == "demo":
        from .demo import run_demo
        return run_demo(today, a.out)
    if a.command == "push-monday":
        from .monday_export import MondayClient, push_leads
        leads = json.loads(open(a.leads, encoding="utf-8").read())
        logging.info("monday: %s", push_leads(leads, a.board, MondayClient(), a.only_ready))
        return

    cfg = load_config(a.config)
    store = Store(cfg.get("storage", "data/freight_intel.sqlite"))
    if a.command == "status":
        for key, last, status, n in store.db.execute("SELECT * FROM runs ORDER BY source_key"):
            print(f"{key:50s} {last}  {status}  {n}")
        return
    if a.command == "calibrate":
        from . import calibration
        if a.from_monday:
            from .monday_export import MondayClient, fetch_outcomes
            outcomes = fetch_outcomes(MondayClient(), a.board)
        else:
            outcomes = calibration.read_outcomes_csv(a.outcomes)
        model = calibration.fit(store.lead_history(), outcomes, a.min_samples)
        calibration.save(model, cfg.get("calibration_path", "data/calibration.json"))
        logging.info("calibrated on %d leads, Brier %.4f (base rate %.4f)", model["n"], model["brier_cv"],
                     model["brier_base_rate"])
        return

    registry = Registry.from_csv(cfg.get("registry_csv", "data/registry.csv"))
    fetcher = None
    if a.command in ("collect", "run"):
        from .sources.base import Fetcher
        fetcher = Fetcher(cfg.get("user_agent", "FreightIntelBot/0.1"), cfg.get("min_delay_seconds", 3),
                          respect_robots=cfg.get("respect_robots", True))
    p = Pipeline(cfg, store, registry, fetcher)
    if a.command in ("collect", "run"):
        logging.info("collected %d new documents", p.collect(today, due_only=a.due_only))
    if a.command in ("process", "run"):
        logging.info("processed: %s", p.process(today))
    if a.command in ("build", "run"):
        leads = p.build_leads(today, screen=not a.no_sanctions)
        logging.info("%d leads -> %s", len(leads), export(leads, a.out))


if __name__ == "__main__":
    main()
