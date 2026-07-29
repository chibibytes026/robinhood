# Build order

One step at a time. Don't skip ahead — each phase depends on the one above it.
Check the box, commit, move on.

---

## Where we are now (2026-07-28)

Progress so far, out of phase order because the build has front-loaded the persona + data
layers ahead of the simulator:

- **Phase 0–1 done.** Repo skeleton, `schema.sql`, `.env.example`, `db/client.py`; Supabase
  project `robinhood-personas` live with RLS on all tables (no policies — service-role
  bypasses in the proof-of-concept phase). Schema has grown well past the original 12 tables:
  `market_news`, `persona_calls` (the "you should have listened" ledger), `insider_trades`,
  plus the `insider_buys` and `insider_coverage_gaps` views and `securities.form4_eligible` /
  `ever_traded` flags — all documented with `COMMENT ON`.
- **Six personas registered** (was three): 🏛️ The House, 🎯 The Oracle, 🧠 The Architect,
  📯 **The Herald** (news/trend reader — the only *live* voice, plain Buy/Watch/Avoid table
  first, then flavor; 3-month headline archive), 🫀 **The Empath** (meta voice reading the
  `persona_calls` ledger — dormant until ≥10 live personas), 🕵️ **The Insider** (Form-4
  `P`-buy follower — data live, no voice bible yet). See `README.md` for the full status table.
- **Ingestion live on Railway** (not EDGAR-first as originally planned — Finnhub-first, since
  it's the one source Railway's network can reach; Finnhub is 403-blocked from the agent
  session). `ingest/daily.py` runs `news` + `insider` nightly → `market_news` /
  `insider_trades`. News has a rolling **3-month retention** (`NEWS_RETENTION_DAYS`, we never
  backfill past 90 days). GDELT was tried and removed (blocks Railway datacenter IPs, 429).
- **Insider relevance tested:** high coverage (11 US watchlist names), low signal — only **6
  open-market `P`-buys** across ~5,100 recent transactions, clustered in AVGO/MSFT; every
  AI-infra name (NVDA, CRWV, VST, CEG, BE) showed zero insider buying. Confirms The Insider is
  a low-frequency, contrarian voice by design.
- **Human-approved execution validated** in the ring-fenced agentic account (see Never, below).
- **`price_history` LANDED (2026-07-29).** Split-adjusted daily OHLCV + real dividends via Yahoo
  (Finnhub candles are premium), 3-month backfill for all watchlist tickers + SPY, daily Railway
  cron. The backtest → state → voice chain is now unblocked on data. **The next blocker is the
  simulator itself** (`sim/` is still empty) plus `map_personas.py` (needs a CUSIP→ticker resolve
  for the 13F persona). Note: `price_history` is a 3-month window — deepen it before backtesting
  older disclosed trades.
- **Universe expanded beyond the original 14:** a `💧 Water` theme (AWK, WTRG, AWR, XYL, PNR, VLTO,
  PHO) was added via a new `securities.watchlist` tag that mirrors the Robinhood watchlists; all
  ingesters now read the universe from `securities`, so new themes propagate automatically.

---

## Phase 0 — Repo foundation

- [x] Commit `schema.sql`, `ARCHITECTURE.md`, `TODO.md`
- [x] Add `.gitignore` (Python + `.env`)
- [x] Add `requirements.txt`
- [x] Add `README.md` (point at ARCHITECTURE.md)
- [x] Create `.env.example` — document every key, commit **no secrets**
- [x] Folder skeleton: `ingest/ sim/ personas/ reports/ db/`

---

## Phase 1 — Database

- [x] Create Supabase project (or reuse existing) — `robinhood-personas` (ref ufkaoyvdhicwdwbckutx)
- [x] Run `schema.sql` in the SQL editor
- [x] Verify all 12 tables + the 3 seeded personas exist
- [x] `db/client.py` — supabase-py wrapper, reads creds from env
- [x] Confirm Claude can read the tables through the Supabase MCP
- [x] Enable RLS or keep service-role key server-side only — RLS enabled on all 12 tables, no policies (service-role bypasses)

---

## Phase 2 — Accounts & keys (free tier only)

