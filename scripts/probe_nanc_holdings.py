"""One-off probe: what NANC holdings can we actually grab, headless?

Answers the open question behind the Oracle/NANC restructure (see
`personas/the_oracle/nanc-restructure.md`): is there a free, headless, full-book
daily-holdings source, or are we capped at Yahoo's top-10 weight-only view?

Run this WHERE EGRESS IS OPEN — a Railway one-off, or the user's local machine.
It will NOT work from the Claude agent session: that session's egress policy
403s every external host at the CONNECT layer (Yahoo, SEC, subversiveetfs all
blocked), and we do not route around an org egress denial.

Writes NOTHING to Supabase. Pure read-only HTTP. **No browser** — that's a hard
project constraint (the pipeline is fully headless); endpoint discovery here is
done by fetching HTML and regexing for data-source URLs, never by driving Chrome.

For each source it prints: HTTP status, content-type, byte size, and a short
sample so we can see the SHAPE — crucially, whether it carries real share counts
(the active-decision signal) or only weight percentages.

Sources probed, in order of what they'd buy us:
  1. Tidal / issuer fund page  — scrape the NANC page HTML for a machine-readable
                                 holdings data-source (wp-json / admin-ajax / .csv
                                 / .json / "holdings" links), then probe each hit.
  2. SEC EDGAR NPORT-P         — authoritative FULL holdings WITH share counts,
                                 but quarterly and ~60-day lagged. The backstop.
  3. Yahoo topHoldings         — the v1 fallback (top-10, weight-only). Includes
                                 the cookie+crumb handshake so we learn if it's needed.

Run:  python -m scripts.probe_nanc_holdings
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# SEC requires a descriptive UA with a contact; mirror how the repo hits EDGAR.
SEC_UA = "robinhood-personas research (contact: jj@dulcenochemedia.com)"

FUND_PAGE = "https://subversiveetfs.com/nanc/"


def _get(url: str, headers: dict | None = None, cookie: str | None = None):
    """GET url. Returns (status, content_type, body_bytes, err_str)."""
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.headers.get("Content-Type", "?"), r.read(), None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "?") if e.headers else "?", e.read() or b"", None
    except Exception as e:  # noqa: BLE001
        return None, "?", b"", repr(e)


def _report(label: str, url: str, status, ctype, body: bytes, err, sample=400):
    size = len(body)
    print(f"\n### {label}\n  url    : {url}")
    if err:
        print(f"  ERROR  : {err}")
        return
    print(f"  status : {status}")
    print(f"  type   : {ctype}")
    print(f"  size   : {size:,} bytes")
    if status == 200 and size:
        text = body[:sample].decode("utf-8", "replace").replace("\n", " ")
        print(f"  sample : {text!r}")
        low = body[:20000].lower()
        # Flag whether the payload smells like it carries share counts (what we want)
        # vs. weight-only. Heuristic, but a useful first read.
        has_shares = any(k in low for k in (b"shares", b"quantity", b"sharesheld", b"share_amount", b"balance"))
        has_weight = any(k in low for k in (b"weight", b"percent", b"allocation"))
        print(f"  signal : shares-like={has_shares}  weight-like={has_weight}")


# ---------------------------------------------------------------------------
# 1. Issuer / Tidal fund page — discover a machine-readable holdings source
# ---------------------------------------------------------------------------
def probe_issuer():
    print("\n" + "=" * 70 + "\n1) ISSUER / TIDAL FUND PAGE\n" + "=" * 70)
    status, ctype, body, err = _get(FUND_PAGE)
    _report("fund page HTML", FUND_PAGE, status, ctype, body, err, sample=200)
    if status != 200 or not body:
        print("  -> could not read the fund page; cannot auto-discover a data source.")
        return
    html = body.decode("utf-8", "replace")

    # Hunt for candidate holdings data-source URLs embedded in the page.
    pats = [
        r'https?://[^\s"\'<>]+?holdings[^\s"\'<>]*\.(?:csv|json|xlsx?)',
        r'https?://[^\s"\'<>]+?\.(?:csv|json)(?:\?[^\s"\'<>]*)?',
        r'/wp-json/[^\s"\'<>]+',
        r'admin-ajax\.php\?[^\s"\'<>]*action=[^\s"\'<>]*',
        r'https?://[^\s"\'<>]*tidal[^\s"\'<>]+',
    ]
    found = []
    for p in pats:
        for m in re.findall(p, html, flags=re.I):
            u = m if m.startswith("http") else ("https://subversiveetfs.com" + m)
            if u not in found:
                found.append(u)
    # Keep it bounded.
    found = [u for u in found if "holding" in u.lower() or u.endswith((".csv", ".json"))
             or "wp-json" in u or "admin-ajax" in u][:15]

    if not found:
        print("\n  No embedded holdings data-source URL found in the HTML.")
        print("  (The table may be injected by JS from an undocumented endpoint — inspect")
        print("   the page's network calls in a browser MANUALLY to find it; the pipeline")
        print("   itself must stay headless once the URL is known.)")
        return
    print(f"\n  Discovered {len(found)} candidate data-source URL(s); probing each:")
    for u in found:
        s, c, b, e = _get(u, headers={"Referer": FUND_PAGE, "Accept": "application/json, text/csv, */*"})
        _report(f"candidate: {u.split('/')[-1][:40]}", u, s, c, b, e, sample=300)


# ---------------------------------------------------------------------------
# 2. SEC EDGAR NPORT-P — authoritative full holdings with share counts
# ---------------------------------------------------------------------------
def probe_edgar():
    print("\n" + "=" * 70 + "\n2) SEC EDGAR NPORT-P (full book, quarterly, lagged)\n" + "=" * 70)
    # Resolve the fund/trust CIK from the ticker map, then find the latest NPORT-P.
    s, c, b, e = _get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": SEC_UA})
    if s != 200 or not b:
        _report("company_tickers.json", "https://www.sec.gov/files/company_tickers.json", s, c, b, e)
        print("  -> could not resolve CIK; skipping EDGAR.")
        return
    try:
        tickers = json.loads(b)
        cik = next((f'{row["cik_str"]:010d}' for row in tickers.values()
                    if row.get("ticker", "").upper() == "NANC"), None)
    except Exception as ex:  # noqa: BLE001
        print(f"  parse error: {ex!r}")
        cik = None
    print(f"  NANC CIK: {cik}")
    if not cik:
        print("  -> NANC not in the ticker map (ETFs sometimes file under the Trust's CIK).")
        print("     Fall back to EDGAR full-text search: https://efts.sec.gov/LATEST/search-index?q=NANC&forms=NPORT-P")
        return
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    s, c, b, e = _get(sub_url, headers={"User-Agent": SEC_UA})
    _report("submissions", sub_url, s, c, b, e, sample=120)
    if s == 200 and b:
        try:
            recent = json.loads(b)["filings"]["recent"]
            forms = recent["form"]
            idx = next((i for i, f in enumerate(forms) if f.startswith("NPORT-P")), None)
            if idx is None:
                print("  -> no NPORT-P in recent filings for this CIK.")
            else:
                acc = recent["accessionNumber"][idx].replace("-", "")
                doc_dir = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/"
                print(f"  latest NPORT-P: {recent['accessionNumber'][idx]} "
                      f"filed {recent['filingDate'][idx]} (period {recent['reportDate'][idx]})")
                print(f"  holdings XML dir: {doc_dir}")
                # The holdings live in the primary XML (primary_doc.xml / <acc>.xml).
                for name in ("primary_doc.xml", f"{recent['accessionNumber'][idx]}.txt"):
                    u = doc_dir + name
                    s2, c2, b2, e2 = _get(u, headers={"User-Agent": SEC_UA})
                    _report(f"NPORT doc: {name}", u, s2, c2, b2, e2, sample=300)
        except Exception as ex:  # noqa: BLE001
            print(f"  parse error walking submissions: {ex!r}")


# ---------------------------------------------------------------------------
# 3. Yahoo topHoldings — the v1 fallback (top-10, weight-only)
# ---------------------------------------------------------------------------
def probe_yahoo():
    print("\n" + "=" * 70 + "\n3) YAHOO topHoldings (v1 fallback: top-10, weight-only)\n" + "=" * 70)
    # Cookie + crumb handshake (quoteSummary needs it; the v8 chart endpoint does not).
    cookie = None
    try:
        req = urllib.request.Request("https://fc.yahoo.com", headers={"User-Agent": UA})
        try:
            urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            sc = e.headers.get("Set-Cookie") if e.headers else None
            cookie = sc.split(";")[0] if sc else None
    except Exception as ex:  # noqa: BLE001
        print(f"  cookie fetch note: {ex!r}")
    crumb = None
    s, c, b, e = _get("https://query1.finance.yahoo.com/v1/test/getcrumb",
                      headers={"Accept": "text/plain"}, cookie=cookie)
    if s == 200 and b:
        crumb = b.decode("utf-8", "replace").strip()
    print(f"  cookie: {'yes' if cookie else 'no'}   crumb: {crumb!r} (status {s})")
    base = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/NANC?modules=topHoldings"
    url = base + (f"&crumb={urllib.parse.quote(crumb)}" if crumb else "")
    s, c, b, e = _get(url, cookie=cookie)
    _report("quoteSummary topHoldings", url, s, c, b, e, sample=500)
    if s == 401 or (b and b"crumb" in b.lower() and b"invalid" in b.lower()):
        print("  -> crumb rejected. Use the `yfinance` library, which manages this handshake:")
        print("       yfinance.Ticker('NANC').funds_data.top_holdings")


def main():
    print("NANC holdings probe — read-only, headless, no browser.")
    print("If every source shows a CONNECT/403 error, you're running inside a blocked")
    print("egress (e.g. the agent session). Re-run on Railway or locally.\n")
    probe_issuer()
    probe_edgar()
    probe_yahoo()
    print("\n" + "=" * 70)
    print("Read the 'signal:' lines: a source with shares-like=True is the prize")
    print("(real share counts -> no weight reconstruction needed). weight-only sources")
    print("are usable only via the shares-per-unit reconstruction in the proposal doc.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
