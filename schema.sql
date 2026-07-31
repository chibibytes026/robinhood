-- ============================================================
-- Robinhood Persona Trading System — Supabase schema
-- Run top-to-bottom in the Supabase SQL editor.
--
-- This file is the canonical schema and matches the live
-- `robinhood-personas` Supabase project. Notable points vs. the
-- first draft:
--   * persona_performance.window_label — 'window' is a RESERVED
--     keyword in Postgres and cannot be an unquoted column name.
--   * securities is seeded with the watchlist tickers + SPY/VOO so
--     the FK-bearing ingestion tables have parents to reference.
--   * RLS is enabled on every table with no policies: the anon and
--     authenticated roles are denied, while the server-side
--     service-role key (pipeline + MCP) bypasses RLS.
-- ============================================================

-- ------------------------------------------------------------
-- LAYER 1: REFERENCE
-- ------------------------------------------------------------

create table if not exists securities (
  ticker         text primary key,
  name           text,
  sector         text,
  asset_type     text default 'equity',   -- equity | etf
  form4_eligible boolean default true,     -- files SEC Form 4? false for ETFs / foreign ADRs
  ever_traded    boolean default false,    -- have we bought/sold it in the agentic account
  watchlist      text,                     -- theme tag, mirrors the Robinhood watchlists (Water | AI Infra + Power | Mega-Cap Core | Index Anchor). Ingesters read the universe from this table.
  created_at     timestamptz default now()
);

-- Daily split-adjusted OHLCV. This is what the simulator reads. Trading days only.
-- Source: free feeds — ingest/prices.py tries Finnhub candles first, then Yahoo
-- (which yields split-adjusted OHLC + adj_close + real dividends). Do NOT depend on
-- Robinhood here — keep the cron pipeline headless. ~3-month rolling window.
create table if not exists price_history (
  ticker      text references securities(ticker),
  date        date not null,
  open        numeric,
  high        numeric,
  low         numeric,
  close       numeric,               -- split-adjusted close (the price series the sim reads)
  volume      bigint,
  adj_close   numeric,               -- split + dividend adjusted close (total-return basis)
  dividend    numeric,               -- cash dividend on ex-date (actual when source provides it, e.g. Yahoo)
  source      text,                  -- finnhub | yahoo
  primary key (ticker, date)
);

create index if not exists idx_price_history_date on price_history(date);


-- ------------------------------------------------------------
-- LAYER 2: RAW DISCLOSURE DATA (ingested, never hand-edited)
-- ------------------------------------------------------------

-- SEC Form 4. txn_code 'P' = open-market purchase (the only real conviction tell).
create table if not exists insider_trades (
  id            bigint generated always as identity primary key,
  ticker        text references securities(ticker),
  insider_name  text,
  title         text,                  -- CEO, CFO, Director, 10% Owner
  txn_code      char(1),               -- P buy | S sell | A grant | M option exercise
  shares        numeric,
  price         numeric,
  value_usd     numeric,
  trade_date    date,
  filed_date    date,
  source        text default 'sec_edgar',
  ingested_at   timestamptz default now(),
  unique (ticker, insider_name, trade_date, txn_code, shares)
);

create index if not exists idx_insider_ticker_date on insider_trades(ticker, trade_date desc);
create index if not exists idx_insider_code on insider_trades(txn_code);

-- The daily insider report: open-market PURCHASES only (code 'P') — the real
-- conviction tell. Everything else (S/A/M/F) stays in insider_trades, unused.
-- security_invoker=true so the view respects the base table's RLS.
create or replace view insider_buys with (security_invoker = true) as
select ticker, insider_name, shares, price, value_usd, trade_date, filed_date, source
from insider_trades
where txn_code = 'P' and shares > 0
order by trade_date desc;

-- Coverage gaps: US Form-4 stocks we've TRADED that returned NO insider data.
-- The insider persona reads this to flag tickers whose report looks incomplete
-- and request a refresh (depends on securities.form4_eligible + ever_traded).
create or replace view insider_coverage_gaps with (security_invoker = true) as
select s.ticker, s.name, s.sector
from securities s
where s.form4_eligible and s.ever_traded
  and not exists (select 1 from insider_trades i where i.ticker = s.ticker);

