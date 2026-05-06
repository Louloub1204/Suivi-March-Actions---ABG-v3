"""BRVM web-scraper.

Pulls today's quotes from public BRVM data sites. Tries multiple sources in
order, since the official brvm.org page sometimes renders quotes via JS
which `requests` cannot execute.

Sources, in priority order:
  1. sikafinance.com/marches/aaz — primary, well-structured HTML table.
  2. brvm.org/fr/cours-actions/0  — fallback (regex over rendered text).

Each source produces a DataFrame with the standard columns:
  ticker, name, volume, prev_close, open, close, variation_pct
"""
from __future__ import annotations

import re
import warnings
from datetime import date

import certifi
import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup

SIKA_URL = "https://www.sikafinance.com/marches/aaz"
BRVM_URL = "https://www.brvm.org/fr/cours-actions/0"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Robust HTTPS GET that survives misconfigured CA bundles (Streamlit Cloud)
# ---------------------------------------------------------------------------

def _safe_get(url: str, timeout: int = 25) -> requests.Response:
    """GET with three escalating SSL strategies (certifi → system → no-verify)."""
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout, verify=certifi.where())
    except requests.exceptions.SSLError:
        pass
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.exceptions.SSLError:
        pass
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, headers=HEADERS, timeout=timeout, verify=False)


