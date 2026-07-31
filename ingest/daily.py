"""Daily pull for the Railway cron: prices + news + insider + 13F, in one run.

Runs each sub-pull independently and guards it, so one failing (or exiting
non-zero on a no-op) never kills the others. The root railway.toml pins every
cron service to this entrypoint, so all ingesters live here as guarded steps.

Run:  python -m ingest.daily
"""
from __future__ import annotations

import logging

from ingest import architect_13f, etf_holdings, insider, news, prices

log = logging.getLogger("ingest.daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _run(name: str, fn) -> None:
    try:
        fn()
        log.info("daily: %s completed", name)
    except SystemExit as e:            # sub-pulls raise SystemExit on a no-op run
        log.warning("daily: %s exited (%s)", name, e)
    except Exception as e:             # noqa: BLE001 — one feed must not kill the others
        log.error("daily: %s crashed: %s", name, e)


def main() -> None:
    _run("prices", prices.main)                 # split-adjusted daily OHLCV → price_history (the sim's fuel)
    _run("news", news.main)
    _run("insider", insider.main)
    _run("architect_13f", architect_13f.main)   # SEC 13F → The Architect (quarterly; no-ops between filings)
    _run("etf_holdings", etf_holdings.main)      # NANC daily holdings → The Oracle
    # NOTE: Reddit/The Shut-In is NOT here — it runs as its OWN Railway cron service
    # (startCommand: python -m ingest.reddit_sentiment). Kept separate so its Composio
    # dependency and cadence are isolated from the core disclosure feeds.


if __name__ == "__main__":
    main()