- [x] Finnhub account → API key → Railway service env (`FINNHUB_API_KEY`)
- [ ] SEC EDGAR: no key, but set a descriptive `User-Agent` (they block generic ones)
- [x] Railway account, project created — `serene-friendship`, nightly `ingest.daily` cron
- [x] GitHub → Railway auto-deploy connected (GitHub App installed + environment connected to
      branch `claude/reference-files-review-nb9y1i`). Composio is the fallback control path
      when the native Railway MCP drops.
- [ ] Anthropic API key (for report generation) → `.env`

> Skip paid APIs entirely for now. Revisit FMP (~$19/mo, **includes commercial rights**)
> only once something here is making money. Quiver's $75 tier is breadth you don't need yet.

---

## Phase 3 — First ingestion slice (prove it end to end)

Start with **insider Form 4** — highest signal, lowest noise.

> **Pivot (2026-07):** the source is **Finnhub `/stock/insider-transactions`, not EDGAR** —
> Finnhub is the one feed Railway's network can reach, and its Form-4 data is pre-parsed. The
> pull is `ingest/insider.py`, wired into `ingest/daily.py`. EDGAR is deferred to Phase 4 (13F).

- [x] `ingest/insider.py` — pull recent Form 4s (Finnhub, per watchlist + traded ticker)
- [x] Parse: ticker, insider, txn_code, shares, price, dates (Finnhub omits `title`)
- [x] Filter/report `txn_code = 'P'` (real open-market buys) via the `insider_buys` view
- [x] Upsert to `insider_trades`, dedupe on the unique constraint
- [x] Coverage-gap detection (`insider_coverage_gaps`) so the persona asks for a refresh when a
      US traded ticker is missing
- [x] **Checkpoint:** real rows visible in Supabase (nightly Railway cron). Verified.

---

## Phase 4 — Remaining ingestion

- [x] ⭐ `ingest/prices.py` → `price_history` — DONE. Split-adjusted daily OHLCV + real dividends
      via Yahoo (Finnhub `stock candles` are premium on the free tier); daily Railway cron; the
      ticker universe is read from `securities`. (was `finnhub_prices.py`)
- [~] Backfill depth: currently a **3-month rolling window** (matches news retention), NOT 2 years.
      ⚠️ backtesting older disclosed trades (insider P-buys go back to 2025-09) needs deeper
      history — revisit `PRICE_RETENTION_DAYS` before the sim runs.
- [ ] `ingest/congress.py` → `congress_trades` — ⛔ blocked (congressional feed is premium)
- [x] `ingest/architect_13f.py` → `institutional_holdings` — DONE. By CUSIP+issuer, put/call legs
      separate; manifest + coverage/moves views. (was `edgar_13f.py`)
- [ ] `ingest/map_personas.py` → flatten into `persona_trades` — needs a CUSIP→ticker resolve for
      the 13F persona (OpenFIGI) before it can feed the sim
- [x] **Universe is theme-tagged:** `securities.watchlist` mirrors the Robinhood lists (Water ·
      AI Infra + Power · Mega-Cap Core · Index Anchor); news/insider/prices all read the universe
      from `securities`, so new themes propagate automatically. 💧 Water added.

---

## Phase 5 — Simulator

- [ ] **Decide:** `price_basis` = `close_to_close` or `next_open`
- [ ] **Decide:** copy-ticker-only, or mirror-their-size (ranges → midpoint)
- [ ] **Decide:** `hold_days` = calendar or trading days
- [ ] `sim/backtest.py` — single-trade backtest, fractional shares to 6dp
- [ ] Weekend/holiday roll-back to prior trading day
- [ ] SPY benchmark over the identical window → `alpha_pct`
- [ ] Write results to `backtests`
- [ ] **Validation:** backtest the real CRWV buy (0.012710 sh @ $78.68, 2026-07-23)
      against the actual account. Numbers must match.
- [ ] Batch mode: replay every `persona_trades` row

---

## Phase 6 — Streak classifier

- [ ] `sim/streak.py` — hit_rate, net_return, alpha_vs_spy, streak_run, trend
- [ ] Define exact thresholds for `winning` / `losing` / `stagnant` — write them down
- [ ] Compute per persona × 30d/90d windows
- [ ] Write to `persona_performance`
- [ ] **Checkpoint:** all three personas show a real, earned state

