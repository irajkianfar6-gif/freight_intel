"""Assembles the Section 4 lead card from signals, observations, verification and score."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from .confidence import compute_confidence
from .resolve import Registry, RegistryRecord
from .scoring import NON_COMPANY_GROUPS, Observation, i4_seasonal, score_company
from .sector import HEADWIND_FACTOR, HEADWIND_FLOOR, company_scopes
from .verify import is_stale, verify

IMMEDIATE_WINDOW_DAYS = {"H1": 60, "H2": 30, "H3": 45, "H4": 14, "H5": 60, "H6": 90}
ALWAYS_UNKNOWN = [
    ("consignee_and_destination", "نام خریدار و گیرنده در منابع عمومی منتشر نمی‌شود", "تماس با واحد فروش صادراتی"),
    ("actual_incoterm_and_freight_payer", "پرداخت‌کننده کرایه معمولا اعلام نمی‌شود", "استعلام تلفنی"),
    ("current_forwarder_and_contract_end", "قرارداد حمل فعلی عمومی نیست", "پرسش در اولین تماس"),
    ("packaging_and_dg_class", "بسته‌بندی و کلاس کالای خطرناک (IMDG/ADR) معمولا درج نمی‌شود", "استعلام فنی"),
    ("decision_maker", "تصمیم‌گیرنده حمل در منابع عمومی نیست", "لینکدین (دستی) یا دفتر مرکزی"),
    ("payment_currency_terms", "شرایط پرداخت و ارز عمومی نیست", "پرسش در اولین تماس"),
]
MODE_FOR_INDUSTRY = {"petrochemical": "sea", "steel": "sea", "mining": "sea", "construction": "road",
                     "agri": "road", "industrial": "road"}


def _pick(signals, attr):
    for s in sorted(signals, key=lambda x: -x.reliability):
        v = getattr(s, attr)
        if v:
            return v, s
    return None, None


def build_lead(company_key: str, company_name: str | None, signals: list, observations: list[Observation],
               registry: Registry, sanctions_result: dict, today: date,
               broker_hashes=frozenset(), broker_phones=frozenset(), sector_obs=(),
               trade_flows=frozenset(), probability_fn=None) -> dict:
    nid = next((s.national_id for s in signals if s.national_id), None)
    rec, sim = registry.match(company_name, nid)
    rec: RegistryRecord | None
    obs_groups = {o.source_group for o in observations} - NON_COMPANY_GROUPS
    # H6 (foreign buying request) is confirmed by mirror trade data for the same HS4 and buyer country
    if any(s.code == "H6" and s.hs4 and (s.hs4, s.destination_country) in trade_flows for s in signals):
        obs_groups.add("customs")
    v = verify(signals, rec, rec.ref_url if rec else "", obs_groups, today, broker_hashes, broker_phones)

    hard = [s for s in signals if not is_stale(s, today)]
    hard_verified = bool(hard) and v.level in ("V2", "V3") and not v.rejected
    hs4, _ = _pick(signals, "hs4")
    obs = list(observations)
    if hs4:
        o4 = i4_seasonal(hs4, today)
        if o4:
            obs.append(o4)
    scopes = company_scopes(signals, rec.activity if rec else None)
    headwinds = []
    for so in sector_obs:
        if (so.scope_type, so.scope_value) in scopes:
            if so.polarity > 0:
                obs.append(so.obs)
            elif (today - so.obs.observed_at).days <= 180:
                headwinds.append({"code": so.obs.code, "scope": f"{so.scope_type}:{so.scope_value}",
                                  "note": so.note, "ref": so.obs.evidence_ref,
                                  "observed_at": so.obs.observed_at.isoformat()})
    sc = score_company(obs, today, hard_verified, {s.source_group for s in signals})
    factor = 1.0
    if headwinds:
        factor = max(HEADWIND_FLOOR, HEADWIND_FACTOR ** len({h["scope"] + h["code"] for h in headwinds}))
        sc.demand_score = round(sc.demand_score * factor, 1)
        from .scoring import classify
        sc.demand_class = classify(sc.demand_score, hard_verified and not sc.diversity_capped)

    demand_type = "immediate" if hard else "potential"
    # Section 2 vs 3: a verified immediate signal is demand that already exists, so it is
    # "definite" on its own; the forecast thresholds (S >= 70 + hard signal) apply to potential demand.
    demand_class = "definite" if (demand_type == "immediate" and hard_verified) else sc.demand_class
    window = sc.ship_window.to_dict() if sc.ship_window else None
    if demand_type == "immediate":
        days = min(IMMEDIATE_WINDOW_DAYS.get(s.code, 30) for s in hard)
        window = {"from": today.isoformat(), "to": (today + timedelta(days=days)).isoformat(),
                  "basis": sorted({s.code for s in hard}), "uncertain": False}

    commodity, _ = _pick(signals, "commodity")
    industry, _ = _pick(signals, "industry")
    qty, qsig = _pick(signals, "qty_value")
    exit_point, _ = _pick(signals, "exit_point")
    dest, _ = _pick(signals, "destination_country")
    mode, _ = _pick(signals, "mode_hint")
    inc, _ = _pick(signals, "incoterm")
    phones = sorted({p for s in signals for p in s.phones})
    origin = rec.city if rec and rec.city else None

    sanc = sanctions_result.get("result", "not_checked")
    flags = set()
    if not rec:
        flags.add("no_registry_match")
    if sanc != "no_match":
        flags.add("sanctions_pending")
    if v.suspected_broker:
        flags.add("suspected_broker")
    if len(sc.source_groups) < 2:
        flags.add("single_source_group")
    if not qty:
        flags.add("qty_unknown")
    if not exit_point and not origin:
        flags.add("origin_or_exit_unknown")
    if v.stale:
        flags.add("stale")
    if not dest:
        flags.add("destination_unknown")
    if not phones and not (rec and (rec.phone or rec.website)):
        flags.add("no_contact")
    conf, deductions = compute_confidence(flags)

    unknowns = [{"field": f, "reason": r, "action": a} for f, r, a in ALWAYS_UNKNOWN]
    if not qty:
        unknowns.append({"field": "quantity", "reason": "تناژ در منابع ذکر نشده", "action": "استعلام تلفنی"})
    if not dest:
        unknowns.append({"field": "destination_country", "reason": "مقصد در منابع ذکر نشده", "action": "استعلام تلفنی"})

    evidence = [s.evidence() for s in signals] + [
        {"signal_code": o.code, "source": o.source_group, "url": o.evidence_ref, "published_at": o.observed_at.isoformat(),
         "retrieved_at": None, "extract": o.note, "source_reliability": o.reliability} for o in obs]

    lead = {
        "lead_id": "LD-" + hashlib.sha1(company_key.encode()).hexdigest()[:10],  # stable across runs
        "created_at": today.isoformat(),
        "shipper": {"company_name": rec.name if rec else company_name, "national_id": rec.national_id if rec else nid,
                    "registry_similarity": sim, "industry": industry, "contact_phones_public": phones,
                    "website": rec.website if rec else None},
        "demand": {"demand_type": demand_type, "demand_class": demand_class, "demand_score": sc.demand_score,
                   "score_breakdown": {"contributions": sc.contributions, "synergy_bonus": sc.synergy_bonus,
                                       "hard_signal_bonus": sc.hard_bonus, "diversity_capped": sc.diversity_capped,
                                       "headwind_factor": factor, "headwinds": headwinds},
                   "ship_window": window},
        "cargo": {"commodity": commodity, "hs_code": hs4,
                  "qty": {"value": qty, "unit": qsig.qty_unit if qsig else None, "estimated": False} if qty else None,
                  "origin_city": origin, "origin_city_basis": "شهر ثبت شرکت (جایگزین مبدا واقعی)" if origin else None,
                  "exit_point": exit_point, "destination_country": dest,
                  "suggested_mode": mode or MODE_FOR_INDUSTRY.get(industry or ""), "incoterm_observed": inc},
        "evidence": evidence,
        "verification": {"level": v.level, "checks": v.checks, "rejected": v.rejected, "reject_reasons": v.reject_reasons,
                         "sanctions_screening": sanctions_result},
        "confidence": {"score": conf, "deductions": deductions},
        "unknowns": unknowns,
        "ready_for_sales": v.level in ("V2", "V3") and sanc == "no_match" and not v.rejected,
    }
    if probability_fn is not None:
        lead["demand"]["probability_6m"] = probability_fn(lead)
    return lead
