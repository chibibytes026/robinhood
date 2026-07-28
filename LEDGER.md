# Persona Calls Ledger

The scorecard of **each persona vs. you.** Every call a persona makes is logged with what you
actually did about it, whether that was *agreement* or *defiance*, and — graded later — whether
the call was *right*. Over time this answers the only question that matters:

> **Who should we have listened to?**

Inspired by companion-reputation systems (e.g. *Fallout: New Vegas* — "The Herald liked that,"
"The Herald will remember this"). We keep the construct, not the exact tone.

Table: **`persona_calls`** (see `schema.sql`). Applies to **all** personas — keyed by `persona`
slug — so once The House / Oracle / Architect make dated calls, they log here too.

---

## What each row records

| Field | Meaning |
|---|---|
| `verdict` | the call: `buy` · `speculative` · `watch` · `hold` · `avoid` · `trim` · `sell` |
| `register` | conviction at the time (Herald: `clarion`/`murk`/`silence`; others: streak state) |
| `call_price` | price at the moment of the call — the scoring baseline |
| `user_action` | what you did: `bought` · `sold` · `trimmed` · `held` · `none` |
| `agreement` | `agree` (acted with it) · `disagree` (acted against it) · `n/a` |
| `reaction` | the flavor tag — *"The Herald approved." / "…will remember this." / "…warned against this."* |
| `linked_order` | brokerage order id, if you traded on it |
| outcome fields | `scored_date`, `return_pct`, `spy_return_pct`, `alpha_pct`, `verdict_correct` — filled when graded |

## Agreement, precisely

- **agree** — you moved *with* the call: bought a `buy`, avoided an `avoid`, held a `hold`, trimmed a `trim`.
- **disagree** — you moved *against* it: held what it said to `trim`, bought what it said to `avoid`.
- **n/a** — no actionable stance.

## Scoring (done later, per call)

On a later date, from `call_price` → `score_price`, compute `return_pct`, `spy_return_pct`,
`alpha_pct`, and set `verdict_correct` by the call's *intent*:

- `buy` / `speculative` → correct if it **beat SPY** (`alpha_pct > 0`).
- `avoid` / `trim` → correct if it **lagged SPY** (you were right to skip or cut).
- `watch` / `hold` → correct if holding-off / holding beat the alternative.

Then the payoff cross-tab (`agreement` × `verdict_correct`):

| | verdict right | verdict wrong |
|---|---|---|
| **you agreed** | 🟢 you listened, it worked | ⚪ you listened, it missed |
| **you disagreed** | 🔴 **you should have listened** | 🟢 you were right to defy it |

The 🔴 cell is the one to watch — it's the running tally of *"the persona was right and we didn't listen."*
It is also **[The Empath](personas/the_empath/persona.md)'s** entire beat: a dormant meta-persona that reads this cell, ranks the misses by margin, and gives the most-ignored-yet-correct persona a voice — once there are ≥10 live personas and scored calls to rank.

---

## First entries — 2026-07-28 · The Herald · register `murk`

| Ticker | Verdict | You did | Agreement | Reaction |
|---|---|---|---|---|
| GOOGL | 🟢 buy | bought $1 | agree | The Herald approved. |
| BE | 🟠 speculative | bought $1 | agree | The Herald will remember this. |
| CEG | 🟡 watch | none | agree | The Herald is watching. |
| VST | 🟡 watch | none | agree | The Herald is watching. |
| META | 🟡 watch | none | agree | The Herald is watching. |
| SPY | ⚪ hold | held | agree | The Herald approved. |
| NVDA | 🔴 avoid | none | agree | The Herald approved — you did not chase it. |
| CRWV | ✂️ trim | **held** | **disagree** | The Herald warned against this — and will remember. |

**One open defiance so far:** CRWV. The Herald said cut it (~17% below cost); you're holding.
Grade it in a few weeks and we'll know whether that was conviction or stubbornness.

> The Herald still has **no scored ledger** until these calls are graded — this file is the
> ledger *beginning to fill*, not proof of anything yet. Weigh it accordingly.