-- Insider-persona signal notes, stored as queryable schema metadata.
comment on table insider_trades is
 'Raw SEC Form 4 insider transactions (source: Finnhub). Insider-persona signal rules: code P '
 '(open-market purchase) is the ONLY real conviction tell; S/A/M/F are noise. Cluster > lone; '
 'CEO/CFO > director > VP (rank needs SEC Form 4 directly — Finnhub omits title); buying into '
 'weakness > strength; strip 10b5-1 scheduled trades. Delayed (~2-day filing lag), incomplete '
 '— thematic conviction, not a live signal.';
comment on view insider_buys is
 'The Insider daily report: open-market purchases only (code P, positive shares) — the '
 'conviction subset of insider_trades.';
comment on view insider_coverage_gaps is
 'US Form-4 stocks we have traded that returned NO insider data. The Insider persona reads this '
 'to flag an incomplete report and request a refresh (depends on securities.form4_eligible + '
 'ever_traded).';

-- House/Senate clerk STOCK Act filings. Amounts are RANGES, not exact.
create table if not exists congress_trades (
  id              bigint generated always as identity primary key,
  ticker          text references securities(ticker),
  politician      text,
  chamber         text,                -- house | senate
  txn_type        text,                -- purchase | sale | exchange
  asset_type      text,                -- stock | call | put
  amount_range    text,                -- e.g. '$1,001 - $15,000'
  amount_low      numeric,             -- parsed floor of range
  amount_high     numeric,             -- parsed ceiling of range
  trade_date      date,
  disclosed_date  date,                -- often WEEKS after trade_date
  source          text default 'house_clerk',
  ingested_at     timestamptz default now(),
  unique (ticker, politician, trade_date, txn_type, amount_range)
);

create index if not exists idx_congress_ticker_date on congress_trades(ticker, trade_date desc);

-- 13F quarterly holdings, stored BY CUSIP + issuer (no CUSIP->ticker mapping — ticker
-- is optional/null by design). put_call in (LONG|PUT|CALL); snapshot only, ~45-day lag.
create table if not exists institutional_holdings (
  id             bigint generated always as identity primary key,
  ticker         text references securities(ticker),   -- optional; left null (no CUSIP->ticker map)
  cusip          text,
  issuer         text,                 -- issuer name as reported on the 13F
  fund_name      text,
  cik            text,
  value_usd      numeric,
  shares         numeric,
  pct_portfolio  numeric,
  put_call       text,                 -- LONG | PUT | CALL
  report_period  date,                 -- quarter end
  filed_date     date,
  source         text default 'sec_edgar',
  ingested_at    timestamptz default now(),
  unique (cik, cusip, report_period, put_call)
);

create index if not exists idx_inst_fund_period on institutional_holdings(fund_name, report_period desc);
create index if not exists idx_inst_cik_period  on institutional_holdings(cik, report_period desc);

comment on table institutional_holdings is
 'SEC 13F-HR quarterly holdings, stored BY CUSIP + issuer (no CUSIP->ticker mapping — ticker is '
 'optional/null by design). Long 13(f) securities only, ~45-day lag, quarterly. put_call in '
 '(LONG|PUT|CALL) — the PUT rows are how The Architect''s "short the hype" hedges show up. Feeds '
 'The Architect''s reporting. Retention: the two most recent report_periods per fund are kept so '
 'quarter-over-quarter moves stay computable (view institutional_moves). Completeness: every 13F '
 'filing seen on EDGAR is recorded in institutional_filings; institutional_coverage_gaps is the '
 'bot''s "am I missing a report?" check.';

-- Manifest of every 13F filing seen on EDGAR (the missing-report ledger). The ingester
-- writes a row per filing (ingested=false), then flips ingested=true + holdings_count once
-- holdings load. A missing report = an in-window row with ingested=false / holdings_count 0,
-- or a gap in the report_period sequence. See view institutional_coverage_gaps.
create table if not exists institutional_filings (
  accession      text primary key,
  cik            text,
  fund_name      text,
  form           text,                 -- 13F-HR | 13F-HR/A
  report_period  date,
  filed_date     date,
  holdings_count int,                  -- rows parsed & ingested for this filing (null = not yet)
  ingested       boolean default false,
  first_seen_at  timestamptz default now(),
  ingested_at    timestamptz
);

create index if not exists idx_inst_filings_cik_period on institutional_filings(cik, report_period desc);

-- The Architect's "am I missing a report?" check: within the tracked window (2 most recent
-- 13F periods), filings recorded from EDGAR not yet successfully ingested. Empty = complete.
create or replace view institutional_coverage_gaps with (security_invoker = true) as
with ranked as (
  select *, dense_rank() over (partition by cik order by report_period desc) as rk
  from institutional_filings
)
select accession, cik, fund_name, form, report_period, filed_date, holdings_count, ingested
from ranked
where rk <= 2 and (ingested is not true or coalesce(holdings_count, 0) = 0)
order by report_period desc;

