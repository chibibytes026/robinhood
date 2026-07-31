# Sensei Terminal — UI Plan

Planning doc for the interactive layer's UI. **Planning only — no app code, no deploy yet.**
Source design: `Sensei Terminal.dc.html` (Claude Design export, project *Text RPG Investment UI*).

---

## Decision log (settled in planning)

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Hosting | **Local desktop app** (not online) | Deletes the entire public attack surface. Brokerage creds stay on the user's machine — this *is* the "interactive layer, user present" the architecture already assumes. |
| D2 | Engine | **Electron + TypeScript Claude Agent SDK** | Agent SDK + MCP connectors run natively in Electron's Node process — one runtime. Uses an embedded webview, **not the user's Chrome** (which is saturated — a hard constraint), so a local *browser tab* was rejected in favor of a real app. |
| D3 | Interaction model | **Council cockpit** (supersedes the Zork REPL in TODO Phase 10) | The design has no free-text question box. You press **CONSULT THE PARTY**, every live persona renders its stance at once, and you seal orders inline. Better standing dashboard; still honors Data → State → Voice. |

`sim/terminal.py` (TODO Phase 10, a stdin REPL) is **replaced** by this cockpit. Same retrieval
logic, different surface. The schema Layer-4 comment describing a "Zork REPL" is now historical.

---

## What the design is

A three-column terminal cockpit — `grid-template-columns: 306px 1fr 268px`, JetBrains Mono,
warm paper `#F5F2EB` with crimson `#C41E3A` accent and kanji flourishes (a dojo/"sensei" motif
over the trading system).

- **Left (306px, collapsible) — THE PARTY 一門:** the 7-persona roster. Each card: glyph, name,
  state (CLARION / READY / HUSH / STAGNANT), a conviction/meter bar, `LV` level, record
  (`no ledger` / `sim pending` / `13F live` / `0W-0L`), status (🟢 ACTIVE / 🔵 READY / ⚪ DORMANT).
  Selectable (focus highlight). Footer: *Data becomes state. State becomes voice. Never the
  reverse.* (記 · 位 · 声)
  **No per-persona tagline on the roster card** — it duplicates the tagline already shown in the
  center stance-card header, so it is dropped here (design review, 2026-07-31).
- **Center (1fr):** header (`SENSEI ◆ THE WAY` · clock · `● BROKER LINKED` ·
  `HUMAN APPROVAL REQUIRED`); a circular invested-total seal + SENSEI ASCII wordmark; the
  **COUNSEL 諮** bar (round N · read X ago · N awaiting your seal · **CONSULT THE PARTY** button);
  then one **stance card** per persona — in-voice prose, 評 evidence line, CONVICTION bar, and,
  when present, a **PROPOSED ORDER — YOUR SEAL REQUIRED 印** block with APPROVE / DECLINE.
- **Right (268px, collapsible):** **FEEDS 流** (feed status dots), **STOCK PICKS 選** (anointed
  tickers), **SESSION LEDGER 帳** (calls proposed / approved / declined / capital committed),
  **VS SPY 績** (12-mo line chart + monthly table + APY), disclaimer footer.

**Both side panes are minimizable** (design review, 2026-07-31 — the full three-column view reads
as busy). Each rail collapses to a thin strip with a toggle (◆) that reclaims its width for the
center COUNSEL column; the center council is never collapsible. Suggested behavior: click the
rail header (or its ◆) to collapse/expand; persist each pane's collapsed state locally so it
survives restarts. Collapsed grid becomes `~28px / 1fr / ~28px` (either or both rails), letting
the user run a distraction-free "council only" view and pop the feeds/ledger back when wanted.

The design **bakes the constraints into the UI**: `HUMAN APPROVAL REQUIRED` in the header and,
on every order card, `agentic-ringfence · LONG EQUITY ONLY · NO OPTIONS · NO UNATTENDED FILLS ·
nothing is sent until you approve`.

---

## Design → schema map

