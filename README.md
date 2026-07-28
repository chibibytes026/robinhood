# Robinhood Persona Trading System

A **persona-driven trading research system**. It ingests free public disclosure data
(congressional trades, SEC Form 4 insider buys, 13F institutional holdings), backtests
those trades to compute real profit and loss, then surfaces the results through three
fictional **trader personalities** — each modeled on a documented public trading
*style* — that report their own track record in character.

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

| Slug | | Tagline | Style |
|---|---|---|---|
| `the_house` | 🏛️ The House | *The house always wins.* | Index-broad, bond ballast, effectively passive |
| `the_oracle` | 🎯 The Oracle | *Patience, then the strike.* | Rare, concentrated mega-cap tech; LEAPS leverage |
| `the_architect` | 🧠 The Architect | *Long the future, short the hype.* | Thesis barbell — long AI infra/power, short the hype |

These are **archetypes of public trading styles** — fictional characters layered on
public filing data. Not the real individuals, not their opinions, not financial advice.

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
