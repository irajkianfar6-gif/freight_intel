"""Replaces expert weights with a logistic model once real outcomes exist (Section 3.2).

Label: did the lead ship within the horizon (1) or not (0). Outcomes come from a CSV
(lead_id,shipped) or from the monday board («وضعیت پیگیری» = برنده / از دست رفته).
Features are taken from the EARLIEST snapshot of each lead, so the model learns from what was
known before the outcome. Writes data/calibration.json; leads then carry probability_6m.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path

from .scoring import INDICATORS

FEATURES = list(INDICATORS) + ["hard_signal", "verification_level", "confidence"]
LEVEL = {"V0": 0, "V1": 1, "V2": 2, "V3": 3}


def features(lead: dict) -> list[float]:
    br = lead["demand"]["score_breakdown"]
    x = [br["contributions"].get(c, 0.0) / INDICATORS[c].weight for c in INDICATORS]
    x += [1.0 if br.get("hard_signal_bonus") else 0.0, LEVEL.get(lead["verification"]["level"], 0) / 3,
          lead["confidence"]["score"] / 100]
    return x


def read_outcomes_csv(path: str | Path) -> dict[str, int]:
    with open(path, encoding="utf-8-sig") as f:
        return {r["lead_id"]: int(r["shipped"]) for r in csv.DictReader(f) if r.get("shipped") in ("0", "1")}


def fit(history: list[tuple], outcomes: dict[str, int], min_samples: int = 200) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss
    from sklearn.model_selection import cross_val_predict
    first = {}
    for lead_id, as_of, lead in history:  # history is ordered by as_of
        first.setdefault(lead_id, lead)
    ids = [i for i in outcomes if i in first]
    if len(ids) < min_samples:
        raise ValueError(f"only {len(ids)} labelled leads; need at least {min_samples} to calibrate")
    X = [features(first[i]) for i in ids]
    y = [outcomes[i] for i in ids]
    if len(set(y)) < 2:
        raise ValueError("outcomes contain one class only")
    model = LogisticRegression(C=1.0, max_iter=1000)
    p_cv = cross_val_predict(model, X, y, cv=min(5, min(y.count(0), y.count(1))), method="predict_proba")[:, 1]
    model.fit(X, y)
    bins = []
    for lo in [i / 5 for i in range(5)]:
        idx = [k for k, p in enumerate(p_cv) if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
        if idx:
            bins.append({"bin": f"{lo:.1f}-{lo + 0.2:.1f}", "n": len(idx),
                         "predicted": round(sum(p_cv[k] for k in idx) / len(idx), 3),
                         "observed": round(sum(y[k] for k in idx) / len(idx), 3)})
    return {"features": FEATURES, "coef": [round(float(c), 5) for c in model.coef_[0]],
            "intercept": round(float(model.intercept_[0]), 5), "n": len(ids), "base_rate": round(sum(y) / len(y), 3),
            "brier_cv": round(float(brier_score_loss(y, p_cv)), 4),
            "brier_base_rate": round(float(brier_score_loss(y, [sum(y) / len(y)] * len(y))), 4),
            "reliability": bins, "trained_at": datetime.utcnow().isoformat(timespec="seconds")}


def save(model: dict, path: str | Path = "data/calibration.json"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")


def load_probability_fn(path: str | Path = "data/calibration.json"):
    p = Path(path)
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("features") != FEATURES:
        return None  # model trained on another feature set: ignore rather than mis-score

    def prob(lead: dict) -> float:
        z = m["intercept"] + sum(c * x for c, x in zip(m["coef"], features(lead)))
        return round(1 / (1 + math.exp(-z)), 3)
    return prob
