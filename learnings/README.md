# Learnings

Field notes from other people building **agentic / automated traders** — mostly Reddit
threads. We document what they built, what the crowd flagged, and what it means for *our*
system, so we inherit other people's failures instead of repeating them.

Each file = one thread. Format:

1. **Thread** — title, author, subreddit, score, date, links (post + any repo).
2. **What they built** — the system in a few bullets.
3. **Top comments** — the substantive ones, with author, score, and permalink.
4. **Learnings for us** — the distilled takeaways mapped onto our persona trading system
   (Data → State → Voice, manual-execution-only, backtest honesty).

Why we care: our system is also an agentic layer over markets. The failure modes other
builders hit — selection bias crowning noise, reference-price fills overstating edge,
guardrails that only *promise* not to misbehave — are the same ones that would quietly
corrupt our backtests and personas. Every entry should end with a concrete "so for us…".

## Index

| # | Thread | Source | Key theme |
|---|---|---|---|
| 01 | Evolutionary multi-agent crypto trader (evo-trader) | r/algotrading | Selection bias, null controls, structural guardrails |
