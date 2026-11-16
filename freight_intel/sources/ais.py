"""Port-call counts from a commercial AIS provider (MarineTraffic, VesselFinder, Spire...).

Every provider has its own paid endpoint and response, so the call is described in config:
  ais:
    url: "https://<provider>/<endpoint>?port={port_id}&from={from}&to={to}&key={key}"
    key_env: AIS_API_KEY
    list_path: "data"          # dotted path to the list of port calls in the JSON
    ports: {"شهید رجایی": "<provider port id>", "بندر امام خمینی": "<id>"}
Iranian-flagged vessels often switch AIS off, so counts understate traffic: treat them as a
trend (this 30 days vs the previous 30), never as volumes.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from ..scoring import Observation
from ..sector import SectorObservation

RISE_THRESHOLD = 0.15


def _count(fetcher, cfg: dict, port_id: str, a: date, b: date) -> int:
    url = cfg["url"].format(port_id=port_id, **{"from": a.isoformat(), "to": b.isoformat()},
                            key=os.environ.get(cfg.get("key_env", "AIS_API_KEY"), ""))
    data = fetcher.get(url).json()
    for part in (cfg.get("list_path") or "").split("."):
        if part:
            data = data.get(part, []) if isinstance(data, dict) else []
    return len(data) if isinstance(data, list) else 0


def port_trend_observations(fetcher, cfg: dict, today: date) -> list[SectorObservation]:
    out = []
    for port, pid in (cfg.get("ports") or {}).items():
        now = _count(fetcher, cfg, pid, today - timedelta(days=30), today)
        before = _count(fetcher, cfg, pid, today - timedelta(days=60), today - timedelta(days=30))
        if before and (now - before) / before >= RISE_THRESHOLD:
            note = f"ورود کشتی {now} در برابر {before} در ۳۰ روز قبل"
            o = Observation("I10", min(1.0, (now - before) / before / 0.5), today, "corridor", 0.8,
                            evidence_ref=f"ais:{port}", note=note)
            out.append(SectorObservation("exit_point", port, +1, o, note))
    return out
