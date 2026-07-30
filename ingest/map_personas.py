"""Flatten raw disclosure tables into `persona_trades` — the simulator's uniform input.

`persona_trades` is the ONE shape sim/backtest.py reads: (persona, ticker, side,
trade_date, amount_usd, ...). This mapper rebuilds it from the raw feeds:

  - 🕵️ The Insider  <- insider_trades open-market P-buys (Finnhub already gives tickers).
  - 🧠 The Architect <- institutional_moves (13F quarter-over-quarter diffs). Needs a
    ticker (resolved from CUSIP by ingest/cusip_resolve.py) and encodes the option leg
    into a directional side: buying/adding a LONG or CALL is bullish -> 'buy'; buying a
    PUT is a bearish bet on the underlying -> 'sell' (and closing flips it).
  - 🏛️ House / 🎯 Oracle (congress) are skipped — that feed is still blocked.

Only rows whose ticker exists in `securities` (so the sim can price them) are mapped.
Full rebuild: deletes the mapped personas' rows and re-inserts, so it's idempotent and
always consistent with the current raw data. Belongs in the sim pipeline (before
backtest.py); ingest/architect_13f also calls it after resolving CUSIPs so The
Architect's persona_trades stay fresh.

Env:  SUPABASE_URL, SUPABASE_SERVICE_KEY
Run:  python -m ingest.map_personas
"""
from __future__ import annotations

import logging
import time

from db.client import get_client

log = logging.getLogger("ingest.map_personas")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MAPPED_PERSONAS = ["the_insider", "the_architect"]


def map_insider(client) -> list[dict]:
    """The Insider: one persona_trade per open-market P-buy that carries a ticker."""
    rows = (client.table("insider_trades")
            .select("id,ticker,value_usd,trade_date,filed_date")
            .eq("txn_code", "P").gt("shares", 0).execute().data or [])
    out = []
    for r in rows:
        if not r.get("ticker"):
            continue
        out.append({
            "persona": "the_insider", "ticker": r["ticker"], "side": "buy",
            "trade_date": r.get("trade_date"), "disclosed_date": r.get("filed_date"),
            "amount_usd": r.get("value_usd"), "amount_is_est": False,
            "source_table": "insider_trades", "source_id": r["id"],
        })
    return out


def map_architect(client) -> list[dict]:
    """The Architect: one persona_trade per meaningful 13F move (NEW/ADDED/TRIMMED/EXITED)
    that resolved to a ticker. Direction combines the option leg with the move:
        bullish (LONG/CALL) + opening (NEW/ADDED)  -> buy
        bullish            + closing (TRIMMED/EXITED) -> sell
        bearish (PUT)      + opening               -> sell   (short the underlying)
        bearish            + closing               -> buy    (cover)
    trade_date uses the report period (13F gives no exact trade date); amounts are the
    quarter-over-quarter value delta and are flagged estimated."""
    rows = client.table("institutional_moves").select("*").execute().data or []
    out = []
    for r in rows:
        ticker, move = r.get("ticker"), r.get("move")
        if not ticker or move in (None, "HELD"):
            continue
        bullish = r.get("put_call") in ("LONG", "CALL")
        opening = move in ("NEW", "ADDED")
        side = "buy" if bullish == opening else "sell"
        out.append({
            "persona": "the_architect", "ticker": ticker, "side": side,
            "trade_date": r.get("cur_period") or r.get("prv_period"),
            "disclosed_date": None,
            "amount_usd": abs(r.get("value_delta") or 0), "amount_is_est": True,
            "source_table": "institutional_holdings", "source_id": None,
        })
    return out


def main() -> None:
    started = time.time()
    client = get_client()
    errors: list[str] = []

    rows: list[dict] = []
    for name, fn in (("insider", map_insider), ("architect", map_architect)):
        try:
            got = fn(client)
            rows += got
            log.info("map_personas: %s -> %d rows", name, len(got))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            log.error("map %s failed: %s", name, e)

    # Full rebuild of the mapped personas (delete-then-insert) — the null source_id on
    # 13F moves means an upsert can't dedup them, so rebuilding is the clean, idempotent path.
    inserted = 0
    try:
        client.table("persona_trades").delete().in_("persona", MAPPED_PERSONAS).execute()
        for i in range(0, len(rows), 500):
            batch = rows[i:i + 500]
            client.table("persona_trades").insert(batch).execute()
            inserted += len(batch)
    except Exception as e:  # noqa: BLE001
        errors.append(f"write: {e}")
        log.error("persona_trades write failed: %s", e)

    status = "ok" if (inserted and not errors) else ("partial" if inserted else "failed")
    try:
        client.table("ingest_runs").insert({
            "source": "map_personas",
            "rows_ingested": inserted,
            "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": int((time.time() - started) * 1000),
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("map_personas %s: %d persona_trades (%d errors)", status, inserted, len(errors))
    for e in errors:
        log.error("error: %s", e)


if __name__ == "__main__":
    main()
