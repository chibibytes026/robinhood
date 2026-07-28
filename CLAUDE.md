# CLAUDE.md

Context for Claude Code working in this repo. Read `ARCHITECTURE.md` for detail and
`TODO.md` for the build sequence.

---

## What we're building

A **persona-driven trading research system**. It ingests free public disclosure data
(congressional trades, SEC Form 4 insider buys, 13F institutional holdings), backtests those
trades to compute real profit and loss, then surfaces the results through three fictional
"trader personalities" — each modeled on a documented public trading *style* — that report
their own track record in character and answer questions about what they'd watch.

The user is a retail investor with ~$1,000 to deploy in a Robinhood agentic account
(currently funded with $25 as a live test). The system exists to make **him** a sharper
decision-maker. It does not trade autonomously.

### Why personas
Three distinct styles were reverse-engineered from public filings:

| Slug | Name | Style |
|---|---|---|
| `the_house` | 🏛️ The House | Index-broad, bond ballast, high turnover but effectively passive |
| `the_oracle` | 🎯 The Oracle | Rare, concentrated mega-cap tech bets with long-dated options leverage |
| `the_architect` | 🧠 The Architect | Thesis barbell — long AI infrastructure/power, hedged against overheated chip names |

Each gets a voice bible in `personas/<slug>/persona.md`, a rolling track record computed from
backtests, and monthly/quarterly reports written in its own voice. Query one and it answers
in character using its own history plus live market data.

These are **archetypes of public trading styles** — fictional characters layered on public
filing data. Not the real individuals, not their opinions, not financial advice.

---

## The one rule that matters

> **Data → State → Voice. One direction, always.**

The simulator computes real P&L. The classifier reads those numbers and assigns each persona
a state (`winning` / `losing` / `stagnant`). *Then* the persona speaks in that register.

A persona must never talk itself into confidence the numbers don't support. And a persona on
a cold streak must become **less persuasive**, not just differently flavored — it should
explicitly tell the user to discount it. Inverting this turns the system into three
charismatic ways to rationalize bad trades, which defeats its entire purpose.

---

## Stack

- **Python** — ingestion, simulation, report generation
- **Supabase (Postgres)** — all generated data; queried at runtime via MCP
- **Railway** — three cron jobs: ingest → sim+streak → reports
- **Anthropic API** — writes the in-voice reports
- **Claude Desktop** — interactive query layer (hosts Supabase + Robinhood MCP connectors)

Data sources, all free: SEC EDGAR (Form 4 + 13F), House/Senate clerk disclosures, Finnhub
(price history, free tier). Paid APIs deliberately deferred — revisit FMP (~$19/mo, includes
commercial rights) only once the system produces value. Quiver's $75 tier is breadth we
don't need.

**Nothing in the pipeline uses a browser.** All HTTP/API, fully headless. The user's Chrome
is saturated by other systems, so this was a hard requirement.

---

## Hard constraints — do not violate

- ⚠️ **Execution is human-approved, never autonomous** (updated 2026-07-28):
  - The **headless pipeline** (Railway) never places trades and holds no brokerage
    credentials. Unchanged.
  - In the **interactive layer** (user present), the agent may place a **long equity** order
    **only after explicit per-trade confirmation**, and **only in the ring-fenced
    `agentic_allowed` account** — Robinhood blocks the main account at the platform level.
    No standing authority: every order needs a fresh confirm. Flow: propose →
    `review_equity_order` preview → user confirms → `place_equity_order` → report fill + log.
  - **Options execution, exercises, and any unattended/autonomous order remain forbidden.**
  - Watchlist writes remain always-allowed.
- ❌ **No brokerage credentials in Railway.** Price history comes from Finnhub. The
  Robinhood MCP is interactive-layer only, where the user is present.
- ❌ **No secrets committed.** `.env` is gitignored; `.env.example` documents the keys.
- ❌ **Voice never drives state.** See above.
- ⚠️ **Fractional shares to 6 decimal places, never rounded to whole shares.** Robinhood
  fills dollar-based orders fractionally; whole-share rounding wrecks small-dollar backtests.
- ⚠️ **Congressional filings disclose dollar ranges, not exact amounts.** Store the midpoint,
  flag `amount_is_est = true`, never present an estimate as precise.
- ⚠️ **Disclosures are delayed and incomplete.** Congress filings lag weeks; 13Fs lag 45 days
  and omit shorts, cash, and private positions. Thematic insight, not live signal. Any
  language implying these are actionable real-time signals is wrong.

---

## Current state

**Done (Phase 0):** `schema.sql`, `ARCHITECTURE.md`, `TODO.md`, `.gitignore`,
`requirements.txt`, `.env.example`, `README.md`, folder skeleton, persona voice bibles.

**Done (Phase 1):** Supabase project `robinhood-personas` created; `schema.sql` applied
(12 tables + 3 personas + 13 seeded securities); RLS enabled on all tables (service-role
bypasses). `window` → `window_label` fix applied.

**Execution validated (2026-07-28):** human-approved equity trades proven both directions in
the ring-fenced agentic account — a $2 SPY buy and a $1 CRWV sell, each placed only after
explicit per-trade confirmation. See `agent-commands/` for the full Robinhood MCP command
surface and which commands are in/out of scope.

**Also live outside the repo:** three Robinhood watchlists built via MCP —
🤖 AI Infra + Power (NVDA, VST, BE, CRWV, CEG), 🏛️ Mega-Cap Core (AAPL, MSFT, GOOGL, AMZN,
META, AVGO), 📊 Index Anchor (VOO, SPY). Two brokerage accounts: a default individual
(`agentic_allowed = false`, off-limits to the agent) and a ring-fenced "Agentic" account
(`agentic_allowed = true`, ~$25) that is the only account the agent can trade in.

**Next:** Phases 3–6 — ingestion (start with Form 4), then the simulator, the CRWV validation
gate, and the streak classifier. No validated signal exists yet; execution tests so far are
plumbing only.

---

## Simulator spec

Core function takes `{ticker, entry_date, dollar_amount, hold_days}` and returns:

```
entry_price  → close on entry_date (or next-day open, per price_basis)
shares       → dollar_amount / entry_price, fractional to 6dp, NO rounding
exit_price   → close on entry_date + hold_days
net_usd, net_pct
spy_return   → benchmark over the identical window
alpha_pct    → net_pct - spy_return_pct
```

Weekends/holidays roll back to the prior trading day. Results write to `backtests`.

**Validation test:** replay the real CRWV buy above and confirm the simulator's output
matches the actual account. Independently verifiable — use it as the correctness gate before
trusting any batch results.

---

## Open decisions — blocked on the user, do not guess

1. `price_basis` — close-to-close, or next-day open (more realistic: you see a disclosure
   after hours and buy at the open)?
2. Copy ticker only with the user's own sizing, or mirror the trader's position size?
3. `hold_days` — calendar days or trading days?
4. Final persona names (current ones are placeholders; user may rebrand)
5. Exact numeric thresholds separating `winning` / `losing` / `stagnant`

Phase 5 (simulator) is blocked until 1–3 are answered.

---

## Scope note

If asked to add **autonomous** trade execution, agentic order placement without a human at
the trigger, or anything that removes the user from the decision loop — stop and flag it
rather than building it. That boundary is deliberate and was set by the user's own design
intent, not an incidental gap. The system's value is that it sharpens a human's judgment;
automating the trigger removes the human whose judgment it exists to improve.

(Human-approved, per-trade-confirmed execution — see Hard constraints — does **not** cross
this line: the user is still the one pulling every trigger.)