def _to_float(s) -> float | None:
    if s is None:
        return None
    s = (
        str(s)
        .strip()
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("+", "")
    )
    s = s.replace(",", ".")
    if s in ("", "-", "ND", "n/a", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Source 1 — sikafinance.com (primary)
# ---------------------------------------------------------------------------

# The ticker is embedded in the cotation URL, e.g. /marches/cotation_BOAC.ci
_TICKER_FROM_URL = re.compile(r"cotation_([A-Z0-9]{2,8})", re.IGNORECASE)


def _parse_sikafinance(html: str) -> pd.DataFrame:
    """Extract the BRVM stock quotes table from sikafinance's "A à Z" page.

    The page contains two tables:
      - 'Les indices' (BRVM-CI, BRVM30, etc.)  — we ignore this
      - 'Les actions cotées' with columns:
          Nom | Ouverture | +Haut | +Bas | Volume (titres) | Volume (XOF)
          | Dernier | Variation
    Each row's first cell is a link whose URL embeds the ticker. We use
    that as the source of truth for the ticker symbol.
    """
    soup = BeautifulSoup(html, "html.parser")

    candidate_tables = soup.find_all("table")
    best_rows: list[dict] | None = None
    best_score = 0

    for tbl in candidate_tables:
        rows: list[dict] = []
        for tr in tbl.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 6:
                continue
            link = cells[0].find("a")
            if link is None:
                continue
            href = link.get("href", "")
            m = _TICKER_FROM_URL.search(href)
            if not m:
                continue
            ticker = m.group(1).upper()
            name = link.get_text(strip=True)
            other = [c.get_text(strip=True) for c in cells[1:]]
            rows.append({"ticker": ticker, "name": name, "other": other})

        # Score: count rows whose ticker looks like a BRVM stock (3-6 letters,
        # not a SIKA index code like "BRVMC", "SIKATR", etc.).
        index_codes = {
            "BRVMC", "BRVM30", "BRVMAG", "BRVMAS", "BRVM-CB", "BRVM-CD",
            "BRVMDI", "BRVM-EN", "BRVMFI", "BRVMIN", "BRVM-IN", "BRVMPR",
            "BRVMPA", "BRVM-SF", "BRVMSP", "BRVM-SP", "BRVM-TEL", "BRVMTR",
            "CAPIBRVM", "SIKAIDX", "SIKATR",
        }
        score = sum(1 for r in rows if r["ticker"] not in index_codes)
        if score > best_score:
            best_score = score
            best_rows = [r for r in rows if r["ticker"] not in index_codes]

    if not best_rows or best_score < 5:
        raise RuntimeError("sikafinance: no stock quotes table detected.")

    # The "actions cotées" table has 7 cells after the name:
    #   0: Ouverture | 1: +Haut | 2: +Bas | 3: Vol(titres) | 4: Vol(XOF)
    #   5: Dernier   | 6: Variation
    out_rows = []
    for r in best_rows:
        o = r["other"]
        # Need at least 7 trailing cells; pad with None if fewer.
        while len(o) < 7:
            o.append(None)
        out_rows.append({
            "ticker": r["ticker"],
            "name": r["name"],
            "open": _to_float(o[0]),
            "high": _to_float(o[1]),
            "low": _to_float(o[2]),
            "volume": _to_float(o[3]),
            "volume_xof": _to_float(o[4]),
            "close": _to_float(o[5]),
            "variation_pct": _to_float(o[6]),
        })

    df = pd.DataFrame(out_rows)
    df = df.dropna(subset=["close"]).reset_index(drop=True)

    # Sikafinance does not expose the previous close on this page.
    df["prev_close"] = pd.NA
    return df[
        ["ticker", "name", "volume", "prev_close", "open", "close", "variation_pct"]
    ]


def _parse_sikafinance_session_date(html: str) -> date | None:
    """Look for a French date pattern in the page header.

    Sikafinance prints dates in formats like 'JJ/MM/AAAA' or
    'Lundi 28 avril 2026' near the top.
    """
    # Try numeric format first.
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", html)
    if m:
        d, mo, y = m.groups()
        try:
            return date(int(y), int(mo), int(d))
        except ValueError:
            pass
    return None


def fetch_from_sikafinance(timeout: int = 25) -> tuple[pd.DataFrame, date]:
    resp = _safe_get(SIKA_URL, timeout)
    resp.raise_for_status()
    df = _parse_sikafinance(resp.text)
    if df.empty:
        raise RuntimeError("sikafinance: parsed table is empty.")
    sess = _parse_sikafinance_session_date(resp.text) or date.today()
    df["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
    return df, sess


# ---------------------------------------------------------------------------
# Source 2 — brvm.org (fallback)
# ---------------------------------------------------------------------------

def _parse_brvm_org(html: str) -> pd.DataFrame:
    """Parse the brvm.org page.

    Tries a real HTML table first; if absent, falls back to a regex over
    the rendered text since the live page sometimes renders inline
    'TICKER price var%' triplets like 'ABJC 2 850 -2,38% BICB 5 215 0,29%'.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tbl in soup.find_all("table"):
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) >= 5:
                rows.append(cells)
        if len(rows) >= 10:
            df = pd.DataFrame(rows)
            return pd.DataFrame({
                "ticker": df.iloc[:, 0].astype(str).str.strip(),
                "name": df.iloc[:, 1].astype(str).str.strip() if df.shape[1] > 1 else "",
                "volume": df.iloc[:, 2].apply(_to_float) if df.shape[1] > 2 else pd.NA,
                "prev_close": df.iloc[:, 3].apply(_to_float) if df.shape[1] > 3 else pd.NA,
                "open": df.iloc[:, 4].apply(_to_float) if df.shape[1] > 4 else pd.NA,
                "close": df.iloc[:, 5].apply(_to_float) if df.shape[1] > 5 else pd.NA,
                "variation_pct": df.iloc[:, 6].apply(_to_float) if df.shape[1] > 6 else pd.NA,
            }).dropna(subset=["ticker"]).reset_index(drop=True)

    text = soup.get_text(" ", strip=True)
    pattern = re.compile(r"\b([A-Z]{3,6})\s+([\d\s\u00a0]+)\s+(-?[\d,\.]+)\s*%")
    rows = []
    for m in pattern.finditer(text):
        tk = m.group(1)
        price = _to_float(m.group(2))
        change = _to_float(m.group(3))
        if price is None:
            continue
        rows.append({"ticker": tk, "close": price, "variation_pct": change})

    if not rows:
        raise RuntimeError("brvm.org: no quotes detected (page may use JS rendering).")
    df = pd.DataFrame(rows).drop_duplicates(subset=["ticker"], keep="first")
    df["name"] = ""
    df["volume"] = pd.NA
    df["prev_close"] = pd.NA
    df["open"] = pd.NA
    return df[["ticker", "name", "volume", "prev_close", "open", "close", "variation_pct"]]


def _parse_brvm_session_date(html: str) -> date | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", html)
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d))
    except ValueError:
        return None


def fetch_from_brvm_org(timeout: int = 25) -> tuple[pd.DataFrame, date]:
    resp = _safe_get(BRVM_URL, timeout)
    resp.raise_for_status()
    df = _parse_brvm_org(resp.text)
    if df.empty:
        raise RuntimeError("brvm.org: parsed table is empty.")
    sess = _parse_brvm_session_date(resp.text) or date.today()
    df["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
    return df, sess


# ---------------------------------------------------------------------------
# Public API used by app.py
# ---------------------------------------------------------------------------

def fetch_with_session_date(timeout: int = 25) -> tuple[pd.DataFrame, date]:
    """Try sources in priority order; return whichever succeeds first."""
    errors: list[str] = []
    for label, fn in (("sikafinance", fetch_from_sikafinance),
                      ("brvm.org",    fetch_from_brvm_org)):
        try:
            df, sess = fn(timeout=timeout)
            df["source_url"] = label
            return df, sess
        except Exception as e:
            errors.append(f"{label}: {e}")
            continue

    raise RuntimeError(
        "Aucune source BRVM n'a répondu correctement. Détails :\n  - "
        + "\n  - ".join(errors)
    )


# Backwards compatibility.
def fetch_brvm_quotes(timeout: int = 25) -> pd.DataFrame:
    df, _sess = fetch_with_session_date(timeout=timeout)
    return df
