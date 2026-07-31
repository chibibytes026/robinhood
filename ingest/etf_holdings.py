"""ETF-holdings ingester — The Oracle's feed.

Pulls NANC's daily full-book holdings from the fund administrator's public CSV into
`etf_holdings`. NANC is the Unusual Whales Subversive Democratic Trading ETF — it packages
the STOCK-Act disclosures of Democratic members of Congress (Pelosi is the marquee filer).
Shifts in its holdings are The Oracle's indicator; see personas/the_oracle/nanc-restructure.md.

Why this source: the CSV carries real **Shares** and **SharesOutstanding**, so shares-per-unit
(= shares / fund_shares_out) is exact and immune to both price moves and ETF create/redeem — the
clean active-decision signal. Full book (~101 names), clean tickers (no CUSIP resolve). Confirmed
free + headless from Railway on 2026-07-31 (the agent session's egress 403s it; Railway reaches it).

Headless HTTP only (no browser — hard project constraint), same urllib + browser-UA pattern as
ingest/prices.py. Idempotent: upsert on (fund, ticker, as_of_date), so re-running a day is a no-op
and a non-trading day (stale CSV Date) never fabricates a move.

Env:  SUPABASE_URL, SUPABASE_SERVICE_KEY        (required)
      ETF_RETENTION_DAYS   default "420"        (rolling window; older snapshots pruned)
Run:  python -m ingest.etf_holdings
"""
from __future__ import annotations

import csv
import io
import logging
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from db.client import get_client

log = logging.getLogger("ingest.etf_holdings")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HTTP_TIMEOUT = 30
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Fund -> daily holdings CSV (discovered by scripts/probe_nanc_holdings.py). GOP/KRUZ is
# presumably TidalFG_Holdings_GOP.csv at the same path if we ever want the Republican book.
FUNDS = {
    "NANC": "https://subversiveetfs.com/wp-content/uploads/data/TidalFG_Holdings_NANC.csv",
}

# NANC lists some names under a share class we don't track (e.g. Alphabet as GOOG); map them to
# the ticker `securities`/`price_history` use so the universe join and the backtest line up.
TICKER_ALIASES = {"GOOG": "GOOGL"}


def _num(v: str | None) -> float | None:
    """Parse a CSV cell to float: strip %, commas, whitespace. None if blank/unparseable."""
    if v is None:
        return None
    s = v.strip().replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(v: str | None) -> str | None:
    """CSV 'MM/DD/YYYY' -> ISO 'YYYY-MM-DD'."""
    if not v:
        return None
    try:
        return datetime.strptime(v.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_csv(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8-sig", "replace")


def parse_rows(fund: str, text: str) -> list[dict]:
    """CSV -> one dict per holding, ticker-normalized and merged by ticker within the snapshot.

    Merging matters because an alias can collapse two rows onto one ticker (e.g. GOOG + GOOGL ->
    GOOGL): sum shares/market_value/weight, keep the shared fund_shares_out.
    """
    reader = csv.DictReader(io.StringIO(text))
    merged: dict[tuple, dict] = {}
    for r in reader:
        raw_tkr = (r.get("StockTicker") or "").strip().upper()
        if not raw_tkr:                       # cash / non-equity lines carry no ticker
            continue
        tkr = TICKER_ALIASES.get(raw_tkr, raw_tkr)
        as_of = _date(r.get("Date"))
        if not as_of:
            continue
        key = (fund, tkr, as_of)
        shares = _num(r.get("Shares")) or 0.0
        mv = _num(r.get("MarketValue")) or 0.0
        weight = _num(r.get("Weightings")) or 0.0
        if key in merged:                     # alias collision -> accumulate
            m = merged[key]
            m["shares"] += shares
            m["market_value"] += mv
            m["weight_pct"] += weight
        else:
            merged[key] = {
                "fund": fund, "ticker": tkr, "cusip": (r.get("CUSIP") or "").strip() or None,
                "as_of_date": as_of, "shares": shares,
                "fund_shares_out": _num(r.get("SharesOutstanding")),
                "weight_pct": weight, "market_value": mv,
            }
    return list(merged.values())


def ingest_fund(client, fund: str, url: str, errors: list[str]) -> tuple[int, str | None]:
    """Fetch + upsert one fund's snapshot. Returns (rows_written, as_of_date)."""
    try:
        text = fetch_csv(url)
    except Exception as e:                    # noqa: BLE001
        errors.append(f"{fund} fetch: {e}")
        log.warning("%s fetch failed: %s", fund, e)
        return 0, None
    rows = parse_rows(fund, text)
    if not rows:
        errors.append(f"{fund}: parsed 0 rows (CSV format changed? check {url})")
        log.warning("%s: parsed 0 holdings", fund)
        return 0, None
    as_of = rows[0]["as_of_date"]
    try:
        client.table("etf_holdings").upsert(rows, on_conflict="fund,ticker,as_of_date").execute()
    except Exception as e:                    # noqa: BLE001
        errors.append(f"{fund} write: {e}")
        log.error("%s write failed: %s", fund, e)
        return 0, as_of
    log.info("%s: %d holdings upserted, as-of %s", fund, len(rows), as_of)
    return len(rows), as_of


def main() -> None:
    started = time.time()
    client = get_client()
    retention = int(os.environ.get("ETF_RETENTION_DAYS", "420"))
    errors: list[str] = []
    total = 0

    for fund, url in FUNDS.items():
        n, _ = ingest_fund(client, fund, url, errors)
        total += n

    # Retention: rolling window (a signal series — keep long enough for QoQ/YoY diffs).
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).strftime("%Y-%m-%d")
        res = client.table("etf_holdings").delete().lt("as_of_date", cutoff).execute()
        if res.data:
            log.info("retention: pruned %d rows older than %s", len(res.data), cutoff)
    except Exception as e:                    # noqa: BLE001
        errors.append(f"retention: {e}")
        log.warning("retention delete failed: %s", e)

    status = "ok" if (total and not errors) else ("partial" if total else "failed")
    try:
        client.table("ingest_runs").insert({
            "source": "etf_holdings", "rows_ingested": total, "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": int((time.time() - started) * 1000),
        }).execute()
    except Exception as e:                    # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("etf_holdings %s: %d rows (%d errors)", status, total, len(errors))
    for e in errors:
        log.error("error: %s", e)
    if total == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
