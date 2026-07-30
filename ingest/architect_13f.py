"""SEC EDGAR 13F ingester — The Architect's holdings.

Pulls the tracked institutional filer's quarterly 13F-HR holdings straight from
SEC EDGAR (no key, no vendor) into Supabase `institutional_holdings`, keyed by
CUSIP + issuer (NO CUSIP->ticker mapping — this is the persona/data we want as-is).
Captures put_call (LONG/PUT/CALL) so The Architect's "short the hype" put hedges
are visible, not just the longs.

What it does each run:
  1. Lists the filer's 13F-HR filings from EDGAR submissions.
  2. Records every filing in `institutional_filings` (the manifest / missing-report
     ledger) — new ones as ingested=false.
  3. Ingests the INST_KEEP_PERIODS most recent quarters (default 2 — the minimum to
     compute quarter-over-quarter moves), upserting holdings and flipping the
     manifest row to ingested=true + holdings_count.
  4. Retention: keeps only those N periods per fund (older holdings are deleted).
     "We only go ~3 months back" for a quarterly feed = the latest quarter; we keep
     one extra prior quarter so new-entry / buy-sell history stays computable
     (view: institutional_moves). Set INST_KEEP_PERIODS=1 for strict single-quarter.
  5. Missing-report check: logs anything in `institutional_coverage_gaps` (a filing
     in the tracked window EDGAR shows but we haven't ingested).

EDGAR fair-access: every request sends SEC_USER_AGENT (a role contact, e.g.
"Chibibytes Research team@dulcenochemedia.com"); a generic/absent UA gets 403.
Rate limit <=10 req/s. Runs headless on Railway (same pattern as ingest/news.py).

Env:  SUPABASE_URL, SUPABASE_SERVICE_KEY, SEC_USER_AGENT   (required)
      ARCHITECT_CIK        default "0002045724"  (Situational Awareness LP)
      INST_KEEP_PERIODS    default "2"
Run:  python -m ingest.architect_13f
"""
from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from db.client import get_client

log = logging.getLogger("ingest.architect_13f")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HTTP_TIMEOUT = 30
SEC_PAUSE = 0.3  # be polite: EDGAR allows <=10 req/s

# Tracked filers → (padded CIK, fund_name matching personas.source_key).
FUNDS = [
    (os.environ.get("ARCHITECT_CIK", "0002045724").zfill(10), "Situational Awareness LP"),
]


def _headers() -> dict:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise SystemExit("SEC_USER_AGENT unset (EDGAR requires a contact user-agent)")
    return {"User-Agent": ua}


def sec_get_json(url: str) -> dict:
    r = requests.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    time.sleep(SEC_PAUSE)
    return r.json()


def sec_get_text(url: str) -> str:
    r = requests.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    time.sleep(SEC_PAUSE)
    return r.text


def _tag(t: str) -> str:
    return t.split("}")[-1]


def list_13f_filings(cik: str) -> list[dict]:
    """All 13F-HR filings for a CIK, most-recent report_period first."""
    subs = sec_get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    r = subs["filings"]["recent"]
    out = []
    for form, filed, acc, rep in zip(
        r["form"], r["filingDate"], r["accessionNumber"], r["reportDate"]
    ):
        if form.startswith("13F-HR"):
            out.append({"form": form, "filed": filed, "accession": acc, "period": rep})
    out.sort(key=lambda f: f["period"], reverse=True)
    return out


def parse_holdings(cik: str, accession: str) -> list[dict]:
    """Parse a 13F information table into aggregated holdings by (cusip, put_call)."""
    nd = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nd}/"
    idx = sec_get_json(base + "index.json")
    xmlname = next(
        i["name"] for i in idx["directory"]["item"]
        if i["name"].endswith(".xml") and i["name"] != "primary_doc.xml"
    )
    root = ET.fromstring(sec_get_text(base + xmlname))
    agg: dict[tuple, dict] = {}
    for el in root.iter():
        if _tag(el.tag) != "infoTable":
            continue
        d = {"put_call": "LONG"}
        for c in el.iter():
            tg = _tag(c.tag)
            if tg == "nameOfIssuer":
                d["issuer"] = (c.text or "").strip()[:80]
            elif tg == "cusip":
                d["cusip"] = (c.text or "").strip()
            elif tg == "value":
                d["value"] = int(float(c.text or 0))
            elif tg == "sshPrnamt":
                d["shares"] = int(float(c.text or 0))
            elif tg == "putCall":
                d["put_call"] = (c.text or "LONG").strip().upper() or "LONG"
        key = (d.get("cusip"), d["put_call"])
        if key in agg:
            agg[key]["value"] += d.get("value", 0)
            agg[key]["shares"] += d.get("shares", 0)
        else:
            agg[key] = {
                "cusip": d.get("cusip"), "issuer": d.get("issuer"),
                "put_call": d["put_call"], "value": d.get("value", 0),
                "shares": d.get("shares", 0),
            }
    return list(agg.values())


