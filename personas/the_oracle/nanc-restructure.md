# The Oracle — NANC restructure proposal

**Status: proposal, NOT applied.** Nothing here is in `schema.sql`, the live Supabase
project, or `persona.md` yet. This is a design sketch to review before any ingestion is
written or the voice bible is edited. Conventions match the existing schema (snake_case,
`securities` FK, `timestamptz`, `security_invoker` views, 3-month-style retention where it
fits) and the `the_shutin/data-model.md` proposal format.

---

## The idea (from the user)

The Oracle's data feed — Nancy Pelosi's congressional STOCK Act filings — is **blocked**
(`map_personas.py` skips the congress feed entirely). Instead of scraping individual
filings, track **[NANC](https://finance.yahoo.com/quote/NANC/)** — the *Unusual Whales
Subversive Democratic Trading ETF* — and use **shifts in its holdings as the indicator.**

This is a genuinely good instinct about the **data**, and a fit problem for the **character**.
Both are worked through below.

---

## What NANC actually is (verify the ⚠️ items against the prospectus)

- **Actively-managed ETF** that invests in equities that **sitting Democratic members of
  Congress and/or their families** disclosed buying under the STOCK Act. Marquee name is
  Pelosi, but it is **all Democratic filers aggregated**, not one person.
- **~106 holdings**, tech-heavy mega-cap. Recent top weights: NVDA ~8.3%, GOOGL ~6.3%,
  MSFT ~5.4%, AMAT ~5.0%, AMZN ~4.9%. (Sibling fund KRUZ mirrors Republican filers.) ⚠️ confirm
  current composition — weights drift daily.
- **Holdings disclosed *daily*.** As a transparent active ETF it publishes its full book every
  trading day. This is the whole attraction: **daily** vs. the dead congress scraper and vs.
  13F's 45-day lag. Tickers arrive clean — **no CUSIP resolution** step like the Architect.
- ⚠️ **Equity-only.** NANC holds stock, **not** the long-dated call options (LEAPS) that are the
  archetype's actual signature. Confirm in the prospectus, but this is the crux of the fit
  problem below.

---

## The fit problem: NANC ≠ the Oracle's archetype

The Oracle (see `persona.md`) is **rare, concentrated, mega-cap tech, LEAPS-leveraged,** modeled
on **one** trader's uncanny timing. NANC is the opposite on three axes:

| Oracle archetype | NANC as-is |
|---|---|
| Concentrated — one real position | ~106-name basket |
| LEAPS / long-dated options leverage | Equities only |
| One trader's timing | All Democratic filers, averaged |

Consequences of a naive "Oracle = follow the NANC basket" restructure:

1. **It collides with The House.** The House is already the *index-broad, high-turnover,
   effectively-passive* congress-styled persona. A 106-name congressional basket **is** The
   House's beat. Two personas, one behavior.
2. **It deletes the LEAPS character** — the exact thing that separates "concentrated conviction
   with leverage" from "diversified index."
3. **It averages away the one-trader timing** the Oracle is built on.

So: adopt NANC's **feed**, do **not** adopt NANC's **shape**.

---

## Recommended framing — NANC as universe, Oracle's selectivity as filter (Option B)

Don't copy the basket. Use NANC's **daily holdings deltas** as the candidate universe, and let
the Oracle's defining selectivity be a **filter on top**:

> A rare Oracle "strike" = a **large, high-conviction NANC shift** — a brand-new position, or a
> big increase in shares held — **in a mega-cap tech name**, above a size threshold.

Because NANC contains Pelosi's trades but dilutes them across every Democratic filer, filtering
the basket back down to *concentrated mega-cap tech conviction shifts* effectively **re-isolates
the Pelosi-like signal** inside the aggregate. That preserves:

- **Concentration** (a threshold + top-N cut, not the whole book) → stays distinct from The House.
- **Rarity** ("patience, then the strike" survives — most days there is no qualifying shift).
- **Mega-cap tech** focus.
- **Backtestability** — the simulator prices the **underlying equity** move, which is all it can
  do anyway (it can't price a LEAPS). LEAPS becomes a *note* about how the real pattern expressed
  the same conviction, not something we simulate.

Two alternatives, for the record:

- **Option A — full reposition.** Let the Oracle become the honest "Congress-aggregate tracker"
  and drop the concentration/LEAPS identity. Cleaner data story, but it overwrites the character
  and steps on The House. Not recommended.
- **Option C — new persona.** Leave the Oracle alone (or retire it if congress stays dead) and
  make NANC a *new* persona (e.g. "The Delegate"). Avoids forcing a fit, at the cost of another
  persona to maintain. Viable, but the user asked specifically to restructure the Oracle, and
  Option B honors that.

---

## Applying the Oracle's selectivity — four compounding gates + a rarity throttle

**Chosen: Option B.** NANC touches its book most days; left raw that is dozens of tiny signals —
which *is* The House. Selectivity is what compresses ~106 names × daily churn down to **a handful
of "strikes" per quarter.** Four gates compound, each reproducing one Oracle trait:

| Gate | Rule | Oracle trait it enforces |
|---|---|---|
| **1 — Universe** | `securities.watchlist in ('AI Infra + Power','Mega-Cap Core')`. Excludes `Index Anchor` (VOO/SPY = House turf) and `Water`. | mega-cap tech lane |
| **2 — Direction** | `move in ('NEW','ADDED')` only. Exits/trims are never a strike. | long, concentrated bull bet |
| **3 — Conviction** | `move = 'NEW'` **OR** (`Δ shares-per-unit ≥ +20%` **AND** `weight_pct ≥ 1.0%`). | a *real* position, not drift |
| **4 — Rarity throttle** | rank survivors by conviction score, emit **top-1 per snapshot**, **~10-trading-day per-ticker cooldown**. | rare entries, long silences |

**Why "shares-per-unit" in Gate 3.** It is the only measure immune to *both* failure modes: a name's
weight moves with price (Gate-2 methodology point below), and its raw share count moves with the
ETF's create/redeem (AUM doubles → every line's shares double, no decision made). Dividing each
holding's shares by the fund's total shares outstanding (`fund_shares_out`) neutralizes both, so
`Δ shares-per-unit` is the clean active-decision signal. (Fallback if `fund_shares_out` is
unreliable: decompose Δweight into price effect vs. flow effect and keep the flow.)

**Conviction score** — used only to pick *the* strike among Gate-1–3 survivors (transparent, tunable):

```
score = 0.5·z(Δ shares-per-unit %) + 0.3·z(weight_pct) + 0.2·(move = 'NEW')
```

**Where each gate runs.** Gates 1–3 are set-based → they live in the `the_oracle_candidates` **view**.
Gate 4 (top-1 + cooldown) reaches across dates and dedups → it lives in **`map_oracle()` code**, not
the view.

**The honest limit — selectivity cannot fake timing.** These gates engineer *concentration, rarity,
and lane* — nothing more. Whether the strikes are actually well-timed is what the **backtest**
decides; if they are not, the streak classifier turns the Oracle cold and it de-weights itself.
**Data → State → Voice** holds: selectivity shapes *what* it bets on, never *how confident it sounds.*

---

## The two non-negotiable methodology points

1. **Signal on Δ *shares held*, never Δ *weight %*.** An ETF's weights move every day purely from
   price changes even when nobody traded. Signalling on weight manufactures a fake "strike" every
   time NVDA rallies. The **active decision** is the change in **share count** (or a position
   appearing / disappearing). Store shares; derive weight only as context.
   - Corollary: separate **reconstitution** (NANC actually added/dropped a name) from **price
     drift** and from **creation/redemption scaling** (total shares outstanding of the ETF change,
     scaling every line proportionally — not a stock-level decision). Normalize by looking at each
     holding's share count **per ETF unit**, or flag days with large net create/redeem.

2. **It is a lag-on-a-lag — thematic, never live.** NANC only rebalances *after* STOCK Act
   disclosures surface, and those already lag the trade by weeks. A NANC holdings shift is
   therefore **twice removed** from the actual trade. The existing hard rule ("never present
   delayed/incomplete disclosure as a live signal") applies with extra force. The voice must say
   so.

---

## Data access — the 403 wall applies here too

The issuer/aggregator holdings pages (`subversiveetfs.com`, `stockanalysis.com`, etc.) **403 from
the datacenter IP** — the same block that killed GDELT/Reddit-direct and that 403s Finnhub from
the agent session. Two headless-friendly paths, in priority order:

1. **Finnhub `/etf/holdings`** (`GET /etf/holdings?symbol=NANC`). Finnhub is already wired
   (`FINNHUB_API_KEY`) and reachable **from Railway**. ⚠️ Almost certainly a **premium** endpoint
   — verify on the first Railway call (premium returns `403 / {"error": "...premium..."}`), exactly
   like the doc's other "verify on first call" items. If free/affordable, this is by far the
   cleanest fit — same client, same cron, clean tickers.
2. **Composio-proxied fetch of the issuer's daily holdings file** — the same pattern the Shut-In
   uses for Reddit (`COMPOSIO_API_KEY`, Composio's servers make the request, Railway gets JSON).
   Fallback if Finnhub's holdings endpoint is paywalled. ⚠️ requires locating the canonical daily
   holdings URL (issuer CSV via fund administrator) and confirming it serves through the proxy.

Either way: **pull once per trading day, diff against yesterday's snapshot.** The diff is the
entire signal.

---

## Proposed data model (gated — not applied)

```sql
-- Daily full-book snapshot of NANC holdings. One row per (fund, holding, as_of_date).
-- Small: ~106 rows/day. Keep ~400 days so quarter-over-quarter and YoY diffs are possible;
-- this is a signal series, not raw chatter, so retention is longer than market_news.
create table if not exists etf_holdings (
  id            bigint generated always as identity primary key,
  fund          text not null,                       -- 'NANC' (KRUZ later if wanted)
  ticker        text references securities(ticker),  -- holding symbol (may be null pre-seed)
  as_of_date    date not null,
  shares          numeric,      -- holding's shares held (6dp, no rounding)
  fund_shares_out numeric,      -- the ETF's total shares outstanding on as_of_date (same for
                                --   every row of a snapshot). shares/fund_shares_out = shares-per-
                                --   unit — THE active-decision field, immune to price & create/redeem.
  weight_pct      numeric,      -- context only; do NOT signal on this alone (moves with price)
  market_value    numeric,
  ingested_at     timestamptz default now(),
  unique (fund, ticker, as_of_date)
);

create index if not exists idx_etf_holdings_fund_date on etf_holdings(fund, as_of_date desc);
create index if not exists idx_etf_holdings_ticker on etf_holdings(ticker, as_of_date desc);

-- Snapshot-over-snapshot change in SHARES-PER-UNIT per holding (immune to price & create/redeem).
-- This is the diff that becomes an Oracle candidate. NEW = position appeared; EXITED = disappeared.
create or replace view etf_holdings_delta with (security_invoker = true) as
with snaps as (
  select fund, ticker, as_of_date, shares, weight_pct,
         shares / nullif(fund_shares_out, 0)                          as spu,   -- shares per unit
         lag(shares / nullif(fund_shares_out, 0))
           over (partition by fund, ticker order by as_of_date)       as prev_spu,
         lag(as_of_date)
           over (partition by fund, ticker order by as_of_date)       as prev_date
  from etf_holdings
)
select
  fund, ticker, as_of_date, prev_date, weight_pct, spu, prev_spu,
  (spu - coalesce(prev_spu, 0))                                       as d_spu,
  case when coalesce(prev_spu, 0) = 0 then null
       else round(100 * (spu - prev_spu) / prev_spu, 2) end           as d_spu_pct,  -- % change
  case
    when prev_spu is null or prev_spu = 0   then 'NEW'
    when spu = 0                            then 'EXITED'
    when spu > prev_spu                     then 'ADDED'
    when spu < prev_spu                     then 'TRIMMED'
    else 'HELD'
  end                                                                 as move
from snaps;

-- Gates 1-3 of the Oracle's selectivity (see "Applying the Oracle's selectivity"). The rarity
-- throttle (Gate 4: top-1 per snapshot + per-ticker cooldown) is applied later in map_oracle(),
-- not here. Thresholds are the proposed starting values — tune per Open decision #3.
create or replace view the_oracle_candidates with (security_invoker = true) as
select
  d.*,
  -- conviction score (z-scores computed in map_oracle over the day's survivors; this is the
  -- raw material). NEW gets the structural bump there.
  d.weight_pct as _weight_ctx
from etf_holdings_delta d
join securities s on s.ticker = d.ticker
where d.fund = 'NANC'
  and s.watchlist in ('AI Infra + Power', 'Mega-Cap Core')      -- Gate 1: mega-cap tech lane
  and d.move in ('NEW', 'ADDED')                                -- Gate 2: long striker only
  and (                                                          -- Gate 3: real accumulation
        d.move = 'NEW'
        or (d.d_spu_pct >= 20 and d.weight_pct >= 1.0)
      )
order by d.as_of_date desc, d.weight_pct desc;
```

## How it flows into the existing pipeline

The Oracle rejoins the standard path with **no new simulator work**:

1. `ingest/etf_holdings.py` (new) — daily snapshot into `etf_holdings` (Finnhub or Composio),
   writes an `ingest_runs` audit row like every other feed.
2. `ingest/map_personas.py` — add a `map_oracle()` that reads `the_oracle_candidates` (Gates 1-3),
   **applies Gate 4** (z-score the survivors, add the NEW bump, keep **top-1 per snapshot**, drop any
   ticker struck within the **10-trading-day cooldown**), then emits one `persona_trades` row per
   surviving strike: `persona='the_oracle'`, `side='buy'`, `trade_date = as_of_date` (⚠️ the
   *disclosure/rebalance* date, not the real trade date — `amount_is_est=true`,
   `disclosed_date=as_of_date`). Same delete-then-insert rebuild.
3. `sim/backtest.py` → `sim/streak.py` → `persona_performance` — unchanged. The Oracle finally
   earns a **real, backtested** track record on the underlying equity moves.
4. Voice reads state from `persona_performance` as always. **Data → State → Voice** intact.

---

## Voice / provenance implications (must edit `persona.md` if Option B is chosen)

`persona.md` needs honest edits — do **not** leave it claiming things the new feed can't back:

- **Provenance:** rewrite from "Pelosi's individual filings" to "large conviction shifts in NANC,
  the ETF that packages Democratic congressional disclosures — of which Pelosi's are the marquee
  component." Still a *style/data reference only*, still fictional, still no impersonation.
- **LEAPS:** demote from "what it trades" to a *note* — the real pattern used long-dated options;
  our tracked call is the underlying equity, which is what we can price. Don't let the voice imply
  we're modelling options P&L we aren't computing.
- **Lag honesty:** the `stagnant`/`losing` registers should carry the twice-removed-lag caveat
  explicitly — this feed is even less "live" than the old one.
- **`style_summary` / `source_type`:** `source_type` becomes something like `'etf'` (new value
  alongside `congress|insider|institutional|social`); `source_key = 'NANC'`.

---

## Open decisions — blocked on the user, do not guess

1. **Framing:** Option B (recommended — NANC as universe, Oracle selectivity as filter) vs A
   (full reposition) vs C (new persona, leave Oracle alone). Everything below assumes B.
2. **Feed:** confirm Finnhub `/etf/holdings` tier on Railway; if premium, accept Composio-proxy
   fallback (and find the canonical issuer holdings URL).
3. **"Strike" thresholds (starting values proposed, tune before trusting):** Gate 3 add =
   `Δ shares-per-unit ≥ +20%` & `weight_pct ≥ 1.0%`; Gate 4 = top-1/snapshot + 10-trading-day
   cooldown; conviction weights `0.5/0.3/0.2`. Calibrate so the Oracle fires ~a handful of
   strikes/quarter (its "rare" identity). Ties into Open Decision #5 (streak thresholds) in `CLAUDE.md`.
4. **Universe filter:** proposed as the `securities.watchlist` tags (`AI Infra + Power` +
   `Mega-Cap Core`), since `securities` has no market-cap column. Confirm: (a) is watchlist the right
   gate, or add a `sector` set to catch un-watchlisted NANC names (which then need seeding into
   `securities` + `price_history`)? (b) ever let a non-tech mega-cap through?
5. **Exits:** treat `EXITED`/`TRIMMED` as their own bearish signal, or ignore (Oracle is long-only)?
6. **KRUZ:** ignore the Republican sibling, or ingest both and keep NANC-only for the Oracle?
```
