# 📯 The Herald's Archive

The headlines The Herald reads. It reads the **whole month** to feel the direction — *what
was, what is, and where the current runs* — then crosses that reading against the watchlists
and live holdings to name the **Anointed** and the **Cast Out**.

## Structure

```
headlines/
  <YYYY-MM>/
    <YYYY-Www>.md      ← one file per ISO week; daily sections inside
```

- **Month folder** = the Herald's reading horizon (it ingests the full month).
- **Weekly file** = one ISO week (e.g. `2026-W31` = Mon Jul 27 – Sun Aug 2).
- **Daily section** inside each week, newest day first.
- **Each headline** is one line:
  `HH:MM ET · [Watch] · Source · Headline — link`

## The seven watches (tags)

`⚡Energy` · `⚔️War` · `🔌Power` · `🤖AI` · `📺Media` · `🤝Mergers` · `📈Stocks`

A single story can sit in two watches (e.g. an AI-datacenter power deal is `🤖AI`+`🔌Power`);
it's tagged where it reads strongest and cross-noted where useful.

## Each day closes with a *Herald's reading*

A short, clearly-labeled **derived** interpretation — direction per watch (↑ / ↓ / →) and the
one-line current. This is the Herald's read, not raw fact; it's what feeds a proclamation.
Raw headlines above it stay objective and sourced.

## How it's filled

- **Interactive (now):** pulled via Composio `COMPOSIO_SEARCH_NEWS` across the seven watches.
- **Pipeline (planned):** Finnhub `/news` (general) + `/company-news` for watchlist tickers,
  free + headless, appended daily on the Railway cron.

## Coverage status

| Week | Dates | Status |
|---|---|---|
| 2026-W31 | Jul 27 – Aug 2 | 🟢 seeded (Jul 28 complete, 7 watches) |
| 2026-W27–W30 | Jul 1 – Jul 26 | ⚪ to backfill |

> The Herald's read is only as good as its month. Until W27–W30 are backfilled, it is reading
> a partial month and **must say so** — a herald that proclaims a trend from three days of
> headlines is exactly the noise-crowning failure the system guards against.