def ingest_fund(client, cik: str, fund_name: str, keep: int, errors: list[str]) -> int:
    filings = list_13f_filings(cik)
    if not filings:
        errors.append(f"{fund_name}: no 13F filings found")
        return 0
    log.info("%s: %d 13F filings on EDGAR (latest period %s)",
             fund_name, len(filings), filings[0]["period"])

    # 1. Record every filing in the manifest (don't clobber already-ingested rows).
    manifest = [{
        "accession": f["accession"], "cik": cik, "fund_name": fund_name,
        "form": f["form"], "report_period": f["period"], "filed_date": f["filed"],
    } for f in filings]
    client.table("institutional_filings").upsert(
        manifest, on_conflict="accession", ignore_duplicates=True
    ).execute()

    # 2. Ingest the `keep` most recent quarters.
    to_ingest = filings[:keep]
    total = 0
    for f in to_ingest:
        try:
            rows = parse_holdings(cik, f["accession"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fund_name} {f['period']}: parse {e}")
            log.warning("%s %s: parse failed: %s", fund_name, f["period"], e)
            continue
        if not rows:
            errors.append(f"{fund_name} {f['period']}: 0 holdings parsed")
            continue
        tot_val = sum(r["value"] for r in rows) or 0
        payload = [{
            "cik": cik, "fund_name": fund_name, "cusip": r["cusip"], "issuer": r["issuer"],
            "value_usd": r["value"], "shares": r["shares"],
            "pct_portfolio": round(r["value"] / tot_val * 100, 4) if tot_val else None,
            "put_call": r["put_call"], "report_period": f["period"],
            "filed_date": f["filed"], "source": "sec_edgar",
        } for r in rows]
        client.table("institutional_holdings").upsert(
            payload, on_conflict="cik,cusip,report_period,put_call"
        ).execute()
        client.table("institutional_filings").update({
            "ingested": True, "holdings_count": len(rows),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }).eq("accession", f["accession"]).execute()
        total += len(rows)
        log.info("%s %s: upserted %d holdings ($%s gross)",
                 fund_name, f["period"], len(rows), f"{tot_val:,}")

    # 3. Retention: keep only the `keep` most recent periods for this fund.
    kept_periods = [f["period"] for f in to_ingest]
    if kept_periods:
        cutoff = min(kept_periods)
        res = client.table("institutional_holdings").delete().eq("cik", cik)\
            .lt("report_period", cutoff).execute()
        if res.data:
            log.info("%s: retention pruned %d holdings older than %s",
                     fund_name, len(res.data), cutoff)
    return total


def main() -> None:
    started = time.time()
    client = get_client()
    keep = int(os.environ.get("INST_KEEP_PERIODS", "2"))
    errors: list[str] = []
    total = 0

    for cik, fund_name in FUNDS:
        try:
            total += ingest_fund(client, cik, fund_name, keep, errors)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fund_name}: {e}")
            log.error("%s ingest failed: %s", fund_name, e)

    # Missing-report check — surface anything EDGAR shows in-window that we lack.
    try:
        gaps = client.table("institutional_coverage_gaps").select("*").execute().data or []
        if gaps:
            log.warning("MISSING REPORTS: %d filing(s) in-window not ingested", len(gaps))
            for g in gaps:
                log.warning("  gap: %s %s %s (ingested=%s)",
                            g.get("fund_name"), g.get("report_period"),
                            g.get("accession"), g.get("ingested"))
        else:
            log.info("coverage: no missing reports in the tracked window")
    except Exception as e:  # noqa: BLE001
        errors.append(f"coverage_check: {e}")
        log.warning("coverage check failed: %s", e)

    # Resolve any new CUSIPs -> tickers (OpenFIGI) and expand `securities` so prices.py
    # backfills them, then rebuild persona_trades. Both guarded — a downstream failure
    # must not fail the 13F ingest itself. (Both are also standalone-runnable modules.)
    try:
        from ingest import cusip_resolve
        n = cusip_resolve.resolve(client)
        log.info("architect_13f: cusip_resolve mapped %d new ticker(s)", n)
    except Exception as e:  # noqa: BLE001
        errors.append(f"cusip_resolve: {e}")
        log.warning("cusip_resolve failed: %s", e)
    try:
        from ingest import map_personas
        map_personas.main()
    except Exception as e:  # noqa: BLE001
        errors.append(f"map_personas: {e}")
        log.warning("map_personas failed: %s", e)

    status = "ok" if (total and not errors) else ("partial" if total else "failed")
    duration_ms = int((time.time() - started) * 1000)
    try:
        client.table("ingest_runs").insert({
            "source": "architect_13f",
            "rows_ingested": total,
            "status": status,
            "error_msg": ("; ".join(errors)[:2000]) or None,
            "duration_ms": duration_ms,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.error("ingest_runs write failed: %s", e)

    log.info("architect_13f %s: %d holdings in %d ms (%d errors)",
             status, total, duration_ms, len(errors))
    for e in errors:
        log.error("error: %s", e)
    # Quarterly feed: re-upserting the same holdings each run is a valid no-op, so
    # a nonzero total is expected. Only hard-fail if we got nothing at all.
    if total == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
