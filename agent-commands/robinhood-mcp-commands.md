# Robinhood MCP — full command reference

Mirrors Robinhood's official **"Trading with your agent"** help article (captured as PDF and
cross-referenced against the **live MCP server** connected to this session). Grouping and
descriptions are Robinhood's own; the **R/W** and **Pipeline** columns are our annotations.

**Legend**
- **R** = read-only · **W** = write (mutates brokerage/account state) · **sim** = simulate only, no fill
- **Pipeline** = allowed in *our* system? ✅ read (interactive layer only) · ✅ watchlist write ·
  ✅ scan config · 🚫 forbidden (order execution — never called by us)

> **Cross-reference result:** the article documents **50 tools**; the live MCP exposes **52**.
> The two extras (`exercise_option`, `cancel_option_exercise`) are **not** in the published
> article — see [Cross-reference notes](#cross-reference-notes). Everything in the article is
> present in the live MCP.

---

## Account, portfolio, and other tools

| Tool | Description (Robinhood) | R/W | Pipeline |
|---|---|---|---|
| `get_accounts` | View all your Robinhood accounts | R | ✅ |
| `get_portfolio` | Snapshot of your portfolio: total value, values by asset class, real-time buying power | R | ✅ |
| `get_realized_pnl` | Realized P&L over a custom window, broken down by asset class | R | ✅ |
| `get_pnl_trade_history` | Trade-by-trade realized P&L history | R | ✅ |
| `search` | Resolve a company name or partial name to a ticker | R | ✅ |

## Watchlist tools

| Tool | Description (Robinhood) | R/W | Pipeline |
|---|---|---|---|
| `get_watchlists` | List user's watchlists | R | ✅ |
| `get_watchlist_items` | List symbols in a specific watchlist | R | ✅ |
| `get_option_watchlist` | Load an options watchlist | R | ✅ |
| `get_popular_watchlists` | Discover Robinhood lists (e.g. "100 most popular") | R | ✅ |
| `create_watchlist` | Make a new custom watchlist | W | ✅ |
| `update_watchlist` | Rename or update a watchlist's name/description | W | ✅ |
| `follow_watchlist` | Follow a Robinhood list | W | ✅ |
| `unfollow_watchlist` | Stop following a Robinhood list | W | ✅ |
| `add_to_watchlist` | Add stocks, crypto, or indexes to a watchlist | W | ✅ |
| `remove_from_watchlist` | Remove stocks, crypto, or indexes from a watchlist | W | ✅ |
| `add_option_to_watchlist` | Add an options contract to a watchlist | W | ✅ |
| `remove_option_from_watchlist` | Remove an options contract from a watchlist | W | ✅ |

## Market data tools

| Tool | Description (Robinhood) | R/W | Pipeline |
|---|---|---|---|
| `get_equity_historicals` | OHLCV price bars across a time range | R | ✅ |
| `get_equity_fundamentals` | Valuation ratios, market cap, 52-week range, dividend info, today's OHLCV | R | ✅ |
| `get_financials` | Reported financials over time (revenue, gross profit, net income, net margin) by quarter/year | R | ✅ |
| `get_equity_price_book` | Real-time Level 2 order book (bid/ask levels + resting size), up to 4 stocks | R | ✅ |
| `get_equity_technical_indicators` | Compute a technical indicator (RSI, MACD, Bollinger Bands, MAs, more) over a range | R | ✅ |
| `get_earnings_results` | A stock's earnings history + next report; est. vs actual EPS | R | ✅ |
| `get_earnings_calendar` | Scheduled earnings across the market over a window (≤31 days), optional large-cap filter | R | ✅ |
| `get_indexes` | Look up market indexes by symbol | R | ✅ |
| `get_index_quotes` | Real-time index values | R | ✅ |

## Equities tools

| Tool | Description (Robinhood) | R/W | Pipeline |
|---|---|---|---|
| `get_equity_positions` | Open equity positions with quantity and cost basis | R | ✅ |
| `get_equity_tax_lots` | Open tax lots per holding (qty, cost basis, acquisition date, long/short-term) | R | ✅ |
| `get_equity_quotes` | Real-time quotes + prior close, up to 20 symbols | R | ✅ |
| `get_equity_orders` | Equity order status history | R | ✅ |
| `get_equity_tradability` | Whether a symbol is tradable + fractionally tradable | R | ✅ |
| `review_equity_order` | **Simulate** an equity order and get pre-trade warnings | sim | 🚫 |
| `place_equity_order` | **Place an equity order** | W | 🚫 |
| `cancel_equity_order` | Cancel an open equity order | W | 🚫 |

## Options tools

| Tool | Description (Robinhood) | R/W | Pipeline |
|---|---|---|---|
| `get_option_level_upgrade_info` | Link to apply for options trading access | R | ✅ |
| `get_option_historicals` | OHLC price bars for option contracts over a range | R | ✅ |
| `get_option_chains` | Load option chains | R | ✅ |
| `get_option_instruments` | Load option contracts filtered by expiry, strike, or type | R | ✅ |
| `get_option_quotes` | Real-time quotes for option contracts | R | ✅ |
| `get_option_positions` | Open or closed options positions | R | ✅ |
| `get_option_orders` | Options order history | R | ✅ |
| `review_option_order` | **Simulate** an options order with pre-trade alerts | sim | 🚫 |
| `place_option_order` | **Place a real options order** | W | 🚫 |
| `cancel_option_order` | Cancel an open options order | W | 🚫 |

## Scanner tool calls

| Tool | Description (Robinhood) | R/W | Pipeline |
|---|---|---|---|
| `get_scans` | List your saved scans | R | ✅ |
| `get_scanner_filter_specs` | List every available scanner filter + how to use it before building/updating a scan | R | ✅ |
| `create_scan` | Create a new scan from a preset or custom filters | W | ✅ |
| `run_scan` | Run a saved scan and get live market results | R | ✅ |
| `update_scan_filters` | Change the filters on a saved scan | W | ✅ |
| `update_scan_config` | Change how results are sorted | W | ✅ |

---

## Cross-reference notes

Findings from comparing the article (PDF) to the live MCP server:

1. **Two undocumented execution tools exist in the live MCP.** Not listed anywhere in the
   article's tool tables:
   | Tool | R/W | Pipeline | Note |
   |---|---|---|---|
   | `exercise_option` | W | 🚫 | Exercise an option position — live MCP only, not in the published article |
   | `cancel_option_exercise` | W | 🚫 | Cancel a pending option exercise — live MCP only, not in the published article |
   The article says "We'll be adding more tools in future releases," so the server is ahead
   of the docs. Both are order-execution writes → **forbidden** for our pipeline regardless.

2. **Long-only, for now.** The article: *"You currently can use your agent to place **long**
   equities and options orders… we'll be adding support for more assets soon."* No shorting.

3. **Agents can trade without per-order confirmation.** The article's safety section:
   *"if you've asked your agent to take action without asking your approval, it can place
   trades without your confirmation."* You're always ultimately responsible. This is exactly
   the loop-removal risk our project refuses — hence execution stays manual for us.

4. **`review_*` are simulate-only** (no fill), but they're part of the execution flow and
   require the agentic account, so we still mark them 🚫 for the headless pipeline.

5. **Grouping differs slightly from our first draft.** This file now follows Robinhood's own
   six groups (Account · Watchlist · Market data · Equities · Options · Scanner). Our earlier
   "market data & research" bucket had merged options-data and search into one group.

---

## Summary by our permission scope

*(Updated 2026-07-28: equity execution moved to human-approved.)*

| Bucket | Count | Our pipeline |
|---|---|---|
| Reads (account, market data, positions, order status, scan results) | 33 | ✅ read (interactive layer) |
| Watchlist writes | 8 | ✅ always allowed |
| Scan config writes | 3 | ✅ |
| **Equity execution** (`review_equity_order`, `place_equity_order`, `cancel_equity_order`) | 3 | 🟡 **human-approved only**, interactive layer, agentic account, per-trade confirm |
| **Options execution + exercises** (`review_option_order`, `place_option_order`, `cancel_option_order`, `exercise_option`, `cancel_option_exercise`) | 5 | 🚫 forbidden |
| **Total** | **52** | |

The line now: **44 non-execution tools in-scope; 3 equity-execution tools gated behind
explicit per-trade human approval; 5 options/exercise tools still fully out.** The headless
pipeline places nothing — execution only ever happens with a human at the trigger. The value
is sharpening a human's judgment, not removing them.

First human-approved trade: $2.00 SPY market buy, filled 0.002699 sh @ $740.81 in the
agentic account, 2026-07-28 (order `6a68f6c7…`).