-- The Architect's buy/sell history: quarter-over-quarter change per holding+instrument
-- (LONG/PUT/CALL) across the two retained periods — NEW / EXITED / ADDED / TRIMMED / HELD.
create or replace view institutional_moves with (security_invoker = true) as
with periods as (
  select cik, report_period,
         dense_rank() over (partition by cik order by report_period desc) as rk
  from (select distinct cik, report_period from institutional_holdings) p
),
cur as (select h.* from institutional_holdings h
        join periods pr on h.cik = pr.cik and h.report_period = pr.report_period and pr.rk = 1),
prv as (select h.* from institutional_holdings h
        join periods pr on h.cik = pr.cik and h.report_period = pr.report_period and pr.rk = 2)
select
  coalesce(cur.cik, prv.cik)                              as cik,
  coalesce(cur.fund_name, prv.fund_name)                 as fund_name,
  coalesce(cur.cusip, prv.cusip)                          as cusip,
  coalesce(cur.ticker, prv.ticker)                        as ticker,   -- resolved by ingest/cusip_resolve.py (OpenFIGI)
  coalesce(cur.issuer, prv.issuer)                        as issuer,
  coalesce(cur.put_call, prv.put_call)                    as put_call,
  cur.report_period                                       as cur_period,
  prv.report_period                                       as prv_period,
  prv.shares                                              as prev_shares,
  cur.shares                                              as curr_shares,
  coalesce(cur.shares, 0)   - coalesce(prv.shares, 0)     as shares_delta,
  coalesce(cur.value_usd,0) - coalesce(prv.value_usd,0)   as value_delta,
  case
    when prv.cusip is null then 'NEW'
    when cur.cusip is null then 'EXITED'
    when cur.shares > prv.shares then 'ADDED'
    when cur.shares < prv.shares then 'TRIMMED'
    else 'HELD'
  end                                                     as move
from cur full outer join prv
  on cur.cik = prv.cik and cur.cusip = prv.cusip and cur.put_call = prv.put_call;