| UI region | Backend source | Real today? |
|---|---|---|
| THE PARTY roster (state, LV, record, status) | `personas` + `persona_performance` | Personas exist; state pending simulator |
| Stance prose + register + CONVICTION % | voice bible (repo) + `persona_performance` → Anthropic | Herald live; others need the sim |
| 評 evidence line | latest `market_news` / `insider_buys` / `the_shutin_board` / `institutional_moves` | ✅ feeds live |
| PROPOSED ORDER block | new `persona_calls` row (verdict=`buy`) + Robinhood `review_equity_order` | Needs wiring |
| APPROVE → SENT | `place_equity_order` (agentic ringfence) → `persona_calls.linked_order` | The one guarded action |
| FEEDS 流 (nightly/weekly/pending/blocked) | `ingest_runs` | ✅ live |
| STOCK PICKS 選 (anointed) | `watchlist_signals` (Phase 11) or derived from feeds | Partial |
| SESSION LEDGER 帳 | session-local counters | Trivial |
| VS SPY 績 + APY | `backtests` + `persona_performance` | ❌ waits on simulator + deeper `price_history` |

---

## Architecture

```
Electron window — Sensei Terminal UI (React port of the .dc.html cockpit)
   │  (no auth gate — local machine; OS login is the gate)
   ▼
Electron main process — Claude Agent SDK
   ├─ MCP: Supabase   → read personas, persona_performance, feeds, backtests
   ├─ MCP: Robinhood  → ALLOWLISTED tools ONLY:
   │        get_equity_quotes / positions, review_equity_order,
   │        place_equity_order, watchlist writes
   │        (place_option_order, exercise_option, etc. NOT registered)
   ├─ CONSULT round → per active persona: retrieve → Anthropic → {register, conviction,
   │                  stance, evidence, call?}  (structured output)
   ├─ APPROVE → review_equity_order → place_equity_order → log persona_calls.linked_order
   └─ NO cron, NO background worker → nothing can place an order unattended
```

### Renderer notes
- Rebuild the three-column layout in **React**. The prototype's `DCLogic` state
  (`round`, `variant`, `settled`, `approved`, `declined`, `capital`, `focus`) becomes React
  state — it is already shaped like a component. Add `leftCollapsed` / `rightCollapsed` (persisted
  locally) for the minimizable side rails, and drop the roster-card tagline.
- Recreate the **visual output** pixel-for-pixel (colors, spacing, type). Do **not** port the
  prototype's `<x-dc>` / `sc-for` / `sc-if` / `support.js` internals — that is Claude Design's
  runtime shim, not production structure.

### `consult()` → a real round
For each **active** persona, the Agent SDK retrieves the voice bible + `persona_performance`
(streak/state) + that persona's latest feed rows (+ a live quote for any proposed ticker), and
returns a structured stance `{register, conviction, stance, evidence, call?}`. The `call`, when
present, is a sized long-equity order proposal.

### `settle(approve)` → the one guarded action
APPROVE runs `review_equity_order` → `place_equity_order` in the `agentic_allowed` account, then
writes the fill to `persona_calls` (`linked_order`, `user_action=bought`, `agreement`). DECLINE
voids and logs, nothing transmitted.

---

## Security / guardrails (local build)

Going local collapses the online security stack. What remains — all of it already committed to
in `CLAUDE.md`:

- **Per-trade human confirm** — APPROVE is the fresh, per-order seal. No standing authority.
- **Tool allowlist** — options/exercise tools are never registered with the SDK; the agent
  cannot call what does not exist in its toolset.
- **No unattended path** — zero cron/background route to `place_equity_order`. Execution only
  inside a live session with the user present. This is the "never autonomous" bright line.
- **Ring-fence** — only the `agentic_allowed` account is reachable; Robinhood blocks the main
  account at the platform level, bounding worst-case loss to that balance.
- **Optional** — a trade-PIN at confirm time and hard $/order · orders/day caps, now as
  fat-finger protection rather than anti-attacker controls. The design shows a single-click
  APPROVE; the PIN is an easy add if wanted.

