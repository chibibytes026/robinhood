"""Nightly news ingestion for the persona bots.

Runs headless on Railway (cron) — no browser, all HTTP, no brokerage credentials.
Pulls free news from Finnhub: general market news + per-watchlist-ticker company news.

Normalizes and upserts into Supabase `market_news` (dedup on url), then writes an
`ingest_runs` audit row. The personas read `market_news` at runtime via MCP.

NOTE: GDELT was removed — it blocks Railway's datacenter IP (429 on the first
request regardless of spacing). A keyless, server-friendly thematic-news source for
the non-finance watches (energy/war/media/mergers) is TBD; see the repo notes.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   (required)
  FINNHUB_API_KEY                      (optional; Finnhub sources skipped if unset)
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
HTTP_TIMEOUT = 30

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


def _utc_iso(unix_ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
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
    days = int(os.environ.get("NEWS_LOOKBACK_DAYS", "1"))

    rows: list[dict] = []
    errors: list[str] = []

    log.info("news ingest starting; finnhub_key=%s lookback=%sd", bool(token), days)
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

    rows = dedup(rows)

    inserted = 0
    try:
        inserted = upsert(client, rows)
    except Exception as e:  # noqa: BLE001
        errors.append(f"upsert: {e}")
        log.error("upsert failed: %s", e)

    # Retention: keep a rolling ~3-month window. Anything older is deleted every
    # night, so even backfilled rows never persist past the window.
    retention_days = int(os.environ.get("NEWS_RETENTION_DAYS", "90"))
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        res = client.table("market_news").delete().lt("published_at", cutoff).execute()
        log.info("retention: deleted %d rows older than %d days", len(res.data or []), retention_days)
    except Exception as e:  # noqa: BLE001
        errors.append(f"retention: {e}")
        log.warning("retention delete failed: %s", e)

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
