"""UN Comtrade mirror data: what partner countries report importing FROM Iran.

Iran's own reporting is late, so partner-reported imports (partnerCode=364) are the proxy for
export flows by HS code. Needs a free subscription key from comtradedeveloper.un.org
(env COMTRADE_API_KEY). Used to confirm H6 buying requests and as sector context.
"""
from __future__ import annotations

import os

API = "https://comtradeapi.un.org/data/v1/get/C/{freq}/HS"
IRAN = 364
REPORTERS = {"TR": 792, "IQ": 368, "AF": 4, "PK": 586, "RU": 643, "KZ": 398, "TM": 795, "UZ": 860, "AZ": 31,
             "AM": 51, "GE": 268, "AE": 784, "OM": 512, "QA": 634, "KW": 414, "CN": 156, "IN": 699, "SA": 682,
             "TJ": 762, "KG": 417}


def fetch_mirror(fetcher, reporters: list[str], hs_codes: list[str], period: str, freq: str = "A",
                 api_key: str | None = None) -> list[dict]:
    key = api_key or os.environ.get("COMTRADE_API_KEY")
    if not key:
        raise RuntimeError("COMTRADE_API_KEY is not set")
    params = {"reporterCode": ",".join(str(REPORTERS[r]) for r in reporters if r in REPORTERS),
              "partnerCode": IRAN, "cmdCode": ",".join(hs_codes), "flowCode": "M", "period": period}
    r = fetcher.get(API.format(freq=freq), params=params, headers={"Ocp-Apim-Subscription-Key": key})
    inv = {v: k for k, v in REPORTERS.items()}
    out = []
    for row in r.json().get("data", []) or []:
        out.append({"reporter": inv.get(row.get("reporterCode"), str(row.get("reporterCode"))),
                    "hs": str(row.get("cmdCode")), "period": str(row.get("period")),
                    "value_usd": row.get("primaryValue"), "net_kg": row.get("netWgt")})
    return out
