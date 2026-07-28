"""Finnhub insider-transactions ingester (SEC Form 4).

Relevance test + first insider feed. Pulls insider transactions for every
watchlist ticker plus any we've ever traded, into `insider_trades`. Reveals how
relevant the data is: US operating companies should have rows; ETFs (SPY/VOO) and
foreign ADRs (SONY) should return nothing (no Form 4 filers).

Free tier note: Finnhub returns the most recent ~top-25 insider transactions per
symbol and does NOT include the insider's title/relationship (SEC Form 4 has it;
this endpoint omits it), so `title` is left null — a real limitation for the
"CEO/CFO > director" weighting.

Runs headless on Railway (same pattern as ingest/news.py). Env: SUPABASE_URL,
SUPABASE_SERVICE_KEY, FINNHUB_API_KEY.  Run: python -m ingest.insider
"""
from __future__ import annotations

import logging
import os
import time

import requests

from db.client import get_client

log = logging.getLogger("ingest.insider")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FINNHUB_BASE = "https://finnhub.io/api/v1"
HTTP_TIMEOUT = 30

# Watchlist tickers + everything we've ever bought/sold in the agentic account.
SYMBOLS = [
    "NVDA", "VST", "BE", "CRWV", "CEG",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO",
    "VOO", "SPY",          # ETFs — expected: no insider data
    "SONY",                # foreign ADR — expected: no Form 4 data
]


def fetch_insider(token: str, symbol: str) -> list[dict]:
    r = requests.get(
        f"{FINNHUB_BASE}/stock/insider-transactions",
        params={"symbol": symbol, "token": token},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return (r.json() or {}).get("data", []) or []


def to_rows(symbol: str, data: list[dict]) -> list[dict]:
    out = []
    for a in data:
        shares = a.get("change")            # signed share delta (+buy / -sell)
        price = a.get("transactionPrice")
        value = (shares * price) if (shares is not None and price) else None
        out.append({
            "ticker": symbol,
            "insider_name": a.get("name"),
            "title": None,                  # Finnhub omits relationship/title
            "txn_code": a.get("transactionCode"),
            "shares": shares,
            "price": price,
            "value_usd": value,
            "trade_date": a.get("transactionDate"),
            "filed_date": a.get("filingDate"),
            "source": "finnhub",
        })
    return out


def ensure_securities(client, symbols: list[str]) -> None:
    # insider_trades.ticker FKs to securities — make sure every symbol exists first.
    client.table("securities").upsert(
        [{"ticker": s} for s in symbols], on_conflict="ticker", ignore_duplicates=True
    ).execute()


def main() -> None:
    started = time.time()
    client = get_client()
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        raise SystemExit("FINNHUB_API_KEY unset")

    ensure_securities(client, SYMBOLS)

    total = 0
    per_ticker: dict[str, int] = {}
    all_rows: list[dict] = []
    errors: list[str] = []

    for sym in SYMBOLS:
        try:
            data = fetch_insider(token, sym)
            rows = to_rows(sym, data)
            per_ticker[sym] = len(rows)
            all_rows += rows
            if rows:
                client.table("insider_trades").upsert(
                    rows,
                    on_conflict="ticker,insider_name,trade_date,txn_code,shares",
                    ignore_duplicates=True,
                ).execute()
                total += len(rows)
            log.info("insider %-5s -> %d transactions", sym, len(rows))
            time.sleep(1.1)  # free-tier ~60 req/min
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sym}: {e}")
            log.warning("insider %s failed: %s", sym, e)

    # Relevance summary — which tickers actually carry insider data.
    have = sorted([s for s, n in per_ticker.items() if n], key=lambda s: -per_ticker[s])
    none = [s for s, n in per_ticker.items() if not n]
    log.info("RELEVANCE: %d/%d symbols have insider data", len(have), len(SYMBOLS))
    log.info("  with data : %s", ", ".join(f"{s}={per_ticker[s]}" for s in have))
    log.info("  empty     : %s", ", ".join(none))

    # The daily report is PURCHASES only (code 'P', positive shares) — the real
    # conviction tell. Everything else (S/A/M/F) stays in the raw table, unused.
    buys = [r for r in all_rows if r.get("txn_code") == "P" and (r.get("shares") or 0) > 0]
    log.info("PURCHASES (P): %d buys across %d tickers",
             len(buys), len({r["ticker"] for r in buys}))
    for r in sorted(buys, key=lambda x: (x.get("trade_date") or ""), reverse=True)[:25]:
        log.info("  BUY %-5s %s  +%s sh @ %s  ($%s)  %s",
                 r["ticker"], r.get("insider_name"), r.get("shares"),
                 r.get("price"), r.get("value_usd"), r.get("trade_date"))

    status = "ok" if not errors else ("partial" if total else "failed")
    duration_ms = int((time.time() - started) * 1000)
    try:
        client.table("ingest_runs").insert({
            "source": "insider",
            "rows_ingested": total,
            "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": duration_ms,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("insider ingest %s: %d rows in %d ms", status, total, duration_ms)


if __name__ == "__main__":
    main()