-- ETF holdings — The Oracle's feed. Daily full-book snapshot of NANC (the ETF that
-- packages Democratic congressional disclosures), pulled from the fund administrator's
-- daily CSV by ingest/etf_holdings.py. One row per (fund, holding, day). ~101 rows/day.
-- Columns mirror the CSV. NOTE: `ticker` has NO securities FK — this is the full external
-- book (names we don't track included); the candidate view below joins to securities to
-- filter to the Oracle's universe. Ticker is normalized on ingest (e.g. GOOG -> GOOGL) so
-- it lines up with securities/price_history. Longer retention than news (a signal series).
create table if not exists etf_holdings (
  id              bigint generated always as identity primary key,
  fund            text not null,                 -- 'NANC' (GOP/KRUZ later if wanted)
  ticker          text,                          -- CSV StockTicker, normalized; no FK (see note)
  cusip           text,                          -- CSV CUSIP (bonus; no resolve needed)
  as_of_date      date not null,                 -- CSV Date
  shares          numeric,                       -- CSV Shares — THE active-decision field (6dp)
  fund_shares_out numeric,                        -- CSV SharesOutstanding; shares/fund_shares_out =
                                                 --   shares-per-unit, immune to price + create/redeem
  weight_pct      numeric,                       -- CSV Weightings (context; never signal on alone)
  market_value    numeric,                       -- CSV MarketValue
  ingested_at     timestamptz default now(),
  unique (fund, ticker, as_of_date)
);

create index if not exists idx_etf_holdings_fund_date on etf_holdings(fund, as_of_date desc);
create index if not exists idx_etf_holdings_ticker on etf_holdings(ticker, as_of_date desc);

-- Snapshot-over-snapshot change in SHARES-PER-UNIT (immune to price & create/redeem). This is
-- the diff that becomes an Oracle candidate. NEW = position appeared; a full EXIT drops out of
-- the CSV entirely (no row), which the long-only Oracle ignores anyway. security_invoker → RLS.
create or replace view etf_holdings_delta with (security_invoker = true) as
with snaps as (
  select fund, ticker, as_of_date, weight_pct, market_value, shares,
         shares / nullif(fund_shares_out, 0)                                    as spu,
         lag(shares / nullif(fund_shares_out, 0))
           over (partition by fund, ticker order by as_of_date)                 as prev_spu,
         lag(as_of_date)
           over (partition by fund, ticker order by as_of_date)                 as prev_date
  from etf_holdings
)
select
  fund, ticker, as_of_date, prev_date, weight_pct, market_value, shares, spu, prev_spu,
  (spu - coalesce(prev_spu, 0))                                                 as d_spu,
  case when coalesce(prev_spu, 0) = 0 then null
       else round(100 * (spu - prev_spu) / prev_spu, 2) end                     as d_spu_pct,
  case
    when prev_spu is null or prev_spu = 0   then 'NEW'
    when spu = 0                            then 'EXITED'
    when spu > prev_spu                     then 'ADDED'
    when spu < prev_spu                     then 'TRIMMED'
    else 'HELD'
  end                                                                           as move
from snaps;

-- The Oracle's selectivity Gates 1-3 (see personas/the_oracle/nanc-restructure.md). Gate 4
-- (rank by conviction, top-1/snapshot + 10-trading-day cooldown) is applied in map_personas.
-- Gate 1: mega-cap-tech lane (watchlist join). Gate 2: long striker (NEW/ADDED). Gate 3: real
-- accumulation (NEW, or >=20% shares-per-unit rise landing at >=1% weight). Thresholds are the
-- proposed starting values — tune before trusting (nanc-restructure.md, open decision #3).
create or replace view the_oracle_candidates with (security_invoker = true) as
select d.fund, d.ticker, d.as_of_date, d.move, d.d_spu_pct, d.weight_pct, d.market_value, d.shares
from etf_holdings_delta d
join securities s on s.ticker = d.ticker
where d.fund = 'NANC'
  and s.watchlist in ('AI Infra + Power', 'Mega-Cap Core')      -- Gate 1
  and d.move in ('NEW', 'ADDED')                                -- Gate 2
  and (d.move = 'NEW' or (d.d_spu_pct >= 20 and d.weight_pct >= 1.0))  -- Gate 3
order by d.as_of_date desc, d.weight_pct desc;


-- ------------------------------------------------------------
-- LAYER 3: PERSONAS
-- ------------------------------------------------------------

-- One row per character. Voice bible lives in the repo (personas/<slug>/persona.md);
-- this table holds the queryable metadata + which raw data feeds it.
create table if not exists personas (
  slug           text primary key,     -- the_oracle | the_house | the_architect
  display_name   text,
  tagline        text,
  style_summary  text,
  source_type    text,                 -- congress | insider | institutional
  source_key     text,                 -- matches politician / fund_name / insider_name
  active         boolean default true,
  created_at     timestamptz default now()
);

-- Normalized trade feed per persona. Populated from the raw tables by a mapper,
-- so the sim reads ONE consistent shape regardless of source.
create table if not exists persona_trades (
  id             bigint generated always as identity primary key,
  persona        text references personas(slug),
  ticker         text references securities(ticker),
  side           text,                 -- buy | sell
  trade_date     date,
  disclosed_date date,
  amount_usd     numeric,              -- midpoint if source only gives a range
  amount_is_est  boolean default false,
  source_table   text,                 -- insider_trades | congress_trades | institutional_holdings
  source_id      bigint,
  created_at     timestamptz default now(),
  unique (persona, ticker, trade_date, side, source_table, source_id)
);

create index if not exists idx_ptrades_persona_date on persona_trades(persona, trade_date desc);


-- ------------------------------------------------------------
-- LAYER 4: SIMULATION
--
-- The sim is a HEADLESS terminal program — no GUI, no dashboard, no visualization.
-- The interactive layer runs like *Zork in a terminal*: a text REPL where you type
-- "@<persona> <question>" and it answers in-character.
--   sim/backtest.py  — replays each persona's disclosed trades against price_history,
--                      writes one row per trade to `backtests`.
--   sim/streak.py    — classifies those into a state, writes `persona_performance`.
--   sim/terminal.py  — the Zork REPL; reads persona_performance + backtests +
--                      persona_calls + the repo voice bible, narrates. Data -> state -> voice.
-- Locked knobs: price_basis = next_open · fixed $/trade (selection, not sizing) ·
--   hold_days in TRADING days (21 / 63). See TODO.md "Open decisions" for streak thresholds.
-- ------------------------------------------------------------

-- One row per backtested trade. Fractional shares carried to 6 decimals —
-- no whole-share rounding, matching how Robinhood actually fills dollar orders.
create table if not exists backtests (
  id             bigint generated always as identity primary key,
  persona        text references personas(slug),
  ticker         text references securities(ticker),
  entry_date     date,
  exit_date      date,
  hold_days      int,
  price_basis    text,                 -- close_to_close | next_open
  amount_usd     numeric,
  entry_price    numeric,
  shares         numeric(20,6),        -- fractional, 6dp
  exit_price     numeric,
  exit_value     numeric,
  net_usd        numeric,
  net_pct        numeric,
  spy_return_pct numeric,              -- benchmark over same window
  alpha_pct      numeric,              -- net_pct - spy_return_pct
  is_win         boolean,
  run_id         uuid,
  created_at     timestamptz default now()
);

create index if not exists idx_backtests_persona on backtests(persona, entry_date desc);

-- Rolling streak state. Recomputed after every sim run.
-- state drives the persona's VOICE. Data -> state -> voice. Never the reverse.
-- NOTE: window_label, not `window` — 'window' is a reserved keyword in Postgres.
create table if not exists persona_performance (
  id            bigint generated always as identity primary key,
  persona       text references personas(slug),
  window_label  text,                  -- 30d | 90d | ytd | all
  trades_closed int,
  hit_rate      numeric,               -- 0..1
  net_return    numeric,               -- % over window
  alpha_vs_spy  numeric,
  streak_run    int,                   -- + = consecutive wins, - = consecutive losses
  trend         text,                  -- improving | decaying | flat
  state         text,                  -- winning | losing | stagnant
  computed_at   timestamptz default now(),
  unique (persona, window_label, computed_at)
);

create index if not exists idx_perf_persona on persona_performance(persona, computed_at desc);

-- Persona reactions ledger: every call a persona makes, what the user did about it,
-- whether that was agreement or defiance, and (graded later) who was right. This is the
-- persona-vs-user scorecard — inspired by companion-reputation systems.
create table if not exists persona_calls (
  id              bigint generated always as identity primary key,
  persona         text references personas(slug),
  ticker          text references securities(ticker),
  call_date       date not null,
  verdict         text not null,        -- buy | speculative | watch | hold | avoid | trim | sell
  register        text,                 -- persona conviction at call time (clarion|murk|silence, or streak state)
  rationale       text,                 -- the sign / reason given
  call_price      numeric,              -- price at the moment of the call (scoring baseline)
  user_action     text,                 -- bought | sold | trimmed | held | none
  agreement       text,                 -- agree | disagree | n/a
  reaction        text,                 -- flavor tag, e.g. 'The Herald will remember this.'
  linked_order    text,                 -- brokerage order id if the user acted
  scored_date     date,                 -- null until graded
  score_price     numeric,
  return_pct      numeric,              -- call_price -> score_price
  spy_return_pct  numeric,              -- benchmark over same window
  alpha_pct       numeric,
  verdict_correct boolean,              -- did the call prove right, given its intent?
  created_at      timestamptz default now(),
  unique (persona, ticker, call_date, verdict)
);

create index if not exists idx_persona_calls_persona on persona_calls(persona, call_date desc);
create index if not exists idx_persona_calls_open on persona_calls(scored_date) where scored_date is null;


-- ------------------------------------------------------------
-- LAYER 5: NARRATIVE OUTPUT
-- ------------------------------------------------------------

-- In-voice monthly/quarterly writeups, generated from backtests + persona_performance.
-- Optional under the Zork terminal model — the REPL can narrate live from state; these
-- are pre-baked flavor/history, not required plumbing. This is what Claude retrieves.
create table if not exists persona_reports (
  id             bigint generated always as identity primary key,
  persona        text references personas(slug),
  period_type    text,                 -- monthly | quarterly
  period_label   text,                 -- 2026-07 | 2026-Q3
  period_start   date,
  period_end     date,
  state_at_close text,                 -- streak state when written
  body_md        text,                 -- the in-voice report
  metrics        jsonb,                -- snapshot of the numbers it was built from
  created_at     timestamptz default now(),
  unique (persona, period_type, period_label)
);

-- Scored signals: raw filings become decisions here.
-- Cluster > lone. 'P' code only. CEO/CFO weighted above VP.
create table if not exists watchlist_signals (
  id           bigint generated always as identity primary key,
  ticker       text references securities(ticker),
  signal_type  text,                   -- insider_cluster | congress_buy | fund_new_position
  score        numeric,                -- 0..100
  rationale    text,
  persona      text references personas(slug),
  created_at   timestamptz default now()
);

create index if not exists idx_signals_score on watchlist_signals(score desc, created_at desc);

-- Runtime news feed. Populated nightly by the Railway cron (ingest/news.py) from
-- Finnhub (market + per-ticker company news). The personas query THIS at runtime via
-- MCP — it is the automated source of truth for headlines; the markdown archive under
-- personas/the_herald/headlines/ was the manual bootstrap. (A thematic world-news
-- source for the non-finance watches is TBD — GDELT was dropped, it blocks cloud IPs.)
create table if not exists market_news (
  id            bigint generated always as identity primary key,
  watch         text,                 -- energy|war|power|ai|media|mergers|stocks (nullable)
  ticker        text,                 -- optional loose tag (no FK; news can name any symbol)
  headline      text not null,
  summary       text,
  source        text,                 -- publisher / domain
  url           text unique,          -- dedup key for upsert
  published_at  timestamptz,
  source_api    text,                 -- finnhub_general | finnhub_company | gdelt
  ingested_at   timestamptz default now()
);

create index if not exists idx_market_news_published on market_news(published_at desc);
create index if not exists idx_market_news_watch on market_news(watch, published_at desc);
create index if not exists idx_market_news_ticker on market_news(ticker, published_at desc);

-- Runtime social-buzz feed for The Shut-In (🛋️, slug the_shutin — the Reddit momentum
-- persona). Populated nightly by its OWN Railway cron service (ingest/reddit_sentiment.py,
-- config railway.reddit.toml) via the Composio Reddit connector — Composio makes the call
-- from its own servers, so Railway's datacenter IP is never blocked (the wall that killed
-- GDELT). PURE MOMENTUM: the signal is mention VELOCITY (acceleration), not raw volume.
-- Aggregates only (a few dozen rows/night); 3-month rolling retention like market_news.
-- Three-tier funnel per subreddit: count every mention incl. the daily-megathread comments
-- (velocity) -> keyword the top-3 posts (tilt) -> LLM-read the top-1 post (the story, 4/night).
create table if not exists reddit_buzz (
  id           bigint generated always as identity primary key,
  ticker       text references securities(ticker),
  buzz_date    date not null,
  subreddit    text not null,          -- wallstreetbets | stocks | StockMarket | options
  mentions     int  not null default 0, -- tier 1: count of ALL matched posts/comments
  bull_kw      int  default 0,          -- tier 2: bullish keyword hits across top-3 posts
  bear_kw      int  default 0,          -- tier 2: bearish keyword hits across top-3 posts
  top_score    int,                     -- engagement (score+comments) of the loudest post
  ingested_at  timestamptz default now(),
  unique (ticker, buzz_date, subreddit)
);

create index if not exists idx_reddit_buzz_date on reddit_buzz(buzz_date desc);
create index if not exists idx_reddit_buzz_ticker on reddit_buzz(ticker, buzz_date desc);

-- The tier-3 deep read: the top-1 post per subreddit we LLM-summarized (4/night).
-- The Shut-In's VOICE material — the hearsay/thesis it repeats. Grain = per post.
create table if not exists reddit_threads (
  id           bigint generated always as identity primary key,
  post_id      text unique,             -- Reddit base-36 id (dedup key for upsert)
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

-- Velocity: today's mentions vs the prior day per ticker (summed across subreddits).
-- The momentum tell is ACCELERATION, not raw volume. security_invoker respects base RLS.
create or replace view the_shutin_velocity with (security_invoker = true) as
select
  ticker,
  buzz_date,
  sum(mentions)                                                    as mentions,
  lag(sum(mentions)) over (partition by ticker order by buzz_date) as mentions_prev,
  sum(bull_kw)                                                     as bull_kw,
  sum(bear_kw)                                                     as bear_kw
from reddit_buzz
group by ticker, buzz_date;

-- The Shut-In board: the latest day's movers ranked by velocity (mentions vs prior day),
-- with the crude keyword tilt. The persona joins this to reddit_threads for the "story".
create or replace view the_shutin_board with (security_invoker = true) as
select
  v.ticker,
  v.buzz_date,
  v.mentions,
  v.mentions_prev,
  round(v.mentions::numeric / nullif(v.mentions_prev, 0), 2) as velocity_x,  -- 5.0 = 5x prior day
  case
    when v.bull_kw + v.bear_kw = 0 then 'flat'
    when v.bull_kw >= 2 * greatest(v.bear_kw, 1) then 'bull'
    when v.bear_kw >= 2 * greatest(v.bull_kw, 1) then 'bear'
    else 'mixed'
  end as tilt
from the_shutin_velocity v
where v.buzz_date = (select max(buzz_date) from reddit_buzz)
order by velocity_x desc nulls last, v.mentions desc;

-- Coverage blind spots: US tickers we've TRADED with NO chatter in the last 7 days.
-- Analog to insider_coverage_gaps — the persona flags silence as a blind spot, not calm.
create or replace view the_shutin_coverage_gaps with (security_invoker = true) as
select s.ticker, s.name, s.sector
from securities s
where s.ever_traded
  and not exists (
    select 1 from reddit_buzz b
    where b.ticker = s.ticker
      and b.buzz_date > current_date - 7
  );

-- The Shut-In signal notes, stored as queryable schema metadata.
comment on table reddit_buzz is
 'Per-day, per-subreddit Reddit mention aggregates for The Shut-In (source: Reddit via '
 'Composio). PURE MOMENTUM: the signal is VELOCITY (mentions vs prior day), not raw volume. '
 'Tiers: count every mention (velocity) -> keyword top-3 posts/sub (bull_kw/bear_kw tilt) -> '
 'LLM top-1 post/sub (see reddit_threads). Unverified hearsay incl. pumps/bots — rides '
 'momentum, never fades it; state is P&L-scored (signal-stage until price_history exists).';
comment on view the_shutin_board is
 'The Shut-In daily board: latest-day tickers ranked by velocity_x (mention acceleration) with '
 'keyword tilt. Join reddit_threads for the story behind the buzz.';
comment on view the_shutin_coverage_gaps is
 'US traded tickers with no Reddit chatter in the last 7 days — the persona flags silence as a '
 'blind spot, not calm.';


-- ------------------------------------------------------------
-- LAYER 6: OPS
-- ------------------------------------------------------------

create table if not exists ingest_runs (
  id            bigint generated always as identity primary key,
  source        text,
  rows_ingested int,
  status        text,                  -- ok | partial | failed
  error_msg     text,
  duration_ms   int,
  ran_at        timestamptz default now()
);


-- ------------------------------------------------------------
-- SEED: securities (watchlist tickers + benchmark)
-- Seeded so the FK-bearing raw/price tables have parents to reference.
-- ------------------------------------------------------------

insert into securities (ticker, name, sector, asset_type) values
  ('NVDA',  'NVIDIA Corp',            'Technology',    'equity'),
  ('VST',   'Vistra Corp',            'Utilities',     'equity'),
  ('BE',    'Bloom Energy Corp',      'Industrials',   'equity'),
  ('CRWV',  'CoreWeave Inc',          'Technology',    'equity'),
  ('CEG',   'Constellation Energy',   'Utilities',     'equity'),
  ('AAPL',  'Apple Inc',              'Technology',    'equity'),
  ('MSFT',  'Microsoft Corp',         'Technology',    'equity'),
  ('GOOGL', 'Alphabet Inc',           'Communication', 'equity'),
  ('AMZN',  'Amazon.com Inc',         'Consumer',      'equity'),
  ('META',  'Meta Platforms Inc',     'Communication', 'equity'),
  ('AVGO',  'Broadcom Inc',           'Technology',    'equity'),
  ('VOO',   'Vanguard S&P 500 ETF',   'Index',         'etf'),
  ('SPY',   'SPDR S&P 500 ETF Trust', 'Index',         'etf'),
  ('SONY',  'Sony Group Corp (ADR)',  'Technology',    'equity')
on conflict (ticker) do nothing;

-- Form-4 eligibility + traded flags (ETFs/ADRs don't file Form 4).
update securities set form4_eligible = false where asset_type = 'etf' or ticker = 'SONY';
update securities set ever_traded    = true  where ticker in ('CRWV','SPY','SONY','GOOGL','BE');

-- 💧 Water theme (added 2026-07): utilities + treatment + a water-ETF benchmark.
insert into securities (ticker, name, sector, asset_type, form4_eligible, watchlist) values
  ('AWK',  'American Water Works',        'Utilities',   'equity', true,  'Water'),
  ('WTRG', 'Essential Utilities',         'Utilities',   'equity', true,  'Water'),
  ('AWR',  'American States Water',       'Utilities',   'equity', true,  'Water'),
  ('XYL',  'Xylem Inc',                   'Industrials', 'equity', true,  'Water'),
  ('PNR',  'Pentair plc',                 'Industrials', 'equity', true,  'Water'),
  ('VLTO', 'Veralto Corp',                'Industrials', 'equity', true,  'Water'),
  ('PHO',  'Invesco Water Resources ETF', 'Index',       'etf',    false, 'Water')
on conflict (ticker) do nothing;

-- Theme tags mirroring the Robinhood watchlists (SONY intentionally left untagged).
update securities set watchlist = 'Mega-Cap Core'    where ticker in ('AVGO','META','AMZN','GOOGL','MSFT','AAPL');
update securities set watchlist = 'AI Infra + Power' where ticker in ('NVDA','VST','BE','CRWV','CEG');
update securities set watchlist = 'Index Anchor'     where ticker in ('SPY','VOO');


-- ------------------------------------------------------------
-- SEED: the three personas
-- ------------------------------------------------------------

insert into personas (slug, display_name, tagline, style_summary, source_type, source_key) values
  ('the_house',     'The House',     'The house always wins.',
   'Broad index-like ownership, bond ballast, high turnover but effectively passive. Rides the market, never sweats a single name.',
   'congress', 'Donald Trump'),
  ('the_oracle',    'The Oracle',    'Patience, then the strike.',
   'Rare, concentrated mega-cap tech bets. Long-dated LEAPS leverage. Trades infrequently with uncanny timing.',
   'congress', 'Nancy Pelosi'),
  ('the_architect', 'The Architect', 'Long the future, short the hype.',
   'Thesis barbell: long AI infrastructure and power, hedged with puts against overheated chip names. Multi-year conviction.',
   'institutional', 'Situational Awareness LP')
on conflict (slug) do nothing;

-- The Insider — signal-stage persona (active=false until it has a backtested record).
-- (The Herald [news] and The Empath [meta] are also registered in the live DB.)
insert into personas (slug, display_name, tagline, style_summary, source_type, source_key, active) values
  ('the_insider', 'The Insider', 'The ones who know, buy.',
   'Follows corporate insiders'' open-market PURCHASES (SEC Form 4 code P) — the highest-conviction tell. Weights clusters over lone buys, CEO/CFO over director/VP, and buying into weakness over strength; ignores S/A/M grants & exercises and 10b5-1 scheduled trades. US operating companies only (ETFs/ADRs have no insiders). Data: Finnhub insider transactions (free tier, ~2-day filing lag, incomplete, no title field). Flags US traded stocks missing from the report via insider_coverage_gaps and asks for a refresh. Signal-stage: not yet a backtested live persona.',
   'insider', null, false)
on conflict (slug) do nothing;

-- The Shut-In — signal-stage momentum persona (active=false until price_history scores it).
-- Data feed is LIVE (its own Railway cron writes reddit_buzz nightly via Composio Reddit).
insert into personas (slug, display_name, tagline, style_summary, source_type, source_key, active) values
  ('the_shutin', 'The Shut-In', 'I never leave the room — but I hear everything.',
   'Momentum reader of the trading subreddits (r/wallstreetbets, r/stocks, r/StockMarket, r/options). PURE MOMENTUM: rides the crowd''s buzz, never fades it; the signal is mention VELOCITY (acceleration), not raw volume. Three-tier funnel per subreddit: count every mention (velocity) -> keyword the top-3 posts (tilt) -> LLM-read the top-1 post (the story, 4 reads/night). Everything is UNVERIFIED HEARSAY incl. pumps/bots — flags the source every line and de-weights itself out loud when cold. Data: Reddit via Composio connector (the_shutin_board / reddit_buzz). Named for the hikikomori archetype. Signal-stage: not yet a backtested live persona.',
   'social', null, false)
on conflict (slug) do nothing;


-- ------------------------------------------------------------
-- SECURITY: enable RLS on every table (no policies).
-- The anon/authenticated roles are denied entirely; the server-side
-- service-role key bypasses RLS, so the pipeline and MCP keep full access.
-- Add per-table policies here if a public/authenticated client is ever introduced.
-- ------------------------------------------------------------

alter table public.securities             enable row level security;
alter table public.price_history          enable row level security;
alter table public.insider_trades         enable row level security;
alter table public.congress_trades        enable row level security;
alter table public.institutional_holdings enable row level security;
alter table public.institutional_filings  enable row level security;
alter table public.personas               enable row level security;
alter table public.persona_trades         enable row level security;
alter table public.backtests              enable row level security;
alter table public.persona_performance    enable row level security;
alter table public.persona_calls          enable row level security;
alter table public.persona_reports        enable row level security;
alter table public.watchlist_signals      enable row level security;
alter table public.market_news            enable row level security;
alter table public.reddit_buzz            enable row level security;
alter table public.reddit_threads         enable row level security;
alter table public.ingest_runs            enable row level security;
