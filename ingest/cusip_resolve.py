"""OpenFIGI CUSIP->ticker resolver for The Architect's 13F holdings.

13F filings (`institutional_holdings`) identify securities by CUSIP only; the
simulator prices by TICKER (`price_history`). This bridges the two via OpenFIGI
(Bloomberg's free CUSIP->ticker API — no key needed at our volume), then:

  1. Upserts each resolved ticker into `securities` (tagged '🧠 Architect 13F') so
     ingest/prices.py backfills its price_history automatically — every ingester
     reads its universe from `securities`, so no new price feed is needed.
  2. Stamps `institutional_holdings.ticker` for the matching CUSIPs (the FK requires
     the ticker to exist in `securities` first — hence step 1 runs first).

CUSIPs are stable, so this only does work for CUSIPs not yet resolved — cheap to run
on every 13F cron. Usually invoked by ingest/architect_13f at the end of its run.

⚠️ First Railway run: confirm api.openfigi.com is reachable (it isn't the
datacenter-IP-blocking kind, unlike Finnhub/GDELT, so it should be fine).

Env:  SUPABASE_URL, SUPABASE_SERVICE_KEY   (required)
      OPENFIGI_API_KEY   optional          (raises the rate limit; unneeded at ~37 CUSIPs)
Run:  python -m ingest.cusip_resolve
"""
from __future__ import annotations

import logging
import os
import time

import requests

from db.client import get_client

log = logging.getLogger("ingest.cusip_resolve")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
HTTP_TIMEOUT = 30
BATCH = 10                        # OpenFIGI allows 10 jobs/request without an API key
ARCHITECT_TAG = "🧠 Architect 13F"


def _unresolved_cusips(client) -> list[str]:
    rows = (client.table("institutional_holdings")
            .select("cusip").is_("ticker", "null").execute().data or [])
    return sorted({r["cusip"] for r in rows if r.get("cusip")})


def _openfigi_map(cusips: list[str]) -> dict[str, dict]:
    """CUSIP -> {ticker, name}, preferring the US listing. Silently skips anything
    OpenFIGI can't map to a US-listed symbol (foreign-only names we can't price)."""
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("OPENFIGI_API_KEY")
    if key:
        headers["X-OPENFIGI-APIKEY"] = key

    out: dict[str, dict] = {}
    for i in range(0, len(cusips), BATCH):
        chunk = cusips[i:i + BATCH]
        jobs = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
        r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code == 429:                 # rate limited — back off once and retry
            time.sleep(6)
            r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for cusip, res in zip(chunk, r.json()):
            data = (res or {}).get("data") or []
            if data and data[0].get("ticker"):
                out[cusip] = {
                    "ticker": data[0]["ticker"].upper().replace("/", "-"),  # BRK/B -> BRK-B (Yahoo)
                    "name": data[0].get("name"),
                }
        time.sleep(1.0 if not key else 0.3)      # free tier ~25 req/min
    return out


def resolve(client) -> int:
    """Resolve unmapped CUSIPs; expand `securities`; stamp holdings. Returns # resolved."""
    cusips = _unresolved_cusips(client)
    if not cusips:
        log.info("cusip_resolve: no unresolved CUSIPs")
        return 0

    log.info("cusip_resolve: resolving %d CUSIPs via OpenFIGI", len(cusips))
    mapping = _openfigi_map(cusips)
    log.info("cusip_resolve: OpenFIGI mapped %d/%d to a US ticker", len(mapping), len(cusips))

    # 1) securities first (institutional_holdings.ticker FK -> securities.ticker).
    #    ignore_duplicates keeps existing rows (e.g. NVDA/AVGO keep their Robinhood tag).
    for m in mapping.values():
        client.table("securities").upsert(
            {"ticker": m["ticker"], "name": m.get("name"),
             "watchlist": ARCHITECT_TAG, "form4_eligible": False},
            on_conflict="ticker", ignore_duplicates=True,
        ).execute()

    # 2) stamp the holdings so the moves view / mapper can expose a ticker.
    stamped = 0
    for cusip, m in mapping.items():
        res = (client.table("institutional_holdings")
               .update({"ticker": m["ticker"]}).eq("cusip", cusip).execute())
        stamped += len(res.data or [])

    log.info("cusip_resolve: added/kept %d securities, stamped %d holdings", len(mapping), stamped)
    return len(mapping)


def main() -> None:
    started = time.time()
    client = get_client()
    errors: list[str] = []
    resolved = 0
    try:
        resolved = resolve(client)
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))
        log.error("cusip_resolve failed: %s", e)

    try:
        client.table("ingest_runs").insert({
            "source": "cusip_resolve",
            "rows_ingested": resolved,
            "status": "ok" if not errors else "failed",
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": int((time.time() - started) * 1000),
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("cusip_resolve done: %d resolved (%d errors)", resolved, len(errors))
    for e in errors:
        log.error("error: %s", e)


if __name__ == "__main__":
    main()