Dropped vs. the online version: password gate, rate-limit/lockout, IP allowlist, session
timeouts, hosted-token risk — none needed on a local machine.

---

## Corrections the mock needs in production

- **Placeholder numbers.** "1.5K INVESTED" and a "40 sh @ $189.50 = $7,580" VST order don't
  match the real ring-fenced account (~$25 → ~$1k) or the locked **fixed-$-per-trade** rule.
  Production sizes every order to the actual agentic balance + fixed-$; the UI renders whatever
  the sizing logic returns.
- **Fabricated VS-SPY track.** The chart/APY are simulated. They stay empty/"paper" until the
  simulator (Phase 5) and deeper `price_history` land. The cockpit ships *before* that with real
  Herald stances + feed status; the performance panel fills in later.
- **Low-record personas may still propose.** The design lets Ready/signal-stage personas surface
  calls (Herald "no ledger", Insider "no backtested record yet — discount me"). That is
  consistent with Data → State → Voice: their weaker state shows as a lower CONVICTION bar and
  explicit self-discounting language. The human still decides.

---

## Build sequence

1. **Shell + roster + Herald stances + feeds.** Electron + Agent SDK + Supabase MCP. Renders the
   full cockpit; CONSULT produces real stances for live personas (Herald works end-to-end today).
   No execution wired. Ships without the simulator.
2. **Live market data.** Add Robinhood read tools — quotes/positions in-voice; evidence lines
   reference real prices.
3. **Guarded execution (last).** Wire APPROVE → `review_equity_order` → `place_equity_order` with
   the allowlist + confirm. Retest with a $1 order, mirroring the 2026-07-28 validation.
4. **Performance panel (gated).** VS-SPY / ledger / LV / records go live once the simulator
   (Phase 5) writes `backtests` / `persona_performance`.

Staging execution last means the risky surface exists only after the safe parts are proven.

---

## Multi-agent design

The cockpit is driven by a **team of scoped agents**, not one monolithic agent handling all
retrieval, narration, and execution. This is a deliberate design choice: splitting by
responsibility and scoping each agent's tools turns the project's one rule (Data → State → Voice)
into a structural fact rather than a prompt promise.

### Which primitive — subagents, not "agent teams"

Claude Code documents two multi-agent mechanisms; only one fits an embedded app:

- **Claude Code "agent teams"** (`code.claude.com/docs/en/agent-teams`) orchestrate multiple
  *interactive CLI sessions* — a lead terminal, a shared task-list, mailboxes under
  `~/.claude/teams/`, tmux/iTerm2 split panes. It is **experimental**
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), built for a human steering teammates at a terminal,
  and carries hard limits (one team per session, no nested teams, teammates can't spawn
  teammates, fixed lead, no clean resumption). **Not a fit** for a shipped Electron app backend.
- **Agent SDK subagents + our own orchestration** is the supported path for programmatic /
  embedded multi-agent work: define distinct agents (each with its own system prompt, model, and
  **tool allowlist**), and the Electron main process orchestrates the fan-out. **This is what the
  Sensei Terminal uses.**

### The agent team

```
Orchestrator (Electron main / SDK) — on CONSULT THE PARTY: fan out, gather, assemble
  │
  ├─ DATA-READER agents (parallel · read-only · Supabase MCP ONLY)
  │    news-reader     → market_news              (Herald)
  │    insider-reader  → insider_buys             (Insider)
  │    buzz-reader     → the_shutin_board         (Shut-In)
  │    holdings-reader → institutional_moves      (Architect)
  │    perf-reader     → persona_performance + backtests   (state for ALL personas)
  │
  ├─ VOICE agents (one per persona · NO DB / NO broker tools)
  │    in  = voice bible + that persona's state + its reader's evidence
  │    out = structured {register, conviction, stance, evidence, call?}
  │
  └─ EXECUTION agent (spawned ONLY on APPROVE · Robinhood equity + watchlist tools ONLY)
       review_equity_order → place_equity_order (ringfence) → log persona_calls.linked_order
```

