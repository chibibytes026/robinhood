# Agent Commands

Reference for the **agentic command surface** available to this project through Robinhood's
Model Context Protocol (MCP) service — i.e. everything an AI agent can actually *do* on a
Robinhood account.

Two layers are documented here:

- **[robinhood-mcp-commands.md](./robinhood-mcp-commands.md)** — the complete, exact tool
  list exposed by the connected Robinhood MCP server (52 tools), grouped by function, each
  flagged **read** vs **write** and **allowed / forbidden in our pipeline**.
- This README — what Robinhood's consumer "Agentic Trading" product is, its guardrails, and
  how our project's hard constraints sit on top of it.

> Sourced from the official **"Trading with your agent"** help article
> ([link](https://robinhood.com/us/en/support/articles/trading-with-your-agent/), obtained
> as a PDF since the page 403s automated fetches) **cross-referenced against the live MCP
> server** connected to this session. The article documents 50 tools; the live MCP exposes
> 52 — the command reference flags the delta.

---

## What Robinhood Agentic Trading is

A brokerage product that lets a third-party AI agent connect to a **dedicated, ring-fenced
Robinhood account** via MCP and place real orders. Announced May 2026.

- **Supported agent platforms:** Claude, ChatGPT, Grok, Cursor.
- **Highlighted use cases:** portfolio rebalancing by sector exposure, screening for stocks
  growing 20%+ annually, mean-reversion strategies (buy oversold, sell on recovery),
  concentration-risk and sector-exposure analysis, surfacing new ideas from analyst notes.
- **Example asks the agent can handle:** "What's my buying power?", "Analyze my concentration
  risk", "Screen for names up 20%+ YoY", "Rebalance my sector weights."

### What the agent can place (per the article)
- **Long equities and options orders only** — no shorting yet ("we'll be adding support for
  more assets soon"). Orders appear in the Activity section of the agentic account and in
  your Robinhood history.

### Robinhood's own guardrails
- **Account firewall** — the agent can only touch capital in the dedicated Agentic account,
  never your main portfolio.
- **One-tap kill switch.**
- **Real-time trade alerts** on every agent action.
- **You review before it acts** — *but* if you've pre-authorized the agent to act without
  approval, **it can place trades without your confirmation.** You are always ultimately
  responsible for every order it places.
- **Risk:** agentic trading can lose your entire allocated investment. It is real money and
  real orders.

> This pre-authorization bypass is precisely the loop-removal our project refuses: our system
> keeps execution **manual**, so no order is ever placed without the user pulling the trigger.

Sources: [Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/) ·
[Robinhood is Now Open to Agents](https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/) ·
[CNBC](https://www.cnbc.com/2026/05/27/your-ai-agent-can-now-trade-for-you-on-robinhood-and-buy-stuff-with-your-credit-card-too.html) ·
[TechCrunch](https://techcrunch.com/2026/05/27/robinhood-now-lets-your-ai-agents-trade-stocks/)

---

## ⚠️ How OUR project uses this — the hard line

Robinhood's product *allows* full trade execution. **Our system deliberately does not use
it.** Per the project's hard constraints (`CLAUDE.md`):

- ✅ **Reads** — quotes, positions, portfolio, P&L, fundamentals, options data: allowed at
  the **interactive layer only** (Claude Desktop, user present). Never in the headless
  Railway pipeline.
- ✅ **Watchlist writes** — always permitted.
- 🟡 **Equity order execution — human-approved only** (added 2026-07-28). In the
  **interactive layer** (user present), the agent may place a **long equity** order **only
  after explicit per-trade confirmation**, and **only in the ring-fenced `agentic_allowed`
  account** (••••1739 — Robinhood blocks the main account at the platform level). No standing
  authority: every order needs a fresh `confirm`. Flow: propose → `review_equity_order`
  preview → user confirms → `place_equity_order` → report fill + log.
- ❌ **Options execution, exercises, and any unattended/autonomous execution — still
  forbidden.** `place_option_order`, `exercise_option`, and any order without a human at the
  trigger are out. The **headless Railway pipeline still never places any trade.**
- ❌ **No brokerage credentials in the pipeline.** Price history comes from Finnhub. The
  Robinhood MCP lives only in the interactive layer where the user is present.

So of the 52 available commands, our system is scoped to the **read** and **watchlist-write**
groups. The **trading** group is documented for completeness and marked 🚫 — it exists, and
we intentionally don't call it. See the per-command table for exactly which is which.
