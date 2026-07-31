# Architecture

How the pieces talk to each other. Read this before building anything.

---

## The one-line version

Free public data → Supabase → simulator computes real P&L → streak classifier sets each
persona's state → personas narrate in-voice → **you** decide and execute.

---

## Core principle

> **Data → State → Voice. One direction, always.**

The simulator computes real numbers from real disclosed trades. The classifier reads those
numbers and sets a persona's state (`winning` / `losing` / `stagnant`). *Then* the persona
speaks in that register.

A persona never decides it "feels" confident. If The Oracle sounds humbled, it's because it's
down 4 trades — not because humility fit the paragraph. Reverse this and you've built three
charismatic ways to rationalize bad trades.

**Corollary:** a cold persona must become *less persuasive*, not just differently flavored.
Tone stays in-character; the underlying signal weight drops. A persona on an 8-loss skid
should be telling you to ignore it.

---

## Layers

### 1. Ingestion (`ingest/`)
Scheduled Python. Pulls free public sources, normalizes, upserts into Supabase.
Writes an audit row to `ingest_runs` every time.

| Source | Feeds | Cost |
|---|---|---|
| SEC EDGAR (Form 4) | `insider_trades` | Free |
| SEC EDGAR (13F) | `institutional_holdings` | Free |
| House/Senate clerk | `congress_trades` | Free |
| Finnhub | `price_history` | Free tier |

**Nothing here touches a browser.** All HTTP/API. Runs headless on Railway.

**Nothing here touches Robinhood.** The pipeline must never depend on brokerage
credentials — price history comes from Finnhub. Robinhood is interactive-layer only.

### 2. Mapping (`ingest/map_personas.py`)
Raw disclosures have three different shapes. This flattens them into one:
`persona_trades (persona, ticker, side, trade_date, amount_usd, ...)`.

Congressional filings disclose **ranges**, not exact amounts → store the midpoint and flag
`amount_is_est = true`. Never present an estimate as a precise figure.

### 3. Simulation (`sim/backtest.py`)
The engine. Takes `{ticker, entry_date, dollar_amount, hold_days}` and returns:

```
entry_price  → close on entry_date (or next-day open, per price_basis)
shares       → dollar_amount / entry_price, fractional to 6 decimals, NO rounding
exit_price   → close on entry_date + hold_days
net_usd/pct  → the result
spy_return   → benchmark over the identical window
alpha        → net_pct - spy_return_pct
```

Fractional shares to 6dp mirrors how Robinhood actually fills dollar-based orders. This
matters: whole-share rounding wrecks small-dollar backtests.

Weekends/holidays roll back to the prior trading day. Every run writes rows to `backtests`.

### 4. Streak classification (`sim/streak.py`)
Runs immediately after the sim. For each persona, over 30d and 90d windows:

- **hit_rate** — % of closed trades that netted positive
- **alpha_vs_spy** — did the *style* beat just holding the market
- **streak_run** — consecutive wins (+) or losses (−)
- **trend** — this window vs last

Then classifies:

| State | Condition |
|---|---|
| 🔥 `winning` | positive alpha, rising hit rate, recent run mostly green |
| 🧊 `losing` | negative alpha, recent run mostly red, decaying trend |
| 😐 `stagnant` | near-zero alpha, choppy W-L-W-L, no directional edge |

Writes to `persona_performance`. **This table is the source of truth for voice.**

### 5. Reporting (`reports/generate.py`)
Monthly and quarterly cron. Reads `backtests` + `persona_performance` + the persona's
voice bible, calls the Anthropic API, writes an in-voice markdown report into
`persona_reports`. Quarterly summarizes the three monthlies beneath it.

The report is the backtest, narrated. Numbers first, voice second.