### Why this shape

- **Data → State → Voice becomes tool-scoping.** Voice agents hold *no* data-source or broker
  tools; they can only narrate from the state + evidence handed to them. A voice agent literally
  cannot reach the market and talk itself warm.
- **Execution is isolated.** Only the execution agent holds `place_equity_order`, and it is
  spawned only on the human APPROVE click. No reader or voice agent can ever place an order —
  reinforcing "human-approved, never autonomous" at the wiring level.
- **Parallelism where it pays.** The data readers run concurrently; voice agents fan out per
  persona. Classic orchestrator-worker fan-out; wall-clock is the slowest single agent, not the
  sum.
- **Cost control.** Cheap readers can run a smaller/faster model; only the voice agents need the
  strong model for in-character prose. Dormant personas are skipped entirely.

### SDK surface (confirmed)

Subagents are defined via the **`agents` option on `query()`** in the TypeScript SDK — a map of
name → `AgentDefinition`. Each definition scopes its own prompt, model, effort, and **tools**:

```ts
import { query } from "@anthropic-ai/claude-agent-sdk";

const agents = {
  "perf-reader": {
    description: "Reads persona streak state + backtests from Supabase.",
    prompt: "You ONLY read persona_performance and backtests. Return the state + numbers. Never narrate.",
    tools: ["mcp__supabase__execute_sql"],   // Supabase read only
    mcpServers: ["supabase"],
    model: "haiku", effort: "low",            // cheap: it just fetches
  },
  "voice-oracle": {
    description: "Speaks as The Oracle from handed-in state + evidence.",
    prompt: "<the_oracle voice bible>. Narrate ONLY from the state and evidence provided.",
    tools: [],                                // NO db, NO broker — can only speak
    model: "sonnet", effort: "high",
  },
  "executor": {
    description: "Places a human-approved long-equity order in the ringfence.",
    prompt: "Place exactly the approved order. Long equity only.",
    tools: ["mcp__robinhood__review_equity_order", "mcp__robinhood__place_equity_order"],
    disallowedTools: [                        // belt-and-suspenders
      "mcp__robinhood__place_option_order", "mcp__robinhood__exercise_option",
    ],
    mcpServers: ["robinhood"],
  },
};
```

Confirmed mechanics:
- **Per-agent tool scoping** via `tools` (allowlist), `disallowedTools` (denylist), and
  `mcpServers` (which MCP servers even load). Voice agents get `tools: []` — structurally mute on
  data and execution.
- **Orchestration** is the parent `query()` fanning out to subagents (via the `Agent` tool),
  results summarized back to the parent — context-isolated, and read-only subagents run in
  **parallel** natively.
- **Agent teams are NOT in the SDK** — CLI/terminal only, experimental. Confirmed: use subagents.
- Gotchas to design around: subagents **don't inherit parent history** (pass each persona's state
  + evidence explicitly in the spawn prompt); `maxTurns` caps parent + all subagents combined;
  default subagent nesting depth is 3.

> **Security correction — do NOT auto-approve the executor.** The SDK offers `permissionMode:
> "dontAsk"` / auto-approve; that is fine for the **read** agents (they only query Supabase /
> read Robinhood), but the **executor must never run in an auto-approve mode**. The human APPROVE
> click in the cockpit is the gate: the orchestrator spawns the executor **only after** that click,
> for that one order. Auto-approving execution would silently re-cross the "human-approved, never
> autonomous" line the whole design exists to hold.

---

## Open items

- **STOCK PICKS source** — wire to `watchlist_signals` (needs Phase 11 signal scoring) or derive
  from the existing feed views in the interim.
- **Order type** — the mock uses `BUY · LIMIT DAY`. Confirm limit-day vs market for the sized
  fixed-$ orders (limit is safer for small-dollar fills).
- **Trade-PIN / caps** — decide whether to add the optional fat-finger controls.
- **Persona rename (TODO Open Decision #4)** — cosmetic; the UI reads `display_name`, so a rebrand
  is data-only.
