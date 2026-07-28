"""Nightly news ingestion for the persona bots.

Runs headless on Railway (cron) — no browser, all HTTP, no brokerage credentials.
Pulls free news:
  - Finnhub  : general market news + per-watchlist-ticker company news (free tier, key)
  - GDELT    : thematic world news across the seven watches (energy, war, power, ai,
               media, mergers) — keyless, free.

Normalizes and upserts into Supabase `market_news` (dedup on url), then writes an
`ingest_runs` audit row. The personas read `market_news` at runtime via MCP.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   (required)
  FINNHUB_API_KEY                      (optional; Finnhub sources skipped if unset)
  NEWS_TIMESPAN        default "24H"    (GDELT lookback window)
  NEWS_LOOKBACK_DAYS   default "1"      (Finnhub company-news lookback)

Run:  python -m ingest.news
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from db.client import get_client

log = logging.getLogger("ingest.news")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FINNHUB_BASE = "https://finnhub.io/api/v1"
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
HTTP_TIMEOUT = 30
GDELT_MAX = 50

# Watchlist tickers (mirror the securities seed). Company news is pulled per ticker.
WATCHLIST = [
    "NVDA", "VST", "BE", "CRWV", "CEG",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO",
    "SPY", "VOO",
]

# Loose watch tag per ticker (news is thematic, not a trade — best-effort).
TICKER_WATCH = {
    "NVDA": "ai", "AVGO": "ai", "CRWV": "ai", "MSFT": "ai",
    "GOOGL": "ai", "META": "ai", "AMZN": "ai",
    "VST": "power", "CEG": "power", "BE": "power",
    "AAPL": "stocks", "SPY": "stocks", "VOO": "stocks",
}

# GDELT full-text queries per watch. English-only; recency handled by timespan.
# Halved from 6 to 3 requests to stay under GDELT's aggressive rate limit — the
# overlapping watches are merged so 3 calls still span energy/power/war/media/
# mergers. Finnhub already covers the AI/stocks side via ticker news. Re-expand
# once we confirm this pulls cleanly.
GDELT_QUERIES = {
    "energy":  '(oil OR OPEC OR crude OR "natural gas" OR electricity OR "power grid" OR nuclear)',
    "war":     '(war OR geopolitics OR military OR conflict OR ceasefire)',
    "mergers": '(merger OR acquisition OR takeover OR buyout OR streaming OR Hollywood)',
}
GDELT_UA = "robinhood-personas/1.0 (market research; jj@dulcenochemedia.com)"
GDELT_SLEEP = 6.0  # seconds between GDELT calls (its limit is ~1 req / 5s)


def _utc_iso(unix_ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _gdelt_date(seen: str) -> str | None:
    # GDELT seendate looks like "20260728T183000Z"
    try:
        return datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def fetch_finnhub_general(token: str) -> list[dict]:
    r = requests.get(
        f"{FINNHUB_BASE}/news",
        params={"category": "general", "token": token},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for a in r.json() or []:
        if not a.get("url"):
            continue
        out.append({
            "watch": "stocks",
            "ticker": None,
            "headline": a.get("headline"),
            "summary": a.get("summary"),
            "source": a.get("source"),
            "url": a.get("url"),
            "published_at": _utc_iso(a.get("datetime")),
            "source_api": "finnhub_general",
        })
    return out


def fetch_finnhub_company(token: str, symbol: str, days: int) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    frm = today - timedelta(days=days)
    r = requests.get(
        f"{FINNHUB_BASE}/company-news",
        params={"symbol": symbol, "from": frm.isoformat(), "to": today.isoformat(), "token": token},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for a in r.json() or []:
        if not a.get("url"):
            continue
        out.append({
            "watch": TICKER_WATCH.get(symbol),
            "ticker": symbol,
            "headline": a.get("headline"),
            "summary": a.get("summary"),
            "source": a.get("source"),
            "url": a.get("url"),
            "published_at": _utc_iso(a.get("datetime")),
            "source_api": "finnhub_company",
        })
    return out


def fetch_gdelt(watch: str, query: str, timespan: str) -> list[dict]:
    params = {
        "query": f"{query} sourcelang:eng",
        "mode": "ArtList",
        "maxrecords": GDELT_MAX,
        "timespan": timespan,
        "sort": "DateDesc",
        "format": "json",
    }
    # GDELT 429s aggressively; identify with a UA and retry once after a longer wait.
    r = requests.get(GDELT_DOC, params=params, headers={"User-Agent": GDELT_UA}, timeout=HTTP_TIMEOUT)
    if r.status_code == 429:
        time.sleep(12)
        r = requests.get(GDELT_DOC, params=params, headers={"User-Agent": GDELT_UA}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    out = []
    for a in (r.json() or {}).get("articles", []):
        if not a.get("url"):
            continue
        out.append({
            "watch": watch,
            "ticker": None,
            "headline": a.get("title"),
            "summary": None,
            "source": a.get("domain"),
            "url": a.get("url"),
            "published_at": _gdelt_date(a.get("seendate")),
            "source_api": "gdelt",
        })
    return out


def dedup(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        url = row.get("url")
        if not url or url in seen or not row.get("headline"):
            continue
        seen.add(url)
        out.append(row)
    return out


def upsert(client, rows: list[dict]) -> int:
    n = 0
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        client.table("market_news").upsert(
            batch, on_conflict="url", ignore_duplicates=True
        ).execute()
        n += len(batch)
    return n


def main() -> None:
    started = time.time()
    client = get_client()
    token = os.environ.get("FINNHUB_API_KEY")
    timespan = os.environ.get("NEWS_TIMESPAN", "24H")
    days = int(os.environ.get("NEWS_LOOKBACK_DAYS", "1"))

    rows: list[dict] = []
    errors: list[str] = []

    log.info("news ingest starting; finnhub_key=%s timespan=%s lookback=%sd",
             bool(token), timespan, days)
    try:
        probe = client.table("securities").select("ticker").limit(1).execute()
        log.info("supabase reachable; securities probe rows=%d", len(probe.data or []))
    except Exception as e:  # noqa: BLE001
        errors.append(f"supabase_probe: {e}")
        log.error("SUPABASE PROBE FAILED: %s", e)

    # --- Finnhub (finance + per-ticker) ---
    if token:
        try:
            rows += fetch_finnhub_general(token)
        except Exception as e:  # noqa: BLE001
            errors.append(f"finnhub_general: {e}")
            log.warning("finnhub general failed: %s", e)
        for sym in WATCHLIST:
            try:
                rows += fetch_finnhub_company(token, sym, days)
                time.sleep(1.1)  # respect free-tier ~60 req/min
            except Exception as e:  # noqa: BLE001
                errors.append(f"finnhub_company:{sym}: {e}")
                log.warning("finnhub company %s failed: %s", sym, e)
    else:
        log.warning("FINNHUB_API_KEY unset — skipping Finnhub sources")
        errors.append("finnhub: FINNHUB_API_KEY unset")

    # --- GDELT (thematic, keyless) ---
    for watch, query in GDELT_QUERIES.items():
        try:
            rows += fetch_gdelt(watch, query, timespan)
            time.sleep(GDELT_SLEEP)  # stay under GDELT's rate limit
        except Exception as e:  # noqa: BLE001
            errors.append(f"gdelt:{watch}: {e}")
            log.warning("gdelt %s failed: %s", watch, e)

    rows = dedup(rows)

    inserted = 0
    try:
        inserted = upsert(client, rows)
    except Exception as e:  # noqa: BLE001
        errors.append(f"upsert: {e}")
        log.error("upsert failed: %s", e)

    if inserted and not errors:
        status = "ok"
    elif inserted:
        status = "partial"
    else:
        status = "failed"

    duration_ms = int((time.time() - started) * 1000)
    try:
        client.table("ingest_runs").insert({
            "source": "news",
            "rows_ingested": inserted,
            "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": duration_ms,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info(
        "news ingest %s: %d rows upserted in %d ms (%d source errors)",
        status, inserted, duration_ms, len(errors),
    )
    for e in errors:
        log.error("error: %s", e)
    if inserted == 0:
        # Surface a no-op run as a FAILED deployment so it isn't silently green.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
