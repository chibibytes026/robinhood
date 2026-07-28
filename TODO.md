# Build order

One step at a time. Don't skip ahead — each phase depends on the one above it.
Check the box, commit, move on.

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
- [ ] `db/client.py` — supabase-py wrapper, reads creds from env
- [x] Confirm Claude can read the tables through the Supabase MCP
- [x] Enable RLS or keep service-role key server-side only — RLS enabled on all 12 tables, no policies (service-role bypasses)

---

## Phase 2 — Accounts & keys (free tier only)

- [ ] Finnhub account → API key → `.env`
- [ ] SEC EDGAR: no key, but set a descriptive `User-Agent` (they block generic ones)
- [ ] Railway account, project created
- [ ] GitHub → Railway deploy hook connected
- [ ] Anthropic API key (for report generation) → `.env`

> Skip paid APIs entirely for now. Revisit FMP (~$19/mo, **includes commercial rights**)
> only once something here is making money. Quiver's $75 tier is breadth you don't need yet.

---

## Phase 3 — First ingestion slice (prove it end to end)

Start with **insider Form 4** — highest signal, lowest noise.

- [ ] `ingest/edgar_form4.py` — pull recent Form 4s
- [ ] Parse: ticker, insider, title, txn_code, shares, price, dates
- [ ] Filter to `txn_code = 'P'` (real open-market buys only)
- [ ] Upsert to `insider_trades`, dedupe on the unique constraint
- [ ] Write an `ingest_runs` audit row
- [ ] **Checkpoint:** real rows visible in Supabase. Stop and verify before continuing.

---

## Phase 4 — Remaining ingestion

- [ ] `ingest/finnhub_prices.py` → `price_history` (needed by the sim — do this next)
- [ ] Backfill 2 years of daily OHLC for every watchlist ticker + SPY
- [ ] `ingest/congress.py` → `congress_trades` (parse amount ranges → low/high/midpoint)
- [ ] `ingest/edgar_13f.py` → `institutional_holdings` (handle put/call legs separately)
- [ ] `ingest/map_personas.py` → flatten all three into `persona_trades`

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

- [ ] `railway.toml` + `Procfile`
- [ ] Cron: ingest (daily, after market close)
- [ ] Cron: sim + streak (chained after ingest)
- [ ] Cron: reports (1st of month, 1st of quarter)
- [ ] Env vars set in Railway dashboard
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

- ❌ No trade execution in the pipeline. Watchlists are the only Robinhood write.
- ❌ No brokerage credentials in Railway. Price data comes from Finnhub.
- ❌ No secrets committed. `.env` stays gitignored.
- ❌ Voice never drives state. Data → state → voice, one direction.
