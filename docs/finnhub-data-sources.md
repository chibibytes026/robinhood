# Finnhub data sources — handoff reference

Free-tier Finnhub endpoints for this project, how to pull them, and what they feed.
Expands the **Analyst** and **Events** categories in particular.

> ⚠️ **The #1 gotcha:** Finnhub is **blocked from the agent's Claude session** (both `curl`
> through the egress proxy and Anthropic-routed WebFetch return **403**). **Only the Railway
> network reaches Finnhub.** So every pull/test must run **on Railway** (or the user's local
> machine) — never expect to hit Finnhub from inside the agent session. This is why the
> insider relevance test is "built but not yet run."

---

## How & where to pull

- **Base URL:** `https://finnhub.io/api/v1`
- **Auth:** append `?token=<FINNHUB_API_KEY>` (or send header `X-Finnhub-Token`).
- **Rate limit (free):** ~60 calls/min. Sleep ~1.1s between calls in loops.
- **Key location:** Railway service env `FINNHUB_API_KEY` (also documented in `.env.example`).
- **Response format:** JSON. Some endpoints return a bare array; others an object with a
  named array (e.g. `earningsCalendar`, `ipoCalendar`). Parse defensively.
- **History depth (free):** ~1 year per call for most series.

**Working code pattern** (copy from existing ingesters):
- `ingest/news.py` — Finnhub market + company news → `market_news` (nightly Railway cron).
- `ingest/insider.py` — Finnhub insider transactions → `insider_trades` (built; pending run).
- `db/client.py` — Supabase service-role client (`get_client()`), server-side only.

```python
import requests
r = requests.get(
    "https://finnhub.io/api/v1/stock/recommendation",
    params={"symbol": "NVDA", "token": TOKEN}, timeout=30,
)
r.raise_for_status()
data = r.json()   # list or dict depending on endpoint
```

> Free vs premium shifts over time. Where this doc says "verify", confirm on the **first
> Railway call** (a premium endpoint returns HTTP 403 / `{"error": "...premium..."}`).

---

## Analyst

Analyst consensus/estimates. On the free tier this is essentially **just recommendation
trends** — the rest are premium.

| Endpoint | Free? | Params | Returns | Feeds |
|---|---|---|---|---|
| `/stock/recommendation` | ✅ **free** | `symbol` | Array of monthly consensus rows: `{ symbol, period (YYYY-MM-DD), strongBuy, buy, hold, sell, strongSell }` | Context line in reports & the Herald ("analysts: 9 buy / 2 hold / 0 sell on NVDA, trending up") |
| `/stock/price-target` | ⛔ premium | `symbol` | `{ targetHigh, targetLow, targetMean, targetMedian, lastUpdated }` | (n/a free) |
| `/stock/upgrade-downgrade` | ⛔ premium | `symbol`, `from`, `to` | Rating-change events (firm, fromGrade, toGrade, action) | (n/a free) |
| `/stock/eps-estimate`, `/stock/revenue-estimate`, `/stock/earnings-estimate` | ⛔ premium | `symbol`, `freq` | Forward EPS/revenue estimates | (n/a free) |

**How to use `recommendation`:** it's a *context* signal, never persona state. Good for a
report sentence or for the Herald to cite ("the street is leaning buy"), and it changes
slowly (monthly), so a weekly pull is plenty. Do **not** let it move a backtested register —
same Data → State → Voice rule as news.

---

## Events

Corporate-event calendars and history. Mostly free and genuinely useful for **tagging** a
backtest window ("this trade straddled an earnings date") and for report color.

| Endpoint | Free? | Params | Returns | Feeds |
|---|---|---|---|---|
| `/calendar/earnings` | ✅ free | `from`, `to` (dates) — or `symbol` | `{ earningsCalendar: [ { symbol, date, hour, quarter, year, epsEstimate, epsActual, revenueEstimate, revenueActual } ] }` | Event tagging; "earnings on <date>" flags next to backtests; report color |
| `/stock/earnings` | ✅ free | `symbol` | Array of surprises: `{ symbol, period, quarter, year, actual, estimate, surprise, surprisePercent }` | Beat/miss history; report substance |
| `/calendar/ipo` | ✅ free | `from`, `to` | `{ ipoCalendar: [ { symbol, name, date, exchange, price, numberOfShares, totalSharesValue, status } ] }` | New-listing awareness (e.g. CRWV-style names) |
| `/stock/split` | ✅ free *(verify)* | `symbol`, `from`, `to` | Array: `{ symbol, date, fromFactor, toFactor }` | **Split-adjusting `price_history`** — important for correct backtest returns |
| `/stock/dividend` | ⛔ premium *(verify)* | `symbol`, `from`, `to` | Dividend history (exDate, amount, payDate…) | (n/a free) — basic yield is in `/stock/metric` instead |

**How to use Events:**
- **Earnings calendar/surprises** — the highest-value free events. Store next to a ticker so a
  backtest or a persona can say "the window included an earnings beat." Pull by date range
  (whole market) or per symbol.
- **Splits** — quietly critical once the **price_history** work starts: raw historical closes
  must be split-adjusted or backtest returns are wrong across a split. Pull per watchlist
  ticker when building `price_history`.
- **IPO calendar** — lower priority; nice for spotting fresh names entering the themes.

---

## The rest of the free menu (for orientation)

| Category | Free endpoints | Feeds |
|---|---|---|
| **Prices** ⭐ | `/stock/candle` (historical OHLC), `/quote` (real-time) | The simulator's `price_history` — unblocks backtesting (the biggest TODO) |
| **News** (live) | `/news?category=general`, `/company-news` | The Herald → `market_news` (already wired) |
| **Insider** ⭐ | `/stock/insider-transactions` (Form 4), `/stock/insider-sentiment` (MSPR) | Insider signal / possible 5th persona (`ingest/insider.py` built) |
| **Fundamentals** | `/stock/profile2`, `/stock/metric?metric=all`, `/stock/financials-reported`, `/stock/peers` | Report substance, screening |
| **Reference** | `/stock/symbol`, `/search`, market status | Plumbing |

**Known premium (not free):** congressional/senate trading, social sentiment, price targets,
estimates, upgrade/downgrade, dividends, most alternative data (lobbying, gov spending,
patents, FDA).

---

## Suggested next-agent actions

1. **Run the built insider pull on Railway** (`python -m ingest.insider`) and read the
   per-ticker relevance + `insider_buys` / `insider_coverage_gaps`.
2. When starting **price_history** (the big one): pull `/stock/candle` per watchlist ticker,
   and **also pull `/stock/split`** to adjust — don't skip splits.
3. Treat **recommendation trends** and **earnings** as *context* feeds (weekly/daily), tagged
   to tickers, never as persona state.
