"""Daily Finnhub pull for the Railway cron: news + insider, in one run.

Runs each sub-pull independently and guards it, so one failing (or exiting
non-zero on a no-op) never kills the other. This lets a single Railway service
(the one that auto-deploys from GitHub) refresh both feeds nightly.

Run:  python -m ingest.daily
"""
from __future__ import annotations

import logging

from ingest import insider, news

log = logging.getLogger("ingest.daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _run(name: str, fn) -> None:
    try:
        fn()
        log.info("daily: %s completed", name)
    except SystemExit as e:            # sub-pulls raise SystemExit on a no-op run
        log.warning("daily: %s exited (%s)", name, e)
    except Exception as e:             # noqa: BLE001 — one feed must not kill the other
        log.error("daily: %s crashed: %s", name, e)


def main() -> None:
    _run("news", news.main)
    _run("insider", insider.main)


if __name__ == "__main__":
    main()
