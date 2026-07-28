# 01 — Evolutionary multi-agent crypto trading system (evo-trader)

## Thread

- **Title:** Built an evolutionary multi-agent crypto trading system — 5 strategies compete, best one mutates and repopulates each generation (open source)
- **Author:** u/Loud-Nefariousness45 (the OP / builder)
- **Subreddit:** r/algotrading
- **Score / comments:** 13 / 14 (at capture)
- **Posted:** ~2026-07-23
- **Post:** https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/
- **Repo:** https://github.com/hhhmehmet/evo-trader
- **Captured:** 2026-07-26 via Reddit API

> Disclaimer (OP's own): research/testing project, not financial advice, no guarantee of
> profitability, paper trading only, "no proven edge."

---

## What they built

- **5 isolated agents**, each a different strategy (momentum, mean-reversion,
  trend-following, breakout, volatility-squeeze), trading independently against **real
  Coinbase market data** over timed **"generations."**
- **Ranked by a composite score** — return, drawdown, Sharpe-like ratio, win rate, profit
  factor — *not* raw profit, "specifically so an agent that got lucky with one oversized
  bet doesn't win over a steadier performer."
- **Evolutionary loop:** the best strategy is cloned into **5 mutated descendants**
  (risk-param variants, indicator variants, one experimental) for the next generation.
  Repeat indefinitely.
- **Risk limits enforced *outside* strategy logic** — a hard-coded risk engine that
  strategies "structurally cannot reach or bypass," verified by an **AST scan** in the
  test suite that **fails the build** if a strategy file imports the risk-limits module
  directly. Caps: max loss per agent, max order size, max simultaneous positions.
- **Paper trading by default**, with a separately-gated live path (two env vars + a
  mechanically-verified pre-live checklist before any real order).
- **Null control run:** 200 generations against **synthetic random-walk data** to
  sanity-check the mechanics — it **lost money on average (~-4.2 TRY/generation)**,
  because there's no edge in pure noise. OP posted this deliberately: "I'd rather show the
  system measuring reality correctly than fake a good-looking result."
- **Stack:** Python, SQLite (full generation/lineage history), Streamlit dashboard, pytest
  (~180 tests).

---

## Top comments

**u/dawcza — score 11** ([link](https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/ozbfs6g/))
> "I suppose you used claude? It built me almost an identical thing a few months ago."
- Reply — u/Brianiac69: "Does it work?"
- Reply — **OP** (score -2): "almost everything ~80% of it from claude I dont write any
  codes anymore unless it has huge flaws." *(Downvoted — the sub reacted poorly to
  "I don't read the code anymore.")*

**OP, on structural sandboxing — score 5** ([link](https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/ozayxfu/))
> "AST scan is non negotiable. Coming from C/C++ and assembly, rule 1 is you never trust
> user space or dynamic code to behave. If an AI or strategy *can* break out and touch
> internal state, it eventually will… 4.2 TRY per gen on a pure random walk isn't bad —
> on pure noise that's basically just spread, slippage, and fees taking their cut. Main
> thing is the drawdown stays capped, so the risk engine is holding the line instead of
> blowing up the account."

**u/RegisteredJustToSay — score 1** ([link](https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/ozbjvkq/))
> "Wouldn't it be better to model these as microservices, or a purely functional interface
> you invoke remotely? The AST scan is a nice touch but you're still playing cat-and-mouse
> with the agent possibly messing with other system components."
- **OP's honest concession:** the AST scan "just checks for the obvious door, not bricking
  up the wall" — same-process bypasses remain (monkeypatching, `importlib`). Didn't split
  into a separate service because the loop trades off live ticks and RPC adds a network hop
  in the decision path. **"The honest framing is right now it's 'code promises not to' not
  'code literally can't.'"** The real fix: agent talks to the risk engine only over RPC, so
  there's no in-process reference to reach.
- Follow-up — RegisteredJustToSay: use **unix domain sockets** for that IPC — millions of
  msgs/sec, and it's easier to upgrade UDS→IP later than threads→IP.

**u/BrianBanks939393 — score 1** ([link](https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/ozd2ogu/))
> "The random-walk control run is the part most people skip… One thing I'd add: run the
> same 200 generations twice on identical real data with **different seeds** and compare
> final populations. Evolutionary search over a small strategy space has huge run-to-run
> variance; if two seeded runs converge on **different** winners with similar composite
> scores, generation-over-generation improvement is **drift, not learning.** I got burned
> on the single-run version — five 'improved' iterations that turned out to be inside the
> noise band."

