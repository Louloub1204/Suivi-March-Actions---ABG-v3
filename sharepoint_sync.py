"""SharePoint share-link downloader.

The CGF GESTION workbook is shared via a SharePoint anonymous link. This
module converts that link into a direct-download URL using SharePoint's
"shares" REST endpoint, which works without OAuth as long as the share
remains anonymous.

If the anonymous share is ever disabled, the app falls back to manual
file upload (handled in app.py).
"""
from __future__ import annotations

import base64
import io
import warnings
from urllib.parse import urlparse

import certifi
import openpyxl
import pandas as pd
import requests
import urllib3

DEFAULT_URL = (
    "https://boursecgf.sharepoint.com/:x:/s/CGF_GESTION/"
    "IQAdBwhE7rJUS5Ol4W62HaP1AUIPVtwJ61x7gW7yPPgpKak"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _safe_get(url: str, timeout: int, allow_redirects: bool = True) -> requests.Response:
    """GET with three escalating SSL strategies (certifi → system → no-verify)."""
    try:
        return requests.get(
            url, headers=HEADERS, timeout=timeout,
            allow_redirects=allow_redirects, verify=certifi.where(),
        )
    except requests.exceptions.SSLError:
        pass
    try:
        return requests.get(
            url, headers=HEADERS, timeout=timeout,
            allow_redirects=allow_redirects,
        )
    except requests.exceptions.SSLError:
        pass
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        return requests.get(
            url, headers=HEADERS, timeout=timeout,
            allow_redirects=allow_redirects, verify=False,
        )


def _encode_share_url(url: str) -> str:
    """SharePoint's well-known transform from a share link to a `u!` token.

    Reference: https://learn.microsoft.com/en-us/onedrive/developer/rest-api/api/shares_get
    """
    b64 = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + b64


def download_workbook(share_url: str = DEFAULT_URL, timeout: int = 60) -> bytes:
    """Return the raw bytes of the .xlsm file behind the SharePoint link.

    Strategy:
      1. Try the public Graph-style endpoint via the share token (works for
         most anonymous "anyone with the link" shares).
      2. Fall back to the legacy `?download=1` query string trick.
    """
    parsed = urlparse(share_url)
    host = parsed.netloc

    token = _encode_share_url(share_url)
    api_url = f"https://{host}/_api/v2.0/shares/{token}/driveItem/content"

    try:
        resp = _safe_get(api_url, timeout)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except requests.RequestException:
        pass

    dl_url = share_url + ("&" if "?" in share_url else "?") + "download=1"
    resp = _safe_get(dl_url, timeout)
    resp.raise_for_status()
    if len(resp.content) < 1000:
        raise RuntimeError(
            "SharePoint a renvoyé une réponse trop courte. "
            "Vérifiez que le lien de partage anonyme est toujours actif."
        )
    return resp.content


def read_transactions_from_bytes(xlsm_bytes: bytes) -> pd.DataFrame:
    """Read the 'Transactions' sheet, columns A:K only.

    Mirrors what the user does manually: copy A:K from the source workbook.
    Returns a DataFrame with the canonical columns the app stores.
    """
    wb = openpyxl.load_workbook(
        filename=io.BytesIO(xlsm_bytes),
        data_only=True,
        read_only=True,
        keep_vba=False,
    )
    if "Transactions" not in wb.sheetnames:
        raise RuntimeError(
            f"La feuille 'Transactions' est absente. Feuilles trouvées : {wb.sheetnames}"
        )
    ws = wb["Transactions"]

    # Header is on row 2 (row 1 is 'RECAP VARIATION' label in the source file).
    rows = []
    for row in ws.iter_rows(min_row=3, max_col=11, values_only=True):
        if not row or row[1] is None or row[2] is None or row[3] not in ("ACHAT", "VENTE"):
            continue
        d = row[0]
        if d is None:
            continue
        rows.append({
            "date": pd.Timestamp(d).strftime("%Y-%m-%d"),
            "fcp": row[1],
            "ticker": row[2],
            "sens": row[3],
            "quantite": row[4] or 0,
            "cmp_at_tx": row[5] if isinstance(row[5], (int, float)) else 0,
            "col_g": row[6] if isinstance(row[6], (int, float)) else 0,
            "prix": row[7] or 0,
            "valeur": row[8] or 0,
            "frais": row[9] or 0,
            "col_k": row[10] if isinstance(row[10], (int, float)) else 0,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["cost_in"] = df.apply(lambda r: r["col_k"] if r["sens"] == "ACHAT" else 0, axis=1)
    df["cost_out"] = df.apply(lambda r: r["col_g"] if r["sens"] == "VENTE" else 0, axis=1)
    return df[
        ["date", "fcp", "ticker", "sens", "quantite", "prix", "valeur", "frais",
         "cost_in", "cost_out", "cmp_at_tx"]
    ]


def read_last_cours_row(xlsm_bytes: bytes) -> tuple[pd.Timestamp, pd.DataFrame]:
    """Read the LAST data row of the 'Cours' sheet.

    Returns (session_date, DataFrame with columns ['ticker','price']).
    The Cours sheet is wide: col A = volume index, col B = date, cols C+ = tickers.
    """
    wb = openpyxl.load_workbook(
        filename=io.BytesIO(xlsm_bytes),
        data_only=True,
        read_only=True,
        keep_vba=False,
    )
    if "Cours" not in wb.sheetnames:
        raise RuntimeError(
            f"La feuille 'Cours' est absente. Feuilles trouvées : {wb.sheetnames}"
        )
    ws = wb["Cours"]

    headers: list = []
    last_row_with_date: tuple[pd.Timestamp, list] | None = None

    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i == 1:
            headers = list(row)
            continue
        if len(row) < 2 or row[1] is None:
            continue
        try:
            d = pd.Timestamp(row[1])
        except (ValueError, TypeError):
            continue
        last_row_with_date = (d, list(row))

    if last_row_with_date is None:
        raise RuntimeError("Aucune ligne de cours datée trouvée dans la feuille 'Cours'.")

    sess_date, values = last_row_with_date
    out = []
    for h, v in zip(headers[2:], values[2:]):
        if not isinstance(h, str) or not h.strip():
            continue
        if v is None:
            continue
        try:
            out.append({"ticker": h.strip(), "price": float(v)})
        except (ValueError, TypeError):
            continue
    return sess_date, pd.DataFrame(out)


def read_full_cours_history(xlsm_bytes: bytes) -> pd.DataFrame:
    """Read the entire 'Cours' sheet, columns A to BJ, in long format.

    Mirrors what the user does manually: copy A:BJ from the source workbook.
    The sheet has:
      - col A : volume index (ignored)
      - col B : date
      - col C..BJ : tickers (one per column), header row = ticker symbol
    Each cell holds the closing price for that (date, ticker).

    Returns a DataFrame with columns: date, ticker, price.
    Rows with empty dates or empty prices are dropped.
    """
    wb = openpyxl.load_workbook(
        filename=io.BytesIO(xlsm_bytes),
        data_only=True,
        read_only=True,
        keep_vba=False,
    )
    if "Cours" not in wb.sheetnames:
        raise RuntimeError(
            f"La feuille 'Cours' est absente. Feuilles trouvées : {wb.sheetnames}"
        )
    ws = wb["Cours"]

    # Column BJ corresponds to the 62nd column (A=1, B=2, ..., BJ=62).
    # We read up to that column and let pandas drop empty trailing columns.
    MAX_COL = 62

    headers: list = []
    rows: list[dict] = []

    for i, row in enumerate(ws.iter_rows(min_col=1, max_col=MAX_COL, values_only=True), start=1):
        if i == 1:
            headers = list(row)
            continue
        if len(row) < 2 or row[1] is None:
            continue
        try:
            d = pd.Timestamp(row[1])
        except (ValueError, TypeError):
            continue
        date_str = d.strftime("%Y-%m-%d")
        for h, v in zip(headers[2:], row[2:]):
            if not isinstance(h, str) or not h.strip():
                continue
            if v is None:
                continue
            try:
                price = float(v)
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": date_str,
                "ticker": h.strip(),
                "price": price,
            })

    if not rows:
        raise RuntimeError("La feuille 'Cours' n'a renvoyé aucun cours exploitable.")

    df = pd.DataFrame(rows)
    # Last-write-wins for any (date, ticker) duplicate (rare but possible in the source).
    df = df.drop_duplicates(subset=["date", "ticker"], keep="last").reset_index(drop=True)
    return df
