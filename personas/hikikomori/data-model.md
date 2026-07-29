# Hikikomori — data-model sketch

**Status: proposal, NOT applied.** Nothing here is in `schema.sql` or the live Supabase
project yet. This is the shape to review before any ingestion is written. Conventions match
the existing schema (snake_case, `securities` FK, `timestamptz`, `security_invoker` views,
`comment on` metadata, 3-month retention like `market_news`).

---

## Architecture — how the data gets in (headless, no IP-block risk)

The nightly Railway cron calls the **Composio REST API** (`x-api-key` header → execute a
Reddit tool). **Composio's servers make the Reddit call**, authenticated by the already-
connected account, and hand Railway back JSON. This is the whole reason we use Composio here
rather than Reddit's public `.json` endpoints: those hard-block datacenter IPs (the same wall
that killed GDELT and 403s Finnhub from the agent session). Composio-as-proxy sidesteps it.

- **New Railway env var:** `COMPOSIO_API_KEY` (+ the connected-account / entity id). No Reddit
  OAuth creds to manage on Railway.
- **⚠️ Verify on the first Railway run** (like the Finnhub-premium check): confirm a Composio
  connection authorized interactively still executes from a headless cron with only the API
  key. Expected to work — Composio connections are account-level, not session-interactive —
  but prove it on call #1 before trusting the pipeline.
- Reddit read tools used (all confirmed available): `REDDIT_RETRIEVE_REDDIT_POST` (per-sub
  listings), `REDDIT_SEARCH_ACROSS_SUBREDDITS` (per-ticker), `REDDIT_RETRIEVE_POST_COMMENTS`
  (thread depth for the top-3 read). Rate limit ~1–2 req/s; a nightly run is nowhere near it.

## Scope

- **Subreddits (4):** `wallstreetbets`, `stocks`, `StockMarket`, `options`.
- **Tickers:** watchlist + traded names only (same set the Insider uses) — extracted from post
  titles/bodies via cashtag (`$NVDA`) + a bounded ticker regex validated against `securities`.
- **Cadence:** nightly, wired into `ingest/daily.py` alongside `news` + `insider` (guarded so
  one feed failing never kills the others).

## The three-tier funnel → where each tier lands

| Tier | Scope (per subreddit) | Cost | Column(s) it fills |
|---|---|---|---|
| 1 — count | *every* matched post/comment | free | `reddit_buzz.mentions` → velocity |
| 2 — keyword | top **10** by engagement | ~free | `reddit_buzz.bull_kw` / `bear_kw` → tilt |
| 3 — LLM | top **3** by engagement | ~12 calls/night | `reddit_threads.summary` (the "story") |