**u/NeighborhoodDue5263 — score 1** ([link](https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/ozfxjgb/))
> "Since the agents trade against real Coinbase data in paper mode, are fills
> reference-price (instant, no slippage) or do they account for the fact that a bigger
> position would've actually moved the book? If it's the former, your generational ranking
> could be partly measuring **'who got a frictionless fill'** rather than 'who has a real
> edge' — especially once sizes diverge across the population."
- *(Soft plug for their own reactive-order-book tool, "MockMarket." Noted as vendor
  interest, but the fills-realism point stands.)*

**u/Zestyclose-Eagle1809 — score 1** ([link](https://www.reddit.com/r/algotrading/comments/1v4h5rs/built_an_evolutionary_multiagent_crypto_trading/ozk8bx8/))
> "The random walk run… is measuring the wrong number. Average agent loses 4.2 TRY/gen —
> that's the **mean**. Your system never trades the mean, it trades the **champion.** What
> did the winning agent's composite score look like on that synthetic data? If the best of
> 5 on pure noise scored like a real edge by your ranking, the ranking will crown noise on
> Coinbase data too and nothing downstream would catch it.
>
> Second… 200 generations × 5 agents = 1000 evaluations, and every one keeps the max. Best
> of 1000 draws scores well even when true edge is exactly zero — that's **mechanical**,
> not a flaw in the agents. So the trial count for any significance test is total agents
> ever evaluated, not 5."
- *(Founder of "Quantprove," validation tooling — disclosed. The multiple-testing point is
  the sharpest critique in the thread.)*

---

## Learnings for us

Our system is also an agentic layer over markets (backtest real disclosed trades → classify
a state → speak in voice). The same failure modes apply. Mapped to our design:

1. **Selection bias crowns noise — the single most transferable warning.** Best-of-N scores
   well even with zero true edge (Zestyclose, BrianBanks). We rank/curate too: signal
   scoring (`watchlist_signals`), and any "which persona is hot" comparison. Guard: judge a
   persona's state against a **null benchmark** (we already compute `alpha_pct` vs SPY —
   lean on it hard) and against **trial count**, not raw win counts. A persona that looks
   great only because we looked at three personas and picked the winner is noise.

2. **Run a null control.** Their random-walk run is the most-praised idea in the thread.
   Our analogue: backtest the simulator on **random entry dates / shuffled tickers** and
   confirm it produces ~zero alpha. If our pipeline manufactures alpha on noise, the bug is
   in the sim, not the strategy. Cheap, high-value, do it before trusting batch results.

3. **Reference-price fills overstate edge (NeighborhoodDue).** Directly hits our open
   `price_basis` decision and the CRWV validation gap we already flagged: a real Robinhood
   fill is intraday, our sim reads daily close/next-open. No slippage modeled = optimistic
   backtests. Keep this explicit; don't let a frictionless backtest masquerade as a live
   edge (matches our "disclosures are thematic, not live signal" rule).

4. **"Code promises not to" vs "code literally can't" (OP + RegisteredJustToSay).** This is
   our no-trade / watchlist-only constraint restated. Our hard rule is that the pipeline
   *never* places trades and voice *never* drives state. Aim for **structural** enforcement,
   not convention: no order-placement code path or brokerage credentials in the pipeline at
   all (so it *can't*), rather than a comment saying it shouldn't. Their AST-scan-fails-the-
   build trick is a concrete pattern we could copy — e.g., a test that fails the build if
   any pipeline module imports a Robinhood *write* client.

5. **Honesty about negative results is a feature.** OP shipped a losing number on purpose
   and the sub respected it. This *is* our Data → State → Voice ethos: a cold persona must
   tell the user to discount it; failing tests get reported, not hidden.

6. **"I don't read the code anymore" got downvoted.** ~80% Claude-written, and the one
   comment admitting he no longer reviews it was the only negative-scored reply. Cuts close
   to home — we're Claude-built too. The mitigation the crowd implicitly endorsed: the
   ~180-test suite and the AST guardrail. For us: verification (the CRWV validation gate,
   null controls, the RLS lockdown) is what earns trust in generated code.

7. **Reproducibility / seed variance (BrianBanks).** Less direct (we're not evolving a
   population), but the principle holds: if a result doesn't survive a re-run, it's drift.
   Any persona "improvement" over a window should be checked against variance before we let
   the voice register shift on it.
