"""Daily price-history ingester — the sim's fuel.

Pulls ~3 months of split-adjusted daily OHLCV for the watchlist + traded tickers
(the `securities` table) into `price_history`, trading days only. This is the last
data dependency before the backtest/streak sim can run and flip the backtested
personas (Architect, Insider, and once their feeds land House/Oracle) to live.

Source order (per project decision):
  1. Finnhub `/stock/candle` FIRST (if FINNHUB_API_KEY set). NOTE: free-tier candles
     are RAW (not split-adjusted) and carry no dividends; on many plans they're also
     premium (403). Used only if it actually returns data.
  2. Yahoo chart API fallback (no key) — returns SPLIT-ADJUSTED OHLC + adj_close
     (split+dividend adjusted) + actual dividends + splits in one call. This is the
     source that satisfies "split-adjusted prices" and "real dividends", so in
     practice it's what serves the data.

SPY is included (it's in `securities`) and is the benchmark every persona is scored
against. Dividends are stored when the source provides them (Yahoo does); if only a
no-dividend source is available, the column is left null and the backtest estimates.

Env:  SUPABASE_URL, SUPABASE_SERVICE_KEY        (required)
      FINNHUB_API_KEY                            (optional; tried first for OHLCV)
      PRICE_LOOKBACK_DAYS   default "92"         (~3 months)
      PRICE_RETENTION_DAYS  default "92"         (rolling window; older rows pruned)
Run:  python -m ingest.prices
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import requests

from db.client import get_client

log = logging.getLogger("ingest.prices")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HTTP_TIMEOUT = 30
YAHOO_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
FINNHUB_BASE = "https://finnhub.io/api/v1"


def _watchlist(client) -> list[str]:
    rows = client.table("securities").select("ticker").execute().data or []
    return sorted(r["ticker"] for r in rows if r.get("ticker"))


def _day(unix: int) -> str:
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%Y-%m-%d")


def fetch_finnhub(token: str, ticker: str, p1: int, p2: int) -> list[dict]:
    """Raw daily OHLCV from Finnhub candles. Empty list if premium/blocked/no data."""
    r = requests.get(
        f"{FINNHUB_BASE}/stock/candle",
        params={"symbol": ticker, "resolution": "D", "from": p1, "to": p2, "token": token},
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code != 200:
        return []
    d = r.json() or {}
    if d.get("s") != "ok" or not d.get("c"):
        return []
    out = []
    for i, ts in enumerate(d["t"]):
        out.append({
            "date": _day(ts), "open": d["o"][i], "high": d["h"][i], "low": d["l"][i],
            "close": d["c"][i], "volume": d["v"][i], "adj_close": None, "dividend": None,
            "source": "finnhub",
        })
    return out


def fetch_yahoo(ticker: str, p1: int, p2: int) -> list[dict]:
    """Split-adjusted daily OHLCV + adj_close + dividends from Yahoo. [] on failure."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits")
    req = urllib.request.Request(url, headers={"User-Agent": YAHOO_UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        d = json.loads(resp.read().decode("utf-8", "replace"))
    res = d.get("chart", {}).get("result")
    if not res:
        return []
    res = res[0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    divs = {}
    for v in res.get("events", {}).get("dividends", {}).values():
        divs[_day(v["date"])] = v["amount"]
    out = []
    for i, u in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        dt = _day(u)
        out.append({
            "date": dt, "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
            "close": c, "volume": q["volume"][i],
            "adj_close": (adj[i] if adj and adj[i] is not None else None),
            "dividend": divs.get(dt), "source": "yahoo",
        })
    return out


def ingest_ticker(client, ticker: str, token: str | None, p1: int, p2: int,
                  errors: list[str]) -> int:
    rows: list[dict] = []
    src = None
    if token:                                   # try Finnhub first (per project decision)
        try:
            rows = fetch_finnhub(token, ticker, p1, p2)
            if rows:
                src = "finnhub"
        except Exception as e:                  # noqa: BLE001
            log.info("%s: finnhub candle failed (%s) — falling back to Yahoo", ticker, e)
    if not rows:                                # Yahoo fallback (split-adj + dividends)
        try:
            rows = fetch_yahoo(ticker, p1, p2)
            src = "yahoo"
        except Exception as e:                  # noqa: BLE001
            errors.append(f"{ticker}: {e}")
            log.warning("%s: yahoo failed: %s", ticker, e)
            return 0
    if not rows:
        errors.append(f"{ticker}: no price data from any source")
        return 0
    payload = [{"ticker": ticker, **{k: r[k] for k in
               ("date", "open", "high", "low", "close", "volume", "adj_close", "dividend", "source")}}
               for r in rows]
    client.table("price_history").upsert(payload, on_conflict="ticker,date").execute()
    log.info("%-5s %3d days via %s (%s..%s)", ticker, len(rows), src, rows[0]["date"], rows[-1]["date"])
    return len(rows)


def main() -> None:
    started = time.time()
    client = get_client()
    token = os.environ.get("FINNHUB_API_KEY")
    # Deepened from 92 -> 420 days: backtesting 13F trades (quarterly, ~45-day lag,
    # kept 2 quarters back) needs prices spanning report_period .. report_period + hold.
    lookback = int(os.environ.get("PRICE_LOOKBACK_DAYS", "420"))
    retention = int(os.environ.get("PRICE_RETENTION_DAYS", "420"))
    p2 = int(time.time())
    p1 = p2 - lookback * 86400

    tickers = _watchlist(client)
    log.info("prices: %d tickers, lookback=%dd, finnhub_key=%s", len(tickers), lookback, bool(token))
    total = 0
    errors: list[str] = []
    for t in tickers:
        try:
            total += ingest_ticker(client, t, token, p1, p2, errors)
        except Exception as e:                  # noqa: BLE001
            errors.append(f"{t}: {e}")
            log.warning("%s ingest failed: %s", t, e)
        time.sleep(0.4)                         # be polite to the source

    # Retention: rolling ~3-month window.
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).strftime("%Y-%m-%d")
        res = client.table("price_history").delete().lt("date", cutoff).execute()
        if res.data:
            log.info("retention: pruned %d rows older than %s", len(res.data), cutoff)
    except Exception as e:                       # noqa: BLE001
        errors.append(f"retention: {e}")
        log.warning("retention delete failed: %s", e)

    status = "ok" if (total and not errors) else ("partial" if total else "failed")
    duration_ms = int((time.time() - started) * 1000)
    try:
        client.table("ingest_runs").insert({
            "source": "prices", "rows_ingested": total, "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None, "duration_ms": duration_ms,
        }).execute()
    except Exception as e:                       # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("prices %s: %d rows in %d ms (%d errors)", status, total, duration_ms, len(errors))
    for e in errors:
        log.error("error: %s", e)
    if total == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
