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

| Slug | | Tagline | Style | Status |
|---|---|---|---|---|
| `the_house` | 🏛️ The House | *The house always wins.* | Index-broad, bond ballast, effectively passive | 🟡 In progress |
| `the_oracle` | 🎯 The Oracle | *Patience, then the strike.* | Rare, concentrated mega-cap tech; LEAPS leverage | 🟡 In progress |
| `the_architect` | 🧠 The Architect | *Long the future, short the hype.* | Thesis barbell — long AI infra/power, short the hype | 🟡 In progress |
| `the_herald` | 📯 The Herald | *The signs are written; I only read them aloud.* | News/trend reader across seven watches; **background voice** | 🟢 Active |
| `the_empath` | 🫀 The Empath | *I speak for the ones you stopped hearing.* | Reader of the `persona_calls` ledger; amplifies the ignored-but-right; **meta voice** | ⚪ Dormant |
| `the_insider` | 🕵️ The Insider | *The ones who know, buy.* | Whistleblower-gossip on insiders' open-market `P`-buys; cluster/rank/into-weakness; contrarian, low-frequency | 🔵 Ready |

**Status** (persona lifecycle): 🟢 **Active** = live and feeding calls · 🔵 **Ready** = voice + data feed built, gated only on a missing dependency (fires the moment it lands) · 🟡 **In progress** = being built, not yet live · ⚪ **Dormant** = registered but gated (see The Empath). Today only The Herald is live; The Insider is Ready, waiting on price history.

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

### A note on The Empath

Unlike the other four, The Empath reads no market and no filings — it reads **us**. Its source
is the `persona_calls` ledger itself: it hunts the 🔴 *"you should have listened"* cell (you
moved *against* a persona and the call later scored right — `agreement = disagree` ∧
`verdict_correct = true`), ranks those misses by margin, and gives the most-ignored-yet-correct
persona a voice. It owns no strategy and originates no calls — it **amplifies** a neglected one.
By its own **Ten-Voice Rule** it stays silent (register `hush`) and builds no ranking structure
until **≥10 personas are live** and their calls are scored — with fewer, "a wider margin than
the rest" has no legs to stand on (today: 1 live, ledger unscored → dormant). Its registers are
`resonance` / `murmur` / `hush`. Contract points 4 and 5 apply unchanged; it never overrides a
backtested state and discounts itself always.

### A note on The Insider

A **whistleblower with the receipts** — a Sherron-Watkins-type who reads corporate insiders'
*own* open-market purchases (SEC Form 4, code `P`) and, in a gossip's whisper, tells you who's
quietly buying their own stock before you touch it. The one iron discipline: **she only gossips
what a filing can prove.** A sell means nothing (taxes, a house, a 10b5-1 calendar); a `P`-buy is
the one tell that can't be faked — nobody buys their own name as a favor. She ranks clusters over
lone buys, CEO/CFO over VP, buying-into-weakness over strength, and strips scheduled 10b5-1 buys.
She *will* be backtested (state from `persona_performance`), so contract points 1–3 apply in full
— but she's **signal-stage (`active = false`)** until the simulator exists: today she reports only
signal *volume* (currently low — 6 `P`-buys, AVGO/MSFT; AI-infra names zero) and coverage gaps,
never a backtested claim. When her record is cold she turns the gossip on herself and tells you to
discount her. Her feed is Finnhub Form-4 data (`insider_buys`); points 4 and 5 apply unchanged.
