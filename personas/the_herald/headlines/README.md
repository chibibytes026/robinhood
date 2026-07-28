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
| 2026-W31 | Jul 27 – Aug 2 | 🟢 Jul 27–28 (7 watches) |
| 2026-W30 | Jul 20 – Jul 26 | 🟢 backfilled |
| 2026-W29 | Jul 13 – Jul 19 | 🟢 backfilled |
| 2026-W28 | Jul 6 – Jul 12 | 🟢 backfilled |
| 2026-W27 | Jun 29 – Jul 5 | 🟢 backfilled (sparser) |

> Backfilled from a past-month news pull, so density thins the further back it runs (W27 is
> sparse). Good enough for a *directional* read of the month; not a complete record. The
> Herald still has **no scored ledger**, so it reads with discount regardless.
