"""Flatten raw disclosure tables into `persona_trades` — the simulator's uniform input.

`persona_trades` is the ONE shape sim/backtest.py reads: (persona, ticker, side,
trade_date, amount_usd, ...). This mapper rebuilds it from the raw feeds:

  - 🕵️ The Insider  <- insider_trades open-market P-buys (Finnhub already gives tickers).
  - 🧠 The Architect <- institutional_moves (13F quarter-over-quarter diffs). Needs a
    ticker (resolved from CUSIP by ingest/cusip_resolve.py) and encodes the option leg
    into a directional side: buying/adding a LONG or CALL is bullish -> 'buy'; buying a
    PUT is a bearish bet on the underlying -> 'sell' (and closing flips it).
  - 🎯 The Oracle <- the_oracle_candidates (day-over-day shifts in NANC's holdings that pass
    the Oracle's selectivity gates 1-3). This mapper applies gate 4 (rank by conviction,
    top-1 per snapshot, 10-trading-day per-ticker cooldown) and skips the cold-start baseline
    snapshot where every holding looks NEW. See personas/the_oracle/nanc-restructure.md.
  - 🏛️ The House (congress) is skipped — that feed is still blocked.

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

MAPPED_PERSONAS = ["the_insider", "the_architect", "the_oracle"]

ORACLE_FUND = "NANC"
ORACLE_COOLDOWN = 10        # trading days between strikes on the same ticker (gate 4)


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


def _score_snapshot(rows: list[dict]) -> list[dict]:
    """Rank one snapshot's candidates by conviction (gate-4 tie-break within a day).

    score = 0.5*norm(Δ shares-per-unit %) + 0.3*norm(weight) + 0.2*(move==NEW), where norm is
    min-max within the day's survivors. A NEW carries no Δ% (no prior), so on that axis it takes
    the day's max — a brand-new position is max conviction there — plus the 0.2 NEW bump.
    Returns the rows ranked best-first.
    """
    def dsp(c):
        v = c.get("d_spu_pct")
        return float(v) if v is not None else None

    known = [dsp(c) for c in rows if dsp(c) is not None]
    dmax = max(known) if known else 0.0
    ds = [dsp(c) if dsp(c) is not None else dmax for c in rows]
    ws = [float(c.get("weight_pct") or 0) for c in rows]

    def norm(x, xs):
        lo, hi = min(xs), max(xs)
        return 0.5 if hi == lo else (x - lo) / (hi - lo)

    scored = []
    for c, dv, wv in zip(rows, ds, ws):
        is_new = 1.0 if c.get("move") == "NEW" else 0.0
        sc = 0.5 * norm(dv, ds) + 0.3 * norm(wv, ws) + 0.2 * is_new
        scored.append((sc, wv, c.get("ticker") or "", c))
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [c for *_, c in scored]


def map_oracle(client) -> list[dict]:
    """The Oracle: rare, concentrated strikes filtered out of NANC's daily holdings shifts.

    Reads `the_oracle_candidates` (gates 1-3: mega-cap-tech universe, NEW/ADDED, real
    accumulation) and applies gate 4 here: skip the cold-start baseline snapshot (every
    holding looks NEW with no prior), then per snapshot pick the single highest-conviction
    candidate that isn't within the per-ticker cooldown. One long strike per snapshot at most,
    so the Oracle stays rare. trade_date is the disclosure/rebalance date (NOT the real trade
    date — the underlying congressional trade is weeks older), so it's flagged estimated."""
    snap_rows = (client.table("etf_holdings").select("as_of_date")
                 .eq("fund", ORACLE_FUND).order("as_of_date").execute().data or [])
    dates = sorted({r["as_of_date"] for r in snap_rows})
    if len(dates) < 2:                        # need a baseline + at least one comparison day
        return []
    baseline, idx = dates[0], {d: i for i, d in enumerate(dates)}

    cands = client.table("the_oracle_candidates").select("*").execute().data or []
    by_date: dict[str, list[dict]] = {}
    for c in cands:                           # drop the cold-start baseline (all spurious NEWs)
        d = c.get("as_of_date")
        if d and d != baseline and d in idx:
            by_date.setdefault(d, []).append(c)

    last_strike: dict[str, int] = {}
    out: list[dict] = []
    for d in sorted(by_date):                 # chronological, so cooldown is causal
        i = idx[d]
        for c in _score_snapshot(by_date[d]):        # best-first; take the top one off cooldown
            tkr = c.get("ticker")
            li = last_strike.get(tkr)
            if li is not None and (i - li) < ORACLE_COOLDOWN:
                continue
            last_strike[tkr] = i
            out.append({
                "persona": "the_oracle", "ticker": tkr, "side": "buy",
                "trade_date": d, "disclosed_date": d,
                # position size, flagged est — sizing policy is an open decision, and the
                # backtest's %/alpha are invariant to dollar_amount anyway.
                "amount_usd": c.get("market_value"), "amount_is_est": True,
                "source_table": "etf_holdings", "source_id": None,
            })
            break                             # one strike per snapshot
    return out


def main() -> None:
    started = time.time()
    client = get_client()
    errors: list[str] = []

    rows: list[dict] = []
    for name, fn in (("insider", map_insider), ("architect", map_architect),
                     ("oracle", map_oracle)):
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
