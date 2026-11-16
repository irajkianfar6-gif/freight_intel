"""Sanctions screening through the OpenSanctions matching API.

Needs an API key (env OPENSANCTIONS_API_KEY). Without one every lead stays 'not_checked'
and can never be marked ready for sales. A potential match halts the lead for legal review;
this module does not make a legal determination.
"""
from __future__ import annotations

import os
from datetime import datetime

API_URL = "https://api.opensanctions.org/match/default"
POTENTIAL_MATCH_THRESHOLD = 0.70


def screen(names: list[str], schema: str = "Company", country: str = "ir",
           session=None, api_key: str | None = None, timeout: int = 30) -> dict:
    api_key = api_key or os.environ.get("OPENSANCTIONS_API_KEY")
    checked_at = datetime.utcnow().isoformat(timespec="seconds")
    if not api_key:
        return {"result": "not_checked", "reason": "no API key", "checked_at": checked_at, "hits": []}
    import requests
    s = session or requests.Session()
    queries = {f"q{i}": {"schema": schema, "properties": {"name": [n], "country": [country]}}
               for i, n in enumerate(names) if n}
    try:
        r = s.post(API_URL, json={"queries": queries},
                   headers={"Authorization": f"ApiKey {api_key}"}, timeout=timeout)
        r.raise_for_status()
        responses = r.json().get("responses", {})
    except Exception as e:  # network or API error: never treat as clean
        return {"result": "error", "reason": str(e)[:200], "checked_at": checked_at, "hits": []}
    hits = []
    for q, resp in responses.items():
        for res in resp.get("results", []):
            if res.get("score", 0) >= POTENTIAL_MATCH_THRESHOLD:
                hits.append({"query": q, "id": res.get("id"), "caption": res.get("caption"),
                             "score": res.get("score"), "datasets": res.get("datasets", [])})
    return {"result": "potential_match" if hits else "no_match", "lists": ["OpenSanctions default collection"],
            "checked_at": checked_at, "hits": hits}
