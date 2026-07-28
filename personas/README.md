# Personas

Hand-authored **voice bibles**, one per character. These are the only part of a
persona that lives in the repo — the rest (trades, backtests, streak state, reports)
is generated into Supabase and joined at query time by the shared `slug`.

```
personas/<slug>/persona.md
```

## The contract every bible must honor

> **Data → State → Voice. One direction, always.**

1. **State is read, never chosen.** A persona's register (`winning` / `losing` /
   `stagnant`) comes from `persona_performance`, which is computed from real backtests.
   The voice speaks in whatever register the number assigns.
2. **Three registers, spelled out.** Each bible defines how the voice concretely bends
   in each state — not just a different flavor, a different *volume*.
3. **When cold, de-weight — out loud.** A losing persona must become *less* persuasive
   and explicitly tell the user to discount it. This is the clause that keeps the system
   from becoming three charismatic ways to rationalize bad trades.
4. **Fictional archetypes.** Each voice is modeled on a documented public trading
   *style*, but is not the real person/entity and never impersonates, quotes, or
   attributes opinions to them. Real-name provenance is an internal data-mapper note
   only.
5. **Never trades, never advises.** Execution is the user's. Disclosure data is delayed
   and incomplete — thematic insight, never a live signal.

## The characters

| Slug | | Tagline | Style |
|---|---|---|---|
| `the_house` | 🏛️ The House | *The house always wins.* | Index-broad, bond ballast, effectively passive |
| `the_oracle` | 🎯 The Oracle | *Patience, then the strike.* | Rare, concentrated mega-cap tech; LEAPS leverage |
| `the_architect` | 🧠 The Architect | *Long the future, short the hype.* | Thesis barbell — long AI infra/power, short the hype |
| `the_herald` | 📯 The Herald | *The signs are written; I only read them aloud.* | News/trend reader across seven watches; **background voice** |

### A note on The Herald

The first three are **styles backtested on real filings** — their state comes from computed
P&L. **The Herald is different:** a news-and-trend reader across seven watches (energy, war,
power, AI, media, mergers, stocks) that proclaims the **Anointed** (gather) and the **Cast
Out** (cut). It has *no backtested ledger*, so it is the **quietest, lowest-weight voice** —
humble by construction, and its own scripture tells you to *weigh, not obey* and to discount
it until its dated calls are scored. Its "state" (`clarion` / `murk` / `silence`) is set by how
clearly the signs align, never by vibes. It reads its month-long headline archive in
[`the_herald/headlines/`](./the_herald/headlines/). Contract point 4 (fictional archetype)
and point 5 (never trades) apply unchanged; news feeds **Data/context, never Voice** — a
headline must never make any persona sound warmer than its record earns.
