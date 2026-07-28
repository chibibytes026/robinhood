# Robinhood Persona Trading System

A **persona-driven trading research system**. It ingests free public disclosure data
(congressional trades, SEC Form 4 insider buys, 13F institutional holdings), backtests
those trades to compute real profit and loss, then surfaces the results through fictional
**trader personalities** that report their own track record in character. Three are
modeled on documented public trading *styles* and speak from their backtested P&L; a
fourth — **The Herald** — is a news-and-trend reader that carries context, not a record.

It exists to make a human a sharper decision-maker. **It does not trade.**

> **Data → State → Voice. One direction, always.**
> The simulator computes real P&L → a classifier turns that into a state
> (`winning` / `losing` / `stagnant`) → *then* the persona speaks in that register.
> A cold persona becomes *less* persuasive and tells you to discount it.

## Read next

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — how the pieces talk to each other. Start here.
- **[TODO.md](./TODO.md)** — the phased build sequence.
- **[schema.sql](./schema.sql)** — the Supabase schema (canonical; matches the live DB).
- **[personas/](./personas/)** — the hand-authored voice bibles.

## The personas

| Slug | | Tagline | Style | State from |
|---|---|---|---|---|
| `the_house` | 🏛️ The House | *The house always wins.* | Index-broad, bond ballast, effectively passive | backtested P&L |
| `the_oracle` | 🎯 The Oracle | *Patience, then the strike.* | Rare, concentrated mega-cap tech; LEAPS leverage | backtested P&L |
| `the_architect` | 🧠 The Architect | *Long the future, short the hype.* | Thesis barbell — long AI infra/power, short the hype | backtested P&L |
| `the_herald` | 📯 The Herald | *The signs are written; I only read them aloud.* | News/trend reader across seven watches — the **background voice** | sign clarity, not P&L |

The first three are **archetypes of public trading styles** — fictional characters layered
on public filing data, their register (`winning` / `losing` / `stagnant`) set by computed P&L.

**The Herald is different.** It runs no backtest: it reads the month's headlines across seven
watches (energy · war · power · AI · media · mergers · stocks), crosses them against the
watchlists and live holdings, and proclaims the **Anointed** (gather) and the **Cast Out**
(cut). With no ledger to stand on, it is the **quietest, lowest-weight voice by design** — its
state (`clarion` / `murk` / `silence`) reflects only how clearly the signs align, and its own
scripture tells you to *weigh, not obey*. News feeds **data/context, never voice**: a headline
never makes any persona sound warmer than its record earns.

All four are fictional characters. Not the real individuals, not their opinions, not
financial advice.

## Data sources

Where each persona/signal's data comes from, and what's wired vs. pending. Free-first.

| Persona / signal | Data need | Source | Status |
|---|---|---|---|
| 📯 The Herald | market + company news | Finnhub (free) | ✅ live — nightly cron → `market_news` |
| ⭐ Insider signal *(new)* | Form 4 insider buys | Finnhub insider transactions (free) | ⏳ next up |
| 🧠 The Architect | 13F institutional holdings | SEC EDGAR (free) | ⬜ planned |
| 🎯 The Oracle · 🏛️ The House | congressional trades | Finnhub congressional = **premium**; no clean free API found (S3 mirrors dead, clerk site IP-blocked) | ⛔ blocked — decision needed |

Also free on Finnhub and worth pulling as *context* (not persona state): insider sentiment
(MSPR), recommendation trends, earnings calendar/surprises, basic financials. The
**congressional gap** (Oracle/House) is the one unresolved source — pay Finnhub premium
(~$12/mo), find another free feed, or keep the manual bootstrap.

> ⭐ **The major next step for the backtested personas: price history from Finnhub.**
> The winners/losers simulation — the thing that turns The House / Oracle / Architect from
> voices-without-a-record into real, stateful personas — needs historical daily OHLC
> (`stock candles` → `price_history`). It's a big build, deliberately deferred until all
> personas and their data feeds exist. Nothing about the backtest → state → voice chain works
> until this lands, so it's the single biggest item on the TODO.

## Layout

```
ingest/     # scheduled Python: pull free public sources -> Supabase
sim/        # backtest engine + streak classifier
personas/   # voice bibles (personas/<slug>/persona.md)
reports/    # in-voice monthly/quarterly report generation
db/         # supabase-py client wrapper
schema.sql  # canonical Supabase schema
```

## Setup

1. `cp .env.example .env` and fill in keys (`.env` is gitignored).
2. `pip install -r requirements.txt`
3. Run `schema.sql` in the Supabase SQL editor (already applied to the
   `robinhood-personas` project).

## Constraints (do not violate)

- **Execution is human-approved, never autonomous.** The headless pipeline never places
  trades. In the interactive layer (user present), the agent may place a **long equity**
  order **only after explicit per-trade confirmation**, and **only in the ring-fenced
  agentic account**. Options, exercises, and any unattended order are forbidden; watchlist
  writes are always allowed.
- **No brokerage credentials in the pipeline.** Price history comes from Finnhub.
- **No secrets committed.** `.env` is gitignored; `.env.example` documents the keys.
- **Voice never drives state.** Data → state → voice, one direction.
