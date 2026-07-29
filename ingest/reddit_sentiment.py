"""Nightly Reddit social-buzz ingestion for Hikikomori (pure-momentum persona).

Runs headless on Railway (cron) — no browser. Reddit is reached through the **Composio**
connector: Composio executes the call from ITS OWN servers and returns JSON, so Railway's
datacenter IP is never blocked (the wall that killed GDELT). The Composio connection is
confirmed live; see the ⚠️ note on `_composio_execute` for the one thing to verify on the
first Railway run.

Pure momentum — the signal is mention VELOCITY (acceleration), computed by the
`hikikomori_velocity` view, not here. This module only writes today's raw counts. A
three-tier funnel per subreddit keeps cost fixed regardless of how wild the crowd is:

  tier 1 — count every ticker mention (incl. the daily-megathread comments) -> `mentions`
  tier 2 — keyword-scan the top 3 posts                                     -> bull_kw/bear_kw
  tier 3 — LLM-read the top 1 post (4 reads/night total)                    -> reddit_threads

Writes aggregates into Supabase `reddit_buzz` + `reddit_threads`, trims the rolling 3-month
window, and writes an `ingest_runs` audit row. The persona reads `hikikomori_board` at runtime.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY       (required)
  COMPOSIO_API_KEY                         (required — Reddit via Composio)
  COMPOSIO_BASE_URL   default v3 execute   (backend.composio.dev/api/v3)
  (the Reddit connection's user_id + connected_account_id are auto-resolved at runtime
   from /connected_accounts — no need to set COMPOSIO_REDDIT_ACCOUNT_ID / COMPOSIO_USER_ID)
  ANTHROPIC_API_KEY                        (optional; tier-3 LLM read skipped if unset)
  SOCIAL_RETENTION_DAYS   default "90"

Deploy: its OWN Railway cron service (config `railway.reddit.toml`, startCommand
`python -m ingest.reddit_sentiment`) — kept separate from ingest.daily so its Composio
dependency and cadence are isolated from the core disclosure feeds.

Run:  python -m ingest.reddit_sentiment
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from db.client import get_client

log = logging.getLogger("ingest.reddit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HTTP_TIMEOUT = 30

# The four highest-momentum trading subreddits (see personas/hikikomori/persona.md).
SUBREDDITS = ["wallstreetbets", "stocks", "StockMarket", "options"]

# Only count mentions of names we actually care about (watchlist + traded). Mirrors the
# securities seed; loaded from the DB at runtime so it stays in sync, with this as fallback.
FALLBACK_TICKERS = {
    "NVDA", "VST", "BE", "CRWV", "CEG",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO",
    "SPY", "VOO", "SONY",
}
# Tickers that are also common English words — count ONLY the $CASHTAG form to avoid noise
# (e.g. bare "BE" matches the verb "be"). $BE still counts.
CASHTAG_ONLY = {"BE"}

CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
BARE = re.compile(r"\b([A-Z]{2,5})\b")

BULL_WORDS = {
    "calls", "call", "moon", "🚀", "long", "buy", "bought", "bullish", "yolo",
    "squeeze", "breakout", "rip", "printing", "tendies", "green", "pump",
}
BEAR_WORDS = {
    "puts", "put", "short", "sell", "sold", "bearish", "dump", "crash", "drop",
    "bag", "bagholder", "rug", "red", "tank", "guh",
}

HAIKU = "claude-haiku-4-5-20251001"   # cheap model for the tier-3 read


# --------------------------------------------------------------------------- Composio

def _composio_base() -> tuple[str, str]:
    return (os.environ["COMPOSIO_API_KEY"],
            os.environ.get("COMPOSIO_BASE_URL", "https://backend.composio.dev/api/v3"))


_reddit_conn: "tuple[str, str] | None" = None   # (user_id, connected_account_id), cached


def _resolve_reddit_connection() -> tuple[str, str]:
    """Auto-resolve the ACTIVE Reddit connection's real (user_id, connected_account_id) from
    Composio's /connected_accounts — so we never hardcode account-specific ids.

    The MCP's word_id (e.g. reddit_torus-vervel) is NOT the REST connected_account_id
    (a `ca_...` nanoid), and the entity is not 'default' — both must come from the API.
    """
    global _reddit_conn
    if _reddit_conn is not None:
        return _reddit_conn
    api_key, base = _composio_base()
    r = requests.get(f"{base}/connected_accounts", params={"toolkit_slugs": "reddit"},
                     headers={"x-api-key": api_key}, timeout=HTTP_TIMEOUT)
    if not r.ok:
        raise RuntimeError(f"composio connected_accounts {r.status_code}: {r.text[:400]}")
    items = (r.json() or {}).get("items", [])
    reddit = [it for it in items if (it.get("toolkit") or {}).get("slug") == "reddit"]
    active = [it for it in reddit if it.get("status") == "ACTIVE"] or reddit
    if not active:
        raise RuntimeError("no reddit connected account found via /connected_accounts")
    acct = active[0]
    _reddit_conn = (acct.get("user_id"), acct.get("id"))
    log.info("resolved reddit connection: user_id=%s account=%s", *_reddit_conn)
    return _reddit_conn


def _composio_execute(tool_slug: str, arguments: dict) -> dict:
    """Execute a Composio tool via the REST v3 API (POST /tools/execute/{slug}, header
    x-api-key). Body needs user_id (entity) + connected_account_id + arguments; BOTH ids
    are auto-resolved from /connected_accounts. On a non-2xx we raise the body verbatim."""
    api_key, base = _composio_base()
    user_id, account_id = _resolve_reddit_connection()
    payload = {"user_id": user_id, "connected_account_id": account_id, "arguments": arguments}
    r = requests.post(
        f"{base}/tools/execute/{tool_slug}",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    if not r.ok:
        raise RuntimeError(f"composio {r.status_code} {tool_slug}: {r.text[:600]}")
    return r.json()


def _children(resp: dict) -> list[dict]:
    """Pull the Reddit listing children out of Composio's response, tolerating the
    variable nesting (`data.children` vs an extra `data.data.children` wrapper)."""
    node = resp.get("data", resp) if isinstance(resp, dict) else {}
    for _ in range(3):  # unwrap up to a couple of `data` layers
        if isinstance(node, dict) and "children" in node:
            break
        if isinstance(node, dict) and "data" in node:
            node = node["data"]
        else:
            break
    children = node.get("children", []) if isinstance(node, dict) else []
    return [c.get("data", {}) for c in children if isinstance(c, dict) and c.get("kind") in ("t3", "t1")]


def _fetch_hot(subreddit: str) -> list[dict]:
    resp = _composio_execute(
        "REDDIT_RETRIEVE_REDDIT_POST",
        {"subreddit": subreddit, "sort": "hot", "max_results": 100},
    )
    return _children(resp)


def _fetch_comments(article_id: str) -> list[dict]:
    """Comments of one post (the WSB daily megathread is where the cashtags actually live)."""
    resp = _composio_execute(
        "REDDIT_RETRIEVE_POST_COMMENTS",
        {"article": article_id, "sort": "top", "limit": 200, "depth": 2},
    )
    return _children(resp)


# --------------------------------------------------------------------------- parsing

def _extract_tickers(text: str, valid: set[str]) -> set[str]:
    found: set[str] = set()
    for m in CASHTAG.finditer(text or ""):
        sym = m.group(1).upper()
        if sym in valid:
            found.add(sym)
    for m in BARE.finditer(text or ""):
        sym = m.group(1)
        if sym in valid and sym not in CASHTAG_ONLY:
            found.add(sym)
    return found


def _post_text(p: dict) -> str:
    return f"{p.get('title', '')}\n{p.get('selftext', '') or p.get('body', '')}"


def _keyword_counts(text: str) -> tuple[int, int]:
    low = (text or "").lower()
    bull = sum(low.count(w) for w in BULL_WORDS)
    bear = sum(low.count(w) for w in BEAR_WORDS)
    return bull, bear


# --------------------------------------------------------------------------- tier 3 (LLM)

def _llm_read(post: dict, valid: set[str]) -> dict | None:
    """Summarize WHY the loudest post is buzzing. Guarded — a failure just drops the story."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic not installed — skipping tier-3 read")
        return None
    try:
        client = Anthropic()
        text = _post_text(post)[:4000]
        prompt = (
            "This is a post from a trading subreddit. In one sentence, say WHAT ticker(s) it's "
            "about and WHY the crowd is buzzing (the thesis/rumor). Then give an overall lean.\n"
            "Reply as compact JSON: {\"summary\": \"...\", \"tilt\": \"bull|bear|mixed\"}\n\n"
            f"POST:\n{text}"
        )
        msg = client.messages.create(
            model=HAIKU, max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text if msg.content else "{}"
        import json
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception as e:  # noqa: BLE001
        log.warning("llm read failed for %s: %s", post.get("id"), e)
        return None

    return {
        "post_id": post.get("id"),
        "subreddit": post.get("subreddit"),
        "title": post.get("title"),
        "permalink": "https://reddit.com" + (post.get("permalink") or ""),
        "score": post.get("score"),
        "num_comments": post.get("num_comments"),
        "tickers": sorted(_extract_tickers(_post_text(post), valid)),
        "summary": parsed.get("summary"),
        "llm_tilt": parsed.get("tilt"),
        "posted_at": _utc_iso(post.get("created_utc")),
    }


def _utc_iso(unix_ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


# --------------------------------------------------------------------------- per-subreddit

def _process_subreddit(sub: str, valid: set[str], today: str) -> tuple[list[dict], dict | None]:
    posts = _fetch_hot(sub)
    if not posts:
        return [], None

    ranked = sorted(posts, key=lambda p: (p.get("score") or 0) + (p.get("num_comments") or 0), reverse=True)

    # Tier 1 — count mentions across all post titles/bodies, PLUS the comments of the single
    # most-discussed post (on WSB that's the daily "What Are Your Moves" megathread, where the
    # cashtags actually live). One extra Composio call per sub.
    mentions: dict[str, int] = {}
    for p in posts:
        for tkr in _extract_tickers(_post_text(p), valid):
            mentions[tkr] = mentions.get(tkr, 0) + 1

    megathread = max(posts, key=lambda p: p.get("num_comments") or 0, default=None)
    if megathread and megathread.get("id"):
        try:
            for c in _fetch_comments(megathread["id"]):
                for tkr in _extract_tickers(c.get("body", ""), valid):
                    mentions[tkr] = mentions.get(tkr, 0) + 1
        except Exception as e:  # noqa: BLE001
            log.warning("comment fetch failed for %s/%s: %s", sub, megathread.get("id"), e)

    # Tier 2 — keyword the top 3 posts, attributing sentiment to the tickers each names.
    bull: dict[str, int] = {}
    bear: dict[str, int] = {}
    for p in ranked[:3]:
        b, be = _keyword_counts(_post_text(p))
        for tkr in _extract_tickers(_post_text(p), valid):
            bull[tkr] = bull.get(tkr, 0) + b
            bear[tkr] = bear.get(tkr, 0) + be

    top_score = (ranked[0].get("score") or 0) + (ranked[0].get("num_comments") or 0)
    buzz_rows = [
        {
            "ticker": tkr, "buzz_date": today, "subreddit": sub,
            "mentions": n, "bull_kw": bull.get(tkr, 0), "bear_kw": bear.get(tkr, 0),
            "top_score": top_score,
        }
        for tkr, n in mentions.items()
    ]

    # Tier 3 — LLM-read the single loudest post.
    thread = _llm_read(ranked[0], valid)
    return buzz_rows, thread


# --------------------------------------------------------------------------- main

def _load_tickers(client) -> set[str]:
    try:
        res = client.table("securities").select("ticker").execute()
        got = {r["ticker"] for r in (res.data or [])}
        return got or FALLBACK_TICKERS
    except Exception as e:  # noqa: BLE001
        log.warning("ticker load failed, using fallback: %s", e)
        return FALLBACK_TICKERS


def main() -> None:
    started = time.time()
    client = get_client()
    today = datetime.now(timezone.utc).date().isoformat()
    valid = _load_tickers(client)

    log.info("reddit ingest starting; composio_key=%s subs=%s tickers=%d",
             bool(os.environ.get("COMPOSIO_API_KEY")), SUBREDDITS, len(valid))

    buzz_rows: list[dict] = []
    thread_rows: list[dict] = []
    errors: list[str] = []

    for sub in SUBREDDITS:
        try:
            rows, thread = _process_subreddit(sub, valid, today)
            buzz_rows += rows
            if thread and thread.get("post_id"):
                thread_rows.append(thread)
            time.sleep(1.1)  # Reddit/Composio ~1-2 req/s
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sub}: {e}")
            log.warning("subreddit %s failed: %s", sub, e)

    inserted = 0
    try:
        if buzz_rows:
            client.table("reddit_buzz").upsert(
                buzz_rows, on_conflict="ticker,buzz_date,subreddit"
            ).execute()
            inserted += len(buzz_rows)
        if thread_rows:
            client.table("reddit_threads").upsert(
                thread_rows, on_conflict="post_id"
            ).execute()
            inserted += len(thread_rows)
    except Exception as e:  # noqa: BLE001
        errors.append(f"upsert: {e}")
        log.error("upsert failed: %s", e)

    # Retention: rolling 3-month window, same as market_news.
    retention_days = int(os.environ.get("SOCIAL_RETENTION_DAYS", "90"))
    try:
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=retention_days)).isoformat()
        client.table("reddit_buzz").delete().lt("buzz_date", cutoff).execute()
        ts_cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        client.table("reddit_threads").delete().lt("posted_at", ts_cutoff).execute()
    except Exception as e:  # noqa: BLE001
        errors.append(f"retention: {e}")
        log.warning("retention delete failed: %s", e)

    status = "ok" if (inserted and not errors) else "partial" if inserted else "failed"
    duration_ms = int((time.time() - started) * 1000)
    try:
        client.table("ingest_runs").insert({
            "source": "reddit",
            "rows_ingested": inserted,
            "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": duration_ms,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("reddit ingest %s: %d rows (%d buzz, %d threads) in %d ms (%d errors)",
             status, inserted, len(buzz_rows), len(thread_rows), duration_ms, len(errors))
    for e in errors:
        log.error("error: %s", e)
    if inserted == 0:
        raise SystemExit(1)   # surface a no-op as a failed run, like the other ingesters


if __name__ == "__main__":
    main()