Engagement rank = `score + num_comments`. The top-3/top-10 cut is **per subreddit** (so WSB
doesn't take every slot); everything else is still *counted* for velocity — counting is free,
so the momentum signal is never thrown away.

---

## Proposed tables

```sql
-- Per-day, per-subreddit buzz aggregate for one ticker. The momentum signal lives here.
-- Grain is intentionally small (a few dozen rows/night) — aggregates, never raw posts —
-- which keeps Supabase cost negligible. 3-month rolling retention (like market_news).
create table if not exists reddit_buzz (
  id           bigint generated always as identity primary key,
  ticker       text references securities(ticker),
  buzz_date    date not null,
  subreddit    text not null,          -- wallstreetbets | stocks | StockMarket | options
  mentions     int  not null default 0, -- tier 1: count of ALL matched posts/comments
  bull_kw      int  default 0,          -- tier 2: bullish keyword hits across top-10 posts
  bear_kw      int  default 0,          -- tier 2: bearish keyword hits across top-10 posts
  top_score    int,                     -- engagement of the loudest post (context)
  ingested_at  timestamptz default now(),
  unique (ticker, buzz_date, subreddit)
);

create index if not exists idx_reddit_buzz_date on reddit_buzz(buzz_date desc);
create index if not exists idx_reddit_buzz_ticker on reddit_buzz(ticker, buzz_date desc);

-- The tier-3 deep read: the top-3 posts per subreddit we actually LLM-summarized.
-- This is Hikikomori's VOICE material — the hearsay/thesis it repeats. Grain = per post.
create table if not exists reddit_threads (
  id           bigint generated always as identity primary key,
  post_id      text unique,             -- Reddit base-36 id (dedup key)
  subreddit    text,
  title        text,
  permalink    text,                    -- link back to the thread
  score        int,
  num_comments int,
  tickers      text[],                  -- symbols this post is about (0..n)
  summary      text,                    -- LLM: WHY it's buzzing (the story)
  llm_tilt     text,                    -- LLM read: bull | bear | mixed
  posted_at    timestamptz,
  ingested_at  timestamptz default now()
);

create index if not exists idx_reddit_threads_posted on reddit_threads(posted_at desc);
```

## Proposed views

```sql
-- Velocity: today's mentions vs the prior day, per ticker (summed across subreddits).
-- This is the momentum tell — acceleration, not raw volume. security_invoker respects RLS.
create or replace view hikikomori_velocity with (security_invoker = true) as
select
  ticker,
  buzz_date,
  sum(mentions)                                           as mentions,
  lag(sum(mentions)) over (partition by ticker order by buzz_date) as mentions_prev,
  sum(bull_kw)                                            as bull_kw,
  sum(bear_kw)                                            as bear_kw
from reddit_buzz
group by ticker, buzz_date;

-- The Hikikomori board: today's movers ranked by velocity (mentions vs prior day),
-- with the crude keyword tilt. The persona joins this to reddit_threads for the "story".
create or replace view hikikomori_board with (security_invoker = true) as
select
  v.ticker,
  v.buzz_date,
  v.mentions,
  v.mentions_prev,
  round(v.mentions::numeric / nullif(v.mentions_prev, 0), 2) as velocity_x,  -- e.g. 5.0 = 5x
  case
    when v.bull_kw + v.bear_kw = 0 then 'flat'
    when v.bull_kw >= 2 * greatest(v.bear_kw, 1) then 'bull'
    when v.bear_kw >= 2 * greatest(v.bull_kw, 1) then 'bear'
    else 'mixed'
  end as tilt
from hikikomori_velocity v
where v.buzz_date = (select max(buzz_date) from reddit_buzz)
order by velocity_x desc nulls last, v.mentions desc;

-- Coverage blind spots: US tickers we've TRADED that the feed isn't discussing at all.
-- Analog to insider_coverage_gaps — the persona flags silence as a blind spot, not calm.
create or replace view hikikomori_coverage_gaps with (security_invoker = true) as
select s.ticker, s.name, s.sector
from securities s
where s.ever_traded
  and not exists (
    select 1 from reddit_buzz b
    where b.ticker = s.ticker
      and b.buzz_date > current_date - 7   -- no chatter in the last week
  );
```

## Retention

Rolling **3-month window**, identical to `market_news` — the nightly cron deletes rows older
than `SOCIAL_RETENTION_DAYS` (default 90). Forum chatter ages out fast; we never backfill it
beyond the window.

## Scoring path (how it earns a state — gated on `price_history`)

Hikikomori's board entries become **calls** written into the existing `persona_calls` ledger
(`persona = 'hikikomori'`, `verdict = 'speculative'` for a hot name, `call_price` = price at
call time). Once `price_history` lands, the same scorer that grades every persona compares
`call_price → score_price` and sets `verdict_correct` / `alpha_pct`. That scored record rolls
into `persona_performance` and finally gives it a real `winning`/`losing`/`stagnant` state —
**the same scoring feed the backtested personas wait on.** Scored calls also feed the Empath.

## Registration (when built, not now)

```sql
-- personas seed row (source_type 'social' is a new value alongside congress|insider|institutional)
insert into personas (slug, display_name, tagline, style_summary, source_type, source_key, active)
values ('hikikomori', 'Hikikomori', 'I never leave the room — but I hear everything.',
        '<style_summary from persona.md>', 'social', null, false)   -- active=false: signal-stage
on conflict (slug) do nothing;
```

## Cost note (answers the "tokens at midnight" concern)

- **LLM:** fixed at ~**12 calls/night** (top-3 × 4 subs), regardless of how wild the crowd is.
- **Supabase:** aggregates only — a few dozen `reddit_buzz` rows + ≤12 `reddit_threads` rows
  per night. Trivial storage; 3-month retention caps it.
- **Reddit/Composio:** ~40–60 read calls/night, well under the rate limit.

---

## Open knobs (defaults chosen; easy to change)

1. **Top-3 / top-10 cut = per subreddit** (assumed). Pooled-across-all-4 is cheaper but WSB
   dominates every slot.
2. **Keyword lexicon** — the tier-2 bull/bear word lists live in code, tuned over time.
3. **Velocity threshold for a "call"** — how big a spike (e.g. ≥3×) writes a `persona_calls`
   row vs. just showing on the board. To decide alongside the streak thresholds (Open
   Decision #5).