---

## Phase 7 — Personas

- [x] `personas/the_oracle/persona.md` — voice, style rules, tells, 3 streak registers
- [x] `personas/the_house/persona.md`
- [x] `personas/the_architect/persona.md`
- [x] `personas/the_herald/persona.md` — news/trend reader; plain Buy/Watch/Avoid table first,
      then in-character flavor; 3-month headline archive under `personas/the_herald/headlines/`
- [x] `personas/the_empath/persona.md` — meta voice over the `persona_calls` ledger (dormant)
- [x] `personas/the_insider/persona.md` — whistleblower-gossip voice (holds the receipts on
      CEOs/CFOs; `P`-buy only; receipts-not-rumor discipline; de-weights when cold)
- [ ] Rename the characters if the placeholders don't fit the brand
- [x] Add an explicit "when cold, tell them to ignore me" clause to each bible

---

## Phase 8 — Reports

- [ ] `reports/generate.py` — pull metrics + voice bible → Anthropic API → `persona_reports`
- [ ] Monthly template: scoreboard line first, then in-voice narrative
- [ ] Quarterly template: summarize the 3 monthlies beneath it
- [ ] Backfill historical months so there's real history on day one
- [ ] Verify the voice actually shifts with state (fake a cold streak, check the tone)

---

## Phase 9 — Deploy

- [x] `railway.toml` (`ingest.daily`, `restartPolicyType = NEVER`; cron schedule kept in the
      service config, not the toml, so one-off manual runs aren't overridden on deploy)
- [x] Cron: ingest (daily, ~06:00 UTC — news + insider via `ingest.daily`)
- [ ] Cron: sim + streak (chained after ingest) — blocked on the simulator (needs `price_history`)
- [ ] Cron: reports (1st of month, 1st of quarter)
- [x] Env vars set in Railway dashboard (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FINNHUB_API_KEY`)
- [ ] Failure alerting (Discord webhook — same pattern as the bot crew)
- [ ] **Checkpoint:** a full unattended cycle completes with no browser open

---

## Phase 10 — Interactive layer

- [ ] Install Claude Desktop, move off Chrome
- [ ] Confirm Supabase + Robinhood MCPs both live in the desktop app
- [ ] Write the query prompt: `@<persona>, what's the play this morning?`
- [ ] Verify retrieval pulls: voice bible + streak + latest reports + recent trades + quotes
- [ ] Confirm a cold persona actually de-weights its own advice

---

## Phase 11 — Signal scoring (optional, later)

- [ ] `sim/score_signals.py` → `watchlist_signals`
- [ ] Rules: cluster > lone · `P` only · CEO/CFO > director > VP · buying into weakness ·
      size relative to comp · filter 10b5-1 scheduled trades
- [ ] Auto-sync top-scored tickers into a 🕵️ Insider Conviction Robinhood watchlist

---

## Open decisions

| # | Decision | Status |
|---|---|---|
| 1 | `price_basis`: close-to-close or next-day open | ⬜ |
| 2 | Copy ticker only, or mirror position size | ⬜ |
| 3 | `hold_days`: calendar or trading days | ⬜ |
| 4 | Final persona names | ⬜ |
| 5 | Streak thresholds (exact numbers) | ⬜ |

---

## Never

- ⚠️ **Execution is human-approved, never autonomous.** The **headless pipeline** (Railway)
  never places trades and holds no brokerage credentials. In the **interactive layer** (user
  present), the agent may place a **long equity** order **only after explicit per-trade
  confirmation**, and **only in the ring-fenced `agentic_allowed` account**. Flow: propose →
  `review_equity_order` preview → user confirms → `place_equity_order` → report fill + log.
  **Options execution, exercises, and any unattended/autonomous order remain forbidden.**
  Watchlist writes are always allowed. (Validated 2026-07-28 — a $2 SPY buy + a $1 CRWV sell,
  each per-trade-confirmed.)
- ❌ No brokerage credentials in Railway. Price data comes from Finnhub.
- ❌ No secrets committed. `.env` stays gitignored.
- ❌ Voice never drives state. Data → state → voice, one direction.