### 6. Interactive layer (the Sensei Terminal — local app)
The read side is the **Sensei Terminal**: a **local Electron desktop app** powered by the
**Claude Agent SDK**. It is a **council cockpit**, not a chat REPL — you press **CONSULT THE
PARTY** and every live persona renders its stance at once; proposed **long-equity** orders
surface with **APPROVE / DECLINE** you seal by hand. (This supersedes the earlier "Zork in a
terminal" REPL. Full plan: [`docs/sensei-terminal-plan.md`](./docs/sensei-terminal-plan.md).)

Per persona, a consult round pulls:

```
personas/<slug>/persona.md          ← voice bible (repo)
persona_performance (latest)        ← current streak state  → register + conviction
persona_reports (latest monthly/qtr)← recent narrative arc (optional)
persona_trades (last N)             ← freshest moves
watchlist_signals (top scored)      ← what's flagged now
that persona's latest feed rows     ← market_news / insider_buys / the_shutin_board / 13F moves
Robinhood MCP: quotes + positions    ← live market + your actual book
```

...and answers in character: what this style is eyeing, what to watch, what it'd flag as a
mistake in your current book, what it'd liquidate — with any actionable buy surfaced as a sized,
human-approved order card.

**Multi-agent:** the retrieval + narration is **not** one monolithic agent. The Agent SDK runs a
team of scoped **subagents** — an orchestrator plus per-domain data readers and per-persona voice
agents, each allowlisted to only the MCP tools it needs. See the plan doc's "Multi-agent design"
section. (Note: this uses the SDK's *subagent/orchestrator* primitives, **not** Claude Code's
experimental terminal "agent teams" feature, which orchestrates interactive CLI sessions, not an
embedded app backend.)

---

## Where things live

| Artifact | Home | Why |
|---|---|---|
| Voice bibles (`persona.md`) | **Repo** | Stable, hand-authored, git-versioned, diffable |
| Pipeline code | **Repo** | Obviously |
| Trades, backtests, streaks, reports | **Supabase** | Generated; queried at runtime via MCP |

The persona "folder" is a *logical namespace* (`persona = 'the_oracle'`) spanning both — not
literal files Claude opens at query time. Keeps retrieval fast instead of file-parsing every
question.

---

## Runtime

```
GitHub  ──push──▶  Railway
                     ├─ cron: ingest        (daily)
                     ├─ cron: sim + streak  (after ingest)
                     └─ cron: reports       (monthly / quarterly)
                              │
                              ▼
                          Supabase  ◀──MCP──  Sensei Terminal  ◀──  you
                                              (local Electron app,
                                               Claude Agent SDK + subagents)
                                                    │
                                            Robinhood MCP (read + watchlists
                                            + human-approved equity execution)
```

**No Chrome anywhere.** The pipeline is headless HTTP. The interactive layer is a **local
Electron app** that embeds the Claude Agent SDK and hosts the MCP connectors — it uses its own
webview, not the user's (saturated) Chrome. Execution is human-approved, per-trade-confirmed, and
ring-fenced to the `agentic_allowed` account; nothing trades unattended.

---

## The personas

| Slug | Name | Tagline | Style |
|---|---|---|---|
| `the_house` | 🏛️ The House | *The house always wins.* | Index-broad, bond ballast, high turnover but effectively passive |
| `the_oracle` | 🎯 The Oracle | *Patience, then the strike.* | Rare, concentrated mega-cap tech; LEAPS leverage; uncanny timing |
| `the_architect` | 🧠 The Architect | *Long the future, short the hype.* | Thesis barbell — long AI infra/power, puts against hyped chips |

These are **archetypes of documented public trading styles**, not the real individuals and
not their opinions. Fictional voices layered on public filing data.

---

## Boundaries

- Personas are **lenses on historical patterns**, not licensed advisors. "The Oracle would
  buy X" means "a concentrated-conviction style leans toward X." A pattern, not a promise.
- Backtests describe **what happened**, never what will.
- Disclosures are **delayed and incomplete** — congress filings lag weeks, 13Fs lag 45 days
  and hide shorts/cash/private positions. Treat as thematic insight, not live signal.
- **Execution stays manual.** The pipeline never places orders. Robinhood write access is
  limited to watchlists. You pull every trigger.
