"""Portfolio computation engine.

Replicates the Excel formulas from FCP PLACEMENT CROISSANCE:
- C: QUANTITES = sum(ACHAT.qte) - sum(VENTE.qte) up to date D
- E: COUT TOTAL = sum(ACHAT.valeur) - sum(VENTE.prix*qte) up to date D
- D: CMP = E/C
- I: prev close, J: close on D, K: variation, L: K*C (+/- value)
- F: valorisation = C * J
- G: diff estim = F - E
- H: poids = F / total F
"""
from __future__ import annotations

import functools as _functools
import threading as _threading

import numpy as np
import pandas as pd

from fcp_calendar import previous_cours_date as _pcd_raw

@_functools.lru_cache(maxsize=512)
def previous_cours_date(fcp: str, d) -> "pd.Timestamp":
    """Memoized wrapper — same date+fcp always returns same result."""
    return _pcd_raw(fcp, d)


# ---------------------------------------------------------------------------
# Fast lookup indexes (performance layer)
# ---------------------------------------------------------------------------
# The computation functions below call get_price_on / _qty_before /
# _period_trades thousands of times per page. Scanning the full price table
# (~150 000 rows) and re-parsing every date on each call made pages slow.
#
# Instead, each input DataFrame is indexed ONCE and the index is reused for
# as long as the same DataFrame object is passed in. The cache holds a strong
# reference to the indexed object, so an `is` check is a safe identity test
# (the object cannot be garbage-collected and its id reused while cached).
# New data (after a refresh) arrives as a new object and gets a new index.
# Only the lookup strategy changes - results are identical.

_INDEX_LOCK = _threading.Lock()
_PRICE_INDEX: list[tuple[pd.DataFrame, dict]] = []
_TX_INDEX: list[tuple[pd.DataFrame, dict]] = []
_INDEX_SLOTS = 3


def _ns(d) -> np.datetime64:
    """Any date-like → numpy datetime64[ns] (naive)."""
    return pd.Timestamp(d).as_unit("ns").to_datetime64()


def _lookup(cache: list, obj: pd.DataFrame):
    with _INDEX_LOCK:
        for o, idx in cache:
            if o is obj:
                return idx
    return None


def _store(cache: list, obj: pd.DataFrame, idx: dict) -> dict:
    with _INDEX_LOCK:
        cache.insert(0, (obj, idx))
        del cache[_INDEX_SLOTS:]
    return idx


def _price_index(cours: pd.DataFrame) -> dict:
    """{ticker: (dates[ns] sorted, prices)} built once per prices DataFrame."""
    idx = _lookup(_PRICE_INDEX, cours)
    if idx is not None:
        return idx
    tmp = pd.DataFrame({
        "t": cours["ticker"].to_numpy(),
        "d": pd.to_datetime(cours["date"]).to_numpy(dtype="datetime64[ns]"),
        "p": pd.to_numeric(cours["price"], errors="coerce").to_numpy(dtype=float),
    }).sort_values(["t", "d"], kind="mergesort")
    idx = {
        t: (g["d"].to_numpy(), g["p"].to_numpy())
        for t, g in tmp.groupby("t", sort=False)
    }
    return _store(_PRICE_INDEX, cours, idx)


def _tx_index(transactions: pd.DataFrame) -> dict:
    """Prepared transactions, built once per transactions DataFrame.

    Returns a dict with:
      df      : copy of `transactions` with `date` as datetime64[ns] and a
                `_signed` column (+qty for ACHAT, −qty otherwise).
                SHARED - callers must never modify it in place.
      dates   : `date` column as a numpy datetime64[ns] array
      signed  : `_signed` column as a numpy array
      by_fcp  : {fcp: row positions}
      by_pair : {(fcp, ticker): row positions}   (original row order)
    """
    idx = _lookup(_TX_INDEX, transactions)
    if idx is not None:
        return idx
    df = transactions.copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df["_signed"] = np.where(df["sens"] == "ACHAT", df["quantite"], -df["quantite"])
    idx = {
        "df": df,
        "dates": df["date"].to_numpy(),
        "signed": df["_signed"].to_numpy(),
        "by_fcp": df.groupby("fcp", sort=False).indices,
        "by_pair": df.groupby(["fcp", "ticker"], sort=False).indices,
    }
    return _store(_TX_INDEX, transactions, idx)


def _tx_dated(transactions: pd.DataFrame) -> pd.DataFrame:
    """Transactions with `date` already parsed to datetime (read-only, shared).

    Drop-in replacement for the former per-call
    `df = transactions.copy(); df["date"] = pd.to_datetime(df["date"])`.
    """
    return _tx_index(transactions)["df"]

def get_dividends_on_date(
    dividends_dated: list[dict],
    ticker: str,
    on_date: pd.Timestamp,
) -> float:
    """Return the dividend amount for `ticker` if `on_date` is its payment date.

    `dividends_dated` is a list of dicts with keys:
        ticker, amount, payment_date (date or Timestamp or str)

    Returns 0.0 if no dividend applies on this exact date.
    This ensures dividends are only added to the closing price on the
    payment date itself, not on subsequent days.
    """
    target = pd.Timestamp(on_date).normalize()
    for d in dividends_dated:
        if str(d.get("ticker", "")).strip().upper() != ticker.strip().upper():
            continue
        try:
            pd_date = pd.Timestamp(d["payment_date"]).normalize()
        except (KeyError, ValueError, TypeError):
            continue
        if pd_date == target:
            try:
                return float(d["amount"])
            except (ValueError, TypeError):
                pass
    return 0.0


def resolve_dividends_for_date(
    dividends_dated: list[dict],
    as_of_date: pd.Timestamp,
) -> dict[str, float]:
    """Return {ticker: amount} for all dividends whose payment_date == as_of_date.

    Used to build the legacy `dividends: dict[str, float]` argument for
    build_dashboard and related functions, scoped to a single date.
    """
    result: dict[str, float] = {}
    target = pd.Timestamp(as_of_date).normalize()
    for d in dividends_dated:
        try:
            pd_date = pd.Timestamp(d["payment_date"]).normalize()
        except (KeyError, ValueError, TypeError):
            continue
        if pd_date == target:
            ticker = str(d.get("ticker", "")).strip().upper()
            try:
                amount = float(d["amount"])
                if ticker:
                    result[ticker] = result.get(ticker, 0.0) + amount
            except (ValueError, TypeError):
                pass
    return result




class PortfolioRow:
    """Holds computed metrics for one ticker in one FCP dashboard."""

    __slots__ = (
        "ticker", "quantite", "cmp", "cout_total", "valorisation",
        "diff_estim", "poids", "prev_close", "close", "variation",
        "plus_moins_value", "dividende",
    )

    def __init__(
        self,
        ticker: str,
        quantite: float,
        cmp: float,
        cout_total: float,
        valorisation: float,
        diff_estim: float,
        poids: float,
        prev_close: float,
        close: float,
        variation: float,
        plus_moins_value: float,
        dividende: float = 0.0,
    ) -> None:
        self.ticker = ticker
        self.quantite = quantite
        self.cmp = cmp
        self.cout_total = cout_total
        self.valorisation = valorisation
        self.diff_estim = diff_estim
        self.poids = poids
        self.prev_close = prev_close
        self.close = close
        self.variation = variation
        self.plus_moins_value = plus_moins_value
        self.dividende = dividende

    def __iter__(self):
        """Allow dict(row) and DataFrame construction via row.__dict__."""
        for s in self.__slots__:
            yield s, getattr(self, s)

    @property
    def __dict__(self):  # type: ignore[override]
        return dict(self)


def compute_positions(
    transactions: pd.DataFrame,
    fcp: str,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    """Net quantity and remaining cost basis per ticker for a given FCP up to a date.

    The cost basis follows the convention used in the source Excel:
      - ACHAT adds `cost_in` (= qty*prix + frais) to the cost basis
      - VENTE removes `cost_out` (= qty * CMP_at_sale) from the cost basis

    This means the running cost is `Σ cost_in − Σ cost_out` and CMP is
    `cost / quantite`, which stays stable across pure VENTEs of held shares.
    """
    empty = pd.DataFrame(columns=["ticker", "quantite", "cout_total", "cmp"])
    if transactions.empty:
        return empty

    ix = _tx_index(transactions)
    rows = ix["by_fcp"].get(fcp)
    if rows is None:
        return empty
    rows = rows[ix["dates"][rows] <= _ns(as_of_date)]
    if len(rows) == 0:
        return empty

    df = ix["df"].iloc[rows]
    grouped = df.groupby("ticker").agg(
        quantite=("_signed", "sum"),
        cost_in=("cost_in", "sum"),
        cost_out=("cost_out", "sum"),
    )
    grouped["cout_total"] = grouped["cost_in"] - grouped["cost_out"]
    qty = grouped["quantite"]
    grouped["cmp"] = np.where(
        qty != 0, grouped["cout_total"] / qty.where(qty != 0, 1), 0.0
    )
    return grouped[["quantite", "cout_total", "cmp"]].reset_index()


def get_price_on(cours: pd.DataFrame, ticker: str, target_date: pd.Timestamp) -> float | None:
    """Last known price for `ticker` on or before `target_date`. None if absent."""
    if cours.empty:
        return None
    series = _price_index(cours).get(ticker)
    if series is None:
        return None
    dates, prices = series
    pos = int(np.searchsorted(dates, _ns(target_date), side="right")) - 1
    if pos < 0:
        return None
    return float(prices[pos])


def previous_business_date(d: pd.Timestamp) -> pd.Timestamp:
    """Generic previous business day. For FCP-specific logic use previous_cours_date."""
    d = pd.Timestamp(d)
    return d - pd.Timedelta(days=3 if d.weekday() == 0 else 1)


def _qty_before(transactions: pd.DataFrame, fcp: str, ticker: str,
                cutoff: pd.Timestamp) -> float:
    """Net quantity held on `cutoff` (inclusive).

    A trade made on `cutoff` is considered 'held' for the day-P&L purpose:
    its entry price is essentially `prev_close` of the next valuation, so
    the held bucket formula `qty * (close − prev_close)` applies cleanly.
    """
    if transactions.empty:
        return 0.0
    ix = _tx_index(transactions)
    rows = ix["by_pair"].get((fcp, ticker))
    if rows is None:
        return 0.0
    rows = rows[ix["dates"][rows] <= _ns(cutoff)]
    if len(rows) == 0:
        return 0.0
    return float(ix["signed"][rows].sum())


def quantity_held(transactions: pd.DataFrame, fcp: str, ticker: str,
                  on_date: pd.Timestamp) -> float:
    """Net quantity of `ticker` held by `fcp` on `on_date` (inclusive).

    Same value as compute_positions(...)['quantite'] for that ticker (0.0 if
    never held), but reads a single line instead of rebuilding the portfolio.
    """
    return _qty_before(transactions, fcp, str(ticker).strip(), on_date)


def _period_trades(transactions: pd.DataFrame, fcp: str, ticker: str,
                   prev_date: pd.Timestamp,
                   as_of_date: pd.Timestamp) -> pd.DataFrame:
    """Trades on this ticker in the window `(prev_date, as_of_date]`.

    Lower bound exclusive (a trade on prev_date is in the held bucket);
    upper bound inclusive.
    """
    cols = ["sens", "quantite", "prix", "frais"]
    if transactions.empty:
        return transactions.iloc[0:0]
    ix = _tx_index(transactions)
    rows = ix["by_pair"].get((fcp, ticker))
    if rows is None:
        return ix["df"].iloc[0:0][cols].copy()
    d = ix["dates"][rows]
    rows = rows[(d > _ns(prev_date)) & (d <= _ns(as_of_date))]
    return ix["df"].iloc[rows][cols].copy()


# Toggles: how to treat fees on ACHAT trades within the day P&L.
# True  -> entry cost basis includes fees, so fees reduce the day P&L.
# False -> fees are ignored in the day P&L (treated as separate accounting).
INCLUDE_FEES_IN_DAY_PNL = True


def build_dashboard(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcp: str,
    as_of_date: pd.Timestamp,
    dividends: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Return (rows DataFrame, totals dict) for one FCP on `as_of_date`.

    The daily P&L is computed in two buckets:
      • Held bucket — quantity held on `prev_date` (inclusive):
            P&L_held = qty_held × (close − prev_close)
      • Period-trades bucket — every trade in (prev_date, as_of_date]:
            ACHAT  → qty × (close − prix_achat) − frais
            VENTE  → qty × (prix_vente − close) − frais

    Total daily P&L = sum of both. This formula is correct whether the
    period spans one day (most FCPs) or seven days (weekly-valuation FCPs).
    """
    dividends = dividends or {}
    positions = compute_positions(transactions, fcp, as_of_date)
    prev_date = previous_cours_date(fcp, as_of_date)

    if positions.empty:
        return pd.DataFrame(), {
            "cout_total": 0,
            "valorisation": 0,
            "diff_estim": 0,
            "variation_jour": 0,
            "valorisation_prev": 0,
            "variation_pct": 0,
            "as_of": pd.Timestamp(as_of_date),
            "prev_date": prev_date,
        }

    # Lookups go through the shared index (see _tx_index): no per-call copy.
    tx_fcp = transactions

    rows: list[PortfolioRow] = []

    for _, p in positions.iterrows():
        ticker = p["ticker"]
        qte_now = float(p["quantite"])
        cout = float(p["cout_total"])
        cmp_ = float(p["cmp"])

        prev = get_price_on(cours, ticker, prev_date) or 0.0
        close = get_price_on(cours, ticker, as_of_date) or 0.0
        div = dividends.get(ticker, 0.0)
        close_eff = close + div  # dividend treated as cash returned to holder

        valorisation = qte_now * close_eff
        diff_estim = valorisation - cout

        # Bucket 1 — quantity held BEFORE prev_date, valued at (close − prev).
        qte_held = _qty_before(tx_fcp, fcp, ticker, prev_date)
        pnl_held = qte_held * (close_eff - prev)

        # Bucket 2 — trades within (prev_date, as_of_date].
        period = _period_trades(tx_fcp, fcp, ticker, prev_date, as_of_date)
        pnl_period = 0.0
        for _, t in period.iterrows():
            qty = float(t["quantite"])
            prix = float(t["prix"])
            frais = float(t["frais"]) if INCLUDE_FEES_IN_DAY_PNL else 0.0
            if t["sens"] == "ACHAT":
                pnl_period += qty * (close_eff - prix) - frais
            else:  # VENTE
                pnl_period += qty * (prix - close_eff) - frais

        plus_moins = pnl_held + pnl_period

        # Display variation (per unit) is kept as `close − prev` for the
        # held bucket; it's the most informative number when both buckets
        # exist. The total P&L stays accurate either way.
        variation_unit = close_eff - prev

        rows.append(
            PortfolioRow(
                ticker=ticker,
                quantite=qte_now,
                cmp=cmp_,
                cout_total=cout,
                valorisation=valorisation,
                diff_estim=diff_estim,
                poids=0.0,
                prev_close=prev,
                close=close_eff,
                variation=variation_unit,
                plus_moins_value=plus_moins,
                dividende=div,
            )
        )

    df = pd.DataFrame([r.__dict__ for r in rows])
    total_valo = df["valorisation"].sum()
    df["poids"] = df["valorisation"] / total_valo if total_valo else 0.0
    df = df.sort_values("valorisation", ascending=False).reset_index(drop=True)

    # Reference valuation = portfolio value at prev_date using the qty that
    # was held BEFORE prev_date (so the % is comparable to the held bucket).
    # Period trades contribute their P&L on top, reflected in the total.
    valorisation_prev = 0.0
    for _, r in df.iterrows():
        qte_held_r = _qty_before(tx_fcp, fcp, r["ticker"], prev_date)
        valorisation_prev += qte_held_r * (r["prev_close"] or 0.0)
    valorisation_prev = float(valorisation_prev)

    variation_jour = float(df["plus_moins_value"].sum())
    variation_pct = (
        (variation_jour / valorisation_prev) if valorisation_prev else 0.0
    )

    totals = {
        "cout_total": float(df["cout_total"].sum()),
        "valorisation": float(total_valo),
        "diff_estim": float(df["diff_estim"].sum()),
        "variation_jour": variation_jour,
        "valorisation_prev": valorisation_prev,
        "variation_pct": variation_pct,
        "as_of": pd.Timestamp(as_of_date),
        "prev_date": prev_date,
    }
    return df, totals


def compute_recap(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcps: list[str],
    as_of_date: pd.Timestamp,
    dividends_by_fcp: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Return one row per FCP with day-over-day and YTD variations.

    Day variation: sum of (close_today − close_prev) × qty_held_today,
    where prev_date is the FCP-specific reference date.
    YTD variation: valorisation_today − valorisation_at_year_start, where
    year_start = January 1st of the current calendar year. Quantities at
    year_start are recomputed from the transaction history (positions can
    have changed during the year).
    """
    dividends_by_fcp = dividends_by_fcp or {}
    as_of_ts = pd.Timestamp(as_of_date)
    year_start = pd.Timestamp(year=as_of_ts.year, month=1, day=1)

    rows: list[dict] = []
    for fcp in fcps:
        divs = dividends_by_fcp.get(fcp, {})
        df_today, t_today = build_dashboard(transactions, cours, fcp, as_of_ts, divs)

        # YTD: revaluate the position held at year_start using year_start prices,
        # then compare with today's valuation. This is the cleanest "M2M YTD".
        positions_ystart = compute_positions(transactions, fcp, year_start)
        valo_ystart = 0.0
        if not positions_ystart.empty:
            for _, p in positions_ystart.iterrows():
                price = get_price_on(cours, p["ticker"], year_start) or 0.0
                valo_ystart += float(p["quantite"]) * price

        # Cash injected during YTD = net ACHAT − net VENTE
        df = _tx_dated(transactions)
        ytd_mask = (
            (df["fcp"] == fcp)
            & (df["date"] > year_start)
            & (df["date"] <= as_of_ts)
        )
        ytd_tx = df.loc[ytd_mask]
        cash_in = ytd_tx.loc[ytd_tx["sens"] == "ACHAT", "cost_in"].sum()
        cash_out = ytd_tx.loc[ytd_tx["sens"] == "VENTE", "cost_out"].sum()
        net_cash = cash_in - cash_out

        # YTD P&L = today's valo − year-start valo − net cash injected
        ytd_pl = t_today["valorisation"] - valo_ystart - net_cash
        ytd_pct = (ytd_pl / valo_ystart) if valo_ystart else 0.0

        rows.append({
            "FCP": fcp,
            "Valorisation": t_today["valorisation"],
            "Var. jour": t_today["variation_jour"],
            "Var. jour %": t_today["variation_pct"],
            "Valo début année": valo_ystart,
            "Var. YTD": ytd_pl,
            "Var. YTD %": ytd_pct,
            "Date réf. précédente": t_today["prev_date"].strftime("%d/%m/%Y"),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Exposure / cross-FCP analysis
# ---------------------------------------------------------------------------

def compute_exposures(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcps: list[str],
    as_of_date: pd.Timestamp,
    dividends_by_fcp: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Return a long-format DataFrame of per-(fcp, ticker) exposures.

    Columns: fcp, ticker, quantite, close, valorisation
    Only positions with quantite > 0 are kept.

    This is the building block consumed by the Expositions tab to produce:
      - global ticker totals (group by ticker)
      - matrix ticker × fcp (pivot)
      - concentration metrics (rank within each fcp)
    """
    dividends_by_fcp = dividends_by_fcp or {}
    as_of_ts = pd.Timestamp(as_of_date)

    rows: list[dict] = []
    for fcp in fcps:
        positions = compute_positions(transactions, fcp, as_of_ts)
        if positions.empty:
            continue
        divs = dividends_by_fcp.get(fcp, {})
        for _, p in positions.iterrows():
            qte = float(p["quantite"])
            if qte <= 0:
                continue
            ticker = p["ticker"]
            close = get_price_on(cours, ticker, as_of_ts) or 0.0
            div = divs.get(ticker, 0.0)
            close_eff = close + div
            rows.append({
                "fcp": fcp,
                "ticker": ticker,
                "quantite": qte,
                "close": close_eff,
                "valorisation": qte * close_eff,
            })

    if not rows:
        return pd.DataFrame(columns=["fcp", "ticker", "quantite", "close", "valorisation"])

    return pd.DataFrame(rows)


def concentration_metrics(exposures: pd.DataFrame) -> pd.DataFrame:
    """Per-FCP concentration: weight of top-N positions and number of lines.

    Input: long DataFrame from compute_exposures().
    Output columns: FCP, Nb lignes, Top 1 %, Top 3 %, Top 5 %, Top 10 %, Valo
    """
    if exposures.empty:
        return pd.DataFrame()

    out_rows: list[dict] = []
    for fcp, grp in exposures.groupby("fcp"):
        grp = grp.sort_values("valorisation", ascending=False).reset_index(drop=True)
        total = float(grp["valorisation"].sum())
        if total <= 0:
            continue

        def top_pct(n: int) -> float:
            return float(grp.head(n)["valorisation"].sum()) / total

        out_rows.append({
            "FCP": fcp,
            "Nb lignes": int(len(grp)),
            "Valorisation": total,
            "Top 1 %": top_pct(1),
            "Top 3 %": top_pct(3),
            "Top 5 %": top_pct(5),
            "Top 10 %": top_pct(10),
        })

    return pd.DataFrame(out_rows).sort_values("Valorisation", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Target tracking — écarts positions actuelles vs cibles
# ---------------------------------------------------------------------------

def compute_tracking(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    targets: pd.DataFrame,
    fcp: str,
    as_of_date: pd.Timestamp,
    dividends: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Compare current positions against targets for one FCP.

    `targets` must have columns: ticker, weight_pct (nullable), amount_fcfa (nullable).

    Returns one row per ticker that appears either in the current positions
    OR in the targets. Columns:

      ticker, quantite_actuelle, cours, valo_actuelle, poids_actuel,
      cible_pct, cible_fcfa,
      ecart_fcfa,          # cible_fcfa - valo_actuelle  (+ = acheter, - = vendre)
      ecart_pct,           # cible_pct  - poids_actuel
      quantite_ecart,      # ecart_fcfa / cours  (approximate nb of shares)
      sens                 # 'ACHAT', 'VENTE', or 'OK'
    """
    dividends = dividends or {}
    as_of_ts = pd.Timestamp(as_of_date)

    # Current positions
    positions = compute_positions(transactions, fcp, as_of_ts)
    total_valo = 0.0
    pos_dict: dict[str, dict] = {}

    if not positions.empty:
        for _, p in positions.iterrows():
            ticker = p["ticker"]
            qte = float(p["quantite"])
            if qte <= 0:
                continue
            close = get_price_on(cours, ticker, as_of_ts) or 0.0
            div = dividends.get(ticker, 0.0)
            close_eff = close + div
            valo = qte * close_eff
            total_valo += valo
            pos_dict[ticker] = {
                "quantite_actuelle": qte,
                "cours": close_eff,
                "valo_actuelle": valo,
            }

    # Build unified ticker universe (positions ∪ targets)
    target_tickers = set(
        targets["ticker"].dropna().str.strip().tolist()
        if not targets.empty else []
    )
    all_tickers = set(pos_dict.keys()) | target_tickers

    rows: list[dict] = []
    for ticker in sorted(all_tickers):
        pos = pos_dict.get(ticker, {})
        qte_act = float(pos.get("quantite_actuelle", 0.0))
        close = float(pos.get("cours", 0.0))
        valo_act = float(pos.get("valo_actuelle", 0.0))
        poids_act = valo_act / total_valo if total_valo else 0.0

        # Get target for this ticker
        t_row = targets[targets["ticker"].str.strip() == ticker]
        if t_row.empty:
            if qte_act > 0:
                # Held but not in targets → must be sold entirely for reallocation
                cible_pct  = 0.0
                cible_fcfa = 0.0
            else:
                cible_pct  = None
                cible_fcfa = None
        else:
            r = t_row.iloc[0]
            cible_pct = float(r["weight_pct"]) if pd.notna(r.get("weight_pct")) else None
            cible_fcfa = float(r["amount_fcfa"]) if pd.notna(r.get("amount_fcfa")) else None

        # Derive missing cible from the other dimension
        if cible_pct is not None and cible_fcfa is None and total_valo:
            cible_fcfa = cible_pct * total_valo
        elif cible_fcfa is not None and cible_pct is None and total_valo:
            cible_pct = cible_fcfa / total_valo

        # Ecarts
        if cible_fcfa is not None:
            ecart_fcfa = cible_fcfa - valo_act
        else:
            ecart_fcfa = None

        if cible_pct is not None:
            ecart_pct = cible_pct - poids_act
        else:
            ecart_pct = None

        if ecart_fcfa is not None and close and close > 0:
            quantite_ecart = ecart_fcfa / close
        else:
            quantite_ecart = None

        # Sens
        if ecart_fcfa is None:
            sens = "—"
        elif abs(ecart_fcfa) < max(close or 1, 1) * 0.5:
            # Less than half a share away → negligible
            sens = "OK"
        elif ecart_fcfa > 0:
            sens = "ACHAT"
        else:
            sens = "VENTE"

        rows.append({
            "ticker": ticker,
            "quantite_actuelle": qte_act,
            "cours": close if close else None,
            "valo_actuelle": valo_act,
            "poids_actuel": poids_act,
            "cible_pct": cible_pct,
            "cible_fcfa": cible_fcfa,
            "ecart_fcfa": ecart_fcfa,
            "ecart_pct": ecart_pct,
            "quantite_ecart": quantite_ecart,
            "sens": sens,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Sort: VENTE first, then ACHAT, then OK, then no target
    order = {"VENTE": 0, "ACHAT": 1, "OK": 2, "—": 3}
    df["_sort"] = df["sens"].map(order).fillna(3)
    # Use apply(abs) on individual values to avoid pandas 3.x None issue
    def _safe_abs(v):
        try:
            return abs(float(v))
        except (TypeError, ValueError):
            return 0.0
    df["_ecart_abs"] = df["ecart_fcfa"].apply(_safe_abs)
    df = (df.sort_values(["_sort", "_ecart_abs"], ascending=[True, False])
            .drop(columns=["_sort", "_ecart_abs"])
            .reset_index(drop=True))
    return df


# ---------------------------------------------------------------------------
# Action drivers — P&L attribution by stock across all FCPs
# ---------------------------------------------------------------------------

def compute_action_drivers(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcps: list[str],
    as_of_date: pd.Timestamp,
    dividends_by_fcp: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Compute P&L contribution of each stock across all FCPs.

    For each (ticker, fcp) pair that had a non-zero position on as_of_date,
    compute:
      - qty_held        : net quantity held (from _qty_before using fcp prev date)
      - close_prev      : previous reference price (per FCP calendar)
      - close_today     : today's price
      - variation_unit  : close_today - close_prev
      - pnl_contribution: qty_held * variation_unit  (held bucket only)
      - pnl_period      : P&L from trades in (prev_date, as_of_date]
      - pnl_total       : pnl_contribution + pnl_period

    Returns a long DataFrame with columns:
      ticker, fcp, secteur (placeholder),
      qty_held, close_prev, close_today, variation_unit,
      valo_today, pnl_contribution, pnl_period, pnl_total,
      pnl_pct_of_fcp (filled in a second pass)
    """
    dividends_by_fcp = dividends_by_fcp or {}
    as_of_ts = pd.Timestamp(as_of_date)

    rows: list[dict] = []

    for fcp in fcps:
        positions = compute_positions(transactions, fcp, as_of_ts)
        if positions.empty:
            continue

        prev_date = previous_cours_date(fcp, as_of_ts)
        divs = dividends_by_fcp.get(fcp, {})

        # Lookups go through the shared index (see _tx_index): no per-call copy.
        tx_fcp = transactions

        # Compute total FCP valuation for % calculation later
        fcp_pnl_total = 0.0

        fcp_rows = []
        for _, p in positions.iterrows():
            ticker = p["ticker"]
            qte_now = float(p["quantite"])
            if qte_now <= 0:
                continue

            close_prev = get_price_on(cours, ticker, prev_date) or 0.0
            close_today = get_price_on(cours, ticker, as_of_ts) or 0.0
            div = divs.get(ticker, 0.0)
            close_today_eff = close_today + div
            variation_unit = close_today_eff - close_prev
            valo_today = qte_now * close_today_eff

            # Held bucket
            qte_held = _qty_before(tx_fcp, fcp, ticker, prev_date)
            pnl_held = qte_held * variation_unit

            # Period trades bucket
            period = _period_trades(tx_fcp, fcp, ticker, prev_date, as_of_ts)
            pnl_period = 0.0
            for _, t in period.iterrows():
                qty_t = float(t["quantite"])
                prix_t = float(t["prix"])
                frais_t = float(t["frais"])
                if t["sens"] == "ACHAT":
                    pnl_period += qty_t * (close_today_eff - prix_t) - frais_t
                else:
                    pnl_period += qty_t * (prix_t - close_today_eff) - frais_t

            pnl_total = pnl_held + pnl_period
            fcp_pnl_total += pnl_total

            fcp_rows.append({
                "ticker": ticker,
                "fcp": fcp,
                "qty_held": qte_held,
                "qty_now": qte_now,
                "close_prev": close_prev,
                "close_today": close_today_eff,
                "variation_unit": variation_unit,
                "valo_today": valo_today,
                "pnl_held": pnl_held,
                "pnl_period": pnl_period,
                "pnl_total": pnl_total,
                "fcp_pnl_total": 0.0,  # filled below
            })

        # Back-fill fcp_pnl_total
        for r in fcp_rows:
            r["fcp_pnl_total"] = fcp_pnl_total
        rows.extend(fcp_rows)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # pnl_pct_of_fcp: contribution of this ticker to its FCP's total P&L
    df["pnl_pct_of_fcp"] = df.apply(
        lambda r: r["pnl_total"] / r["fcp_pnl_total"]
        if r["fcp_pnl_total"] != 0 else 0.0,
        axis=1,
    )

    return df


def aggregate_drivers_by_ticker(drivers: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the long drivers DataFrame by ticker.

    Returns one row per ticker with:
      ticker, variation_unit, close_prev, close_today,
      qty_total (all FCPs), valo_total, pnl_total,
      n_fcps (number of FCPs holding this ticker),
      fcp_list (comma-separated list of FCPs)
    """
    if drivers.empty:
        return pd.DataFrame()

    agg = drivers.groupby("ticker").agg(
        variation_unit=("variation_unit", "first"),
        close_prev=("close_prev", "first"),
        close_today=("close_today", "first"),
        qty_total=("qty_now", "sum"),
        valo_total=("valo_today", "sum"),
        pnl_total=("pnl_total", "sum"),
        n_fcps=("fcp", "nunique"),
        fcp_list=("fcp", lambda s: ", ".join(sorted(s.unique()))),
    ).reset_index()

    agg = agg.sort_values("pnl_total", ascending=False).reset_index(drop=True)
    return agg


# ---------------------------------------------------------------------------
# Period performance — variation between two dates
# ---------------------------------------------------------------------------

def compute_period_perf(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcps: list[str],
    date_debut: pd.Timestamp,
    date_fin: pd.Timestamp,
    dividends_by_fcp: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Compute FCP performance over a custom date range [date_debut, date_fin].

    For each FCP:
      valo_debut       : portfolio value at date_debut (positions × prices)
      valo_fin         : portfolio value at date_fin
      flux_nets        : net cash flows during the period
                         = Σ cost_in (ACHATS) − Σ cost_out (VENTES)
                         strictly in (date_debut, date_fin]
      variation_brute  : valo_fin − valo_debut
      variation_nette  : valo_fin − valo_debut − flux_nets  (pure performance)
      variation_brute_pct : variation_brute / valo_debut
      variation_nette_pct : variation_nette / valo_debut

    Returns one row per FCP, sorted by variation_nette descending.
    """
    dividends_by_fcp = dividends_by_fcp or {}
    d0 = pd.Timestamp(date_debut)
    d1 = pd.Timestamp(date_fin)

    rows: list[dict] = []

    for fcp in fcps:
        divs = dividends_by_fcp.get(fcp, {})

        # Valuation at date_debut
        pos0 = compute_positions(transactions, fcp, d0)
        valo_debut = 0.0
        if not pos0.empty:
            for _, p in pos0.iterrows():
                if float(p["quantite"]) <= 0:
                    continue
                price = get_price_on(cours, p["ticker"], d0) or 0.0
                div   = divs.get(p["ticker"], 0.0)
                valo_debut += float(p["quantite"]) * (price + div)

        # Valuation at date_fin
        pos1 = compute_positions(transactions, fcp, d1)
        valo_fin = 0.0
        if not pos1.empty:
            for _, p in pos1.iterrows():
                if float(p["quantite"]) <= 0:
                    continue
                price = get_price_on(cours, p["ticker"], d1) or 0.0
                div   = divs.get(p["ticker"], 0.0)
                valo_fin += float(p["quantite"]) * (price + div)

        # Net cash flows strictly inside the period (d0, d1]
        if not transactions.empty:
            df = _tx_dated(transactions)
            mask = (
                (df["fcp"] == fcp)
                & (df["date"] > d0)
                & (df["date"] <= d1)
            )
            period_tx = df.loc[mask]
            flux_in  = float(period_tx.loc[period_tx["sens"]=="ACHAT","cost_in"].sum())
            # Produit net de cession = quantité × prix de vente − frais
            ventes_tx = period_tx.loc[period_tx["sens"] == "VENTE"]
            flux_out = float(
                (ventes_tx["quantite"] * ventes_tx["prix"] - ventes_tx["frais"])
                .clip(lower=0).sum()
            )
            flux_nets = flux_in - flux_out
        else:
            flux_nets = 0.0

        variation_brute = valo_fin - valo_debut
        variation_nette = valo_fin - valo_debut - flux_nets

        rows.append({
            "FCP":                 fcp,
            "Valo début":          valo_debut,
            "Valo fin":            valo_fin,
            "Flux nets":           flux_nets,
            "Variation brute":     variation_brute,
            "Variation nette":     variation_nette,
            "Variation brute %":   variation_brute / valo_debut if valo_debut else 0.0,
            "Variation nette %":   variation_nette / valo_debut if valo_debut else 0.0,
        })

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values("Variation nette", ascending=False).reset_index(drop=True)
    return df_out


# ---------------------------------------------------------------------------
# Attribution de performance — tableau Portefeuille Initial / Achats / Ventes
# / Dividendes / Effet Marché / Portefeuille Final
# ---------------------------------------------------------------------------

def compute_attribution(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcps: list[str],
    date_debut: pd.Timestamp,
    date_fin: pd.Timestamp,
    dividends_dated: list[dict] | None = None,
) -> pd.DataFrame:
    """Compute the performance attribution table for a period.

    For each FCP:

      Ptf_initial   = Valo à date_debut
      Achats        = Σ cost_in des ACHATS dans (date_debut, date_fin]
      Ventes        = Σ cost_out des VENTES dans (date_debut, date_fin]
      Dividendes    = Σ (div_unitaire × quantité_détenue_à_payment_date)
                      pour tous les payment_date ∈ (date_debut, date_fin]
      Ptf_final     = Valo à date_fin
      Effet_marché  = Ptf_final − Ptf_initial − Achats + Ventes − Dividendes

    `dividends_dated` is a list of dicts:
        [{"ticker": "SNTS", "amount": 500, "payment_date": "2026-03-15"}, ...]

    Returns one row per FCP.
    """
    dividends_dated = dividends_dated or []
    d0 = pd.Timestamp(date_debut)
    d1 = pd.Timestamp(date_fin)

    rows: list[dict] = []

    for fcp in fcps:

        # ── Portefeuille initial ──────────────────────────────────────────
        pos0 = compute_positions(transactions, fcp, d0)
        ptf_initial = 0.0
        for _, p in pos0.iterrows():
            if float(p["quantite"]) <= 0:
                continue
            price = get_price_on(cours, p["ticker"], d0) or 0.0
            ptf_initial += float(p["quantite"]) * price

        # ── Portefeuille final ────────────────────────────────────────────
        pos1 = compute_positions(transactions, fcp, d1)
        ptf_final = 0.0
        for _, p in pos1.iterrows():
            if float(p["quantite"]) <= 0:
                continue
            price = get_price_on(cours, p["ticker"], d1) or 0.0
            ptf_final += float(p["quantite"]) * price

        # ── Flux dans la période (date_debut, date_fin] ───────────────────
        achats = 0.0
        ventes = 0.0
        if not transactions.empty:
            df = _tx_dated(transactions)
            mask = (
                (df["fcp"] == fcp)
                & (df["date"] > d0)
                & (df["date"] <= d1)
            )
            period_tx = df.loc[mask]
            achats = float(
                period_tx.loc[period_tx["sens"] == "ACHAT", "cost_in"].sum()
            )
            # Produit net de cession = quantité × prix de vente − frais
            ventes_tx = period_tx.loc[period_tx["sens"] == "VENTE"]
            ventes = float(
                (ventes_tx["quantite"] * ventes_tx["prix"] - ventes_tx["frais"])
                .clip(lower=0).sum()
            )

        # ── Dividendes dans la période ────────────────────────────────────
        # For each unique payment_date in the dividends list that falls
        # inside (date_debut, date_fin], multiply dividend per share by
        # the quantity held in this FCP on that payment date.
        dividendes = 0.0
        if dividends_dated:
            seen_dates: set[str] = set()
            for d in dividends_dated:
                try:
                    pd_date = pd.Timestamp(d["payment_date"]).normalize()
                except (KeyError, ValueError, TypeError):
                    continue
                if not (d0 < pd_date <= d1):
                    continue
                ticker_d = str(d.get("ticker", "")).strip().upper()
                amount_d = float(d.get("amount", 0) or 0)
                if not ticker_d or amount_d == 0:
                    continue
                # Quantity held by this FCP on the payment date
                qty_d = quantity_held(transactions, fcp, ticker_d, pd_date)
                if qty_d > 0:
                    dividendes += qty_d * amount_d

        # ── Effet marché ──────────────────────────────────────────────────
        # Ptf_final = Ptf_initial + Achats − Ventes + Dividendes + Effet_marché
        # ⟹ Effet_marché = Ptf_final − Ptf_initial − Achats + Ventes − Dividendes
        effet_marche = ptf_final - ptf_initial - achats + ventes - dividendes

        # ── Effet marché latent ───────────────────────────────────────────
        # Variation de cours sur les positions CONSERVÉES entre d0 et d1.
        # Pour chaque titre encore détenu à d1, on mesure la variation
        # (cours_fin − cours_début_période) × qty_finale.
        # Reflète la performance de marché pure sur la fenêtre, indépendamment
        # du prix d'acquisition historique (CMP).
        effet_latent = 0.0
        for _, p in pos1.iterrows():
            qty_f = float(p["quantite"])
            if qty_f <= 0:
                continue
            ticker = p["ticker"]
            c1_ = get_price_on(cours, ticker, d1) or 0.0
            c0_ = get_price_on(cours, ticker, d0) or 0.0
            effet_latent += qty_f * (c1_ - c0_)

        # ── Effet marché réalisé ──────────────────────────────────────────
        # Plus-value nette sur les cessions : produit net − coût de revient.
        # Produit net = qty × prix_vente − frais  (déjà dans `ventes`)
        # Coût de revient = qty × CMP_at_tx  (stocké dans cost_out de la DB)
        # ⟹ Réalisé = (qty × prix_vente − frais) − (qty × CMP)
        #            = ventes_nettes − Σ cost_out
        effet_realise = 0.0
        if not transactions.empty and not period_tx.empty:
            ventes_tx_r = period_tx.loc[period_tx["sens"] == "VENTE"]
            if not ventes_tx_r.empty:
                produit_net = float(
                    (ventes_tx_r["quantite"] * ventes_tx_r["prix"]
                     - ventes_tx_r["frais"]).clip(lower=0).sum()
                )
                cout_revient = float(ventes_tx_r["cost_out"].sum())
                effet_realise = produit_net - cout_revient

        rows.append({
            "FCP":                    fcp,
            "Ptf. Actions début":     ptf_initial,
            "Achats":                 achats,
            "Ventes":                 ventes,
            "Dividendes":             dividendes,
            "Effet marché":           effet_marche,
            "Effet marché latent":    effet_latent,
            "Effet marché réalisé":   effet_realise,
            "Ptf. Actions fin":       ptf_final,
        })

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values(
            "Ptf. Actions fin", ascending=False
        ).reset_index(drop=True)
    return df_out


# ---------------------------------------------------------------------------
# Active management analysis
# ---------------------------------------------------------------------------

def compute_active_management(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcps: list[str],
    date_debut: pd.Timestamp,
    date_fin: pd.Timestamp,
    dividends_dated: list[dict] | None = None,
) -> pd.DataFrame:
    """Compute active management metrics for each FCP over [date_debut, date_fin].

    Metrics per FCP:
      alpha            : FCP return - BRVM index return (same period)
      turnover         : (achats + ventes) / (2 * valo_moyenne)
      frais_pct        : total frais / valo_moyenne
      hit_ratio        : % of buy transactions where cours_fin > prix_achat
      timing_score     : avg (prix_vente - cours_debut) for sells (>0 = good timing)
      stock_picking    : contribution from held stocks vs BRVM
      n_achats         : number of buy transactions in period
      n_ventes         : number of sell transactions in period
      rendement_fcp    : (valo_fin - valo_debut - flux_nets) / valo_debut
      rendement_brvm   : BRVM index return over the same period
    """
    dividends_dated = dividends_dated or []
    d0 = pd.Timestamp(date_debut)
    d1 = pd.Timestamp(date_fin)
    BENCHMARK = ".BRVMCI"

    # BRVM index return
    brvm_start = get_price_on(cours, BENCHMARK, d0) or 0.0
    brvm_end   = get_price_on(cours, BENCHMARK, d1) or 0.0
    rendement_brvm = (brvm_end - brvm_start) / brvm_start if brvm_start else 0.0

    rows: list[dict] = []

    for fcp in fcps:

        # Positions and valuations
        pos0 = compute_positions(transactions, fcp, d0)
        pos1 = compute_positions(transactions, fcp, d1)

        valo_debut = 0.0
        for _, p in pos0.iterrows():
            if float(p["quantite"]) <= 0:
                continue
            valo_debut += float(p["quantite"]) * (get_price_on(cours, p["ticker"], d0) or 0.0)

        valo_fin = 0.0
        for _, p in pos1.iterrows():
            if float(p["quantite"]) <= 0:
                continue
            valo_fin += float(p["quantite"]) * (get_price_on(cours, p["ticker"], d1) or 0.0)

        valo_moy = (valo_debut + valo_fin) / 2 if (valo_debut + valo_fin) > 0 else 1.0

        # Period transactions
        if not transactions.empty:
            df_tx = _tx_dated(transactions)
            mask = (
                (df_tx["fcp"] == fcp)
                & (df_tx["date"] > d0)
                & (df_tx["date"] <= d1)
            )
            period_tx = df_tx.loc[mask].copy()
        else:
            period_tx = transactions.iloc[0:0].copy()

        achats_tx = period_tx[period_tx["sens"] == "ACHAT"]
        ventes_tx  = period_tx[period_tx["sens"] == "VENTE"]

        achats_amt = float(achats_tx["cost_in"].sum())
        ventes_amt = float(
            (ventes_tx["quantite"] * ventes_tx["prix"] - ventes_tx["frais"])
            .clip(lower=0).sum()
        ) if not ventes_tx.empty else 0.0

        frais_total = float(period_tx["frais"].sum())
        n_achats    = len(achats_tx)
        n_ventes    = len(ventes_tx)
        flux_nets   = achats_amt - ventes_amt

        # Turnover & frais friction
        turnover  = (achats_amt + ventes_amt) / (2 * valo_moy)
        frais_pct = frais_total / valo_moy if valo_moy else 0.0

        # FCP return (net of flows)
        rendement_fcp = (valo_fin - valo_debut - flux_nets) / valo_debut                         if valo_debut else 0.0
        alpha = rendement_fcp - rendement_brvm

        # Hit ratio: buy transactions where cours_fin > prix_achat
        hits = 0
        for _, t in achats_tx.iterrows():
            c_fin = get_price_on(cours, t["ticker"], d1) or 0.0
            if c_fin > float(t["prix"]):
                hits += 1
        hit_ratio = hits / n_achats if n_achats else None

        # Timing score for sells: avg(prix_vente - cours_debut_periode)
        # Positive = sold above the starting price = captured gains
        timing_scores = []
        for _, t in ventes_tx.iterrows():
            c_deb = get_price_on(cours, t["ticker"], d0) or float(t["prix"])
            timing_scores.append(float(t["prix"]) - c_deb)
        timing_score = sum(timing_scores) / len(timing_scores) if timing_scores else None

        # Stock picking: contribution of each held title vs BRVM
        # = Σ w_i × (r_i - r_BRVM) where w_i = weight in portfolio at d0
        stock_picking = 0.0
        if valo_debut > 0 and brvm_start > 0:
            for _, p in pos0.iterrows():
                qty = float(p["quantite"])
                if qty <= 0:
                    continue
                c0 = get_price_on(cours, p["ticker"], d0) or 0.0
                c1_ = get_price_on(cours, p["ticker"], d1) or 0.0
                if c0 <= 0:
                    continue
                r_i = (c1_ - c0) / c0
                w_i = (qty * c0) / valo_debut
                stock_picking += w_i * (r_i - rendement_brvm)

        rows.append({
            "FCP":              fcp,
            "Valo début":       valo_debut,
            "Valo fin":         valo_fin,
            "Rendement FCP":    rendement_fcp,
            "Rendement BRVM":   rendement_brvm,
            "Alpha":            alpha,
            "Stock picking":    stock_picking,
            "Turnover":         turnover,
            "Frais (% valo)":   frais_pct,
            "Hit ratio":        hit_ratio,
            "Timing score":     timing_score,
            "Nb achats":        n_achats,
            "Nb ventes":        n_ventes,
            "Frais total":      frais_total,
        })

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values("Alpha", ascending=False).reset_index(drop=True)
    return df_out


def compute_stock_picking_detail(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcp: str,
    date_debut: pd.Timestamp,
    date_fin: pd.Timestamp,
) -> pd.DataFrame:
    """Per-ticker stock picking contribution for one FCP.

    Returns one row per ticker held at date_debut with:
      ticker, poids_debut, rendement_titre, rendement_brvm,
      alpha_titre, contribution (poids × alpha_titre)
    """
    d0 = pd.Timestamp(date_debut)
    d1 = pd.Timestamp(date_fin)
    BENCHMARK = ".BRVMCI"

    brvm_start = get_price_on(cours, BENCHMARK, d0) or 0.0
    brvm_end   = get_price_on(cours, BENCHMARK, d1) or 0.0
    rendement_brvm = (brvm_end - brvm_start) / brvm_start if brvm_start else 0.0

    pos0 = compute_positions(transactions, fcp, d0)
    valo_debut = sum(
        float(p["quantite"]) * (get_price_on(cours, p["ticker"], d0) or 0.0)
        for _, p in pos0.iterrows() if float(p["quantite"]) > 0
    )

    rows = []
    for _, p in pos0.iterrows():
        qty = float(p["quantite"])
        if qty <= 0:
            continue
        ticker = p["ticker"]
        c0 = get_price_on(cours, ticker, d0) or 0.0
        c1_ = get_price_on(cours, ticker, d1) or 0.0
        if c0 <= 0:
            continue
        r_i  = (c1_ - c0) / c0
        w_i  = (qty * c0) / valo_debut if valo_debut else 0.0
        alpha_i = r_i - rendement_brvm
        rows.append({
            "Ticker":            ticker,
            "Cours début":       c0,
            "Cours fin":         c1_,
            "Rendement titre":   r_i,
            "Rendement BRVM":    rendement_brvm,
            "Alpha titre":       alpha_i,
            "Poids début":       w_i,
            "Contribution":      w_i * alpha_i,
            "Qty":               qty,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Contribution", ascending=False).reset_index(drop=True)
    return df


def compute_transaction_analysis(
    transactions: pd.DataFrame,
    cours: pd.DataFrame,
    fcp: str,
    date_debut: pd.Timestamp,
    date_fin: pd.Timestamp,
) -> pd.DataFrame:
    """Per-transaction analysis: timing quality and P&L.

    Returns one row per transaction with:
      date, ticker, sens, qty, prix_tx, cours_debut, cours_fin,
      timing_vs_debut, pnl_realise (ventes) or pnl_latent (achats)
    """
    d0 = pd.Timestamp(date_debut)
    d1 = pd.Timestamp(date_fin)

    if transactions.empty:
        return pd.DataFrame()

    df = _tx_dated(transactions)
    mask = (
        (df["fcp"] == fcp)
        & (df["date"] > d0)
        & (df["date"] <= d1)
    )
    period_tx = df.loc[mask].copy()
    if period_tx.empty:
        return pd.DataFrame()

    rows = []
    for _, t in period_tx.iterrows():
        ticker = t["ticker"]
        prix_tx = float(t["prix"])
        qty     = float(t["quantite"])
        frais_t = float(t["frais"])
        c0 = get_price_on(cours, ticker, d0) or prix_tx
        c1_ = get_price_on(cours, ticker, d1) or prix_tx

        if t["sens"] == "ACHAT":
            pnl = qty * (c1_ - prix_tx) - frais_t  # latent P&L
            timing = prix_tx - c0  # negative = bought cheaper than period start = good
        else:
            pnl = qty * (prix_tx - float(t.get("cmp_at_tx", prix_tx))) - frais_t
            timing = prix_tx - c0  # positive = sold above period start = good

        rows.append({
            "Date":          t["date"].strftime("%d/%m/%Y"),
            "Ticker":        ticker,
            "Sens":          t["sens"],
            "Qté":           int(qty),
            "Prix tx":       prix_tx,
            "Cours début":   c0,
            "Cours fin":     c1_,
            "Timing":        timing,
            "P&L":           pnl,
            "Frais":         frais_t,
        })

    return pd.DataFrame(rows).sort_values("Date")


# ---------------------------------------------------------------------------
# Break-even: target prices needed to offset a negative daily variation
# ---------------------------------------------------------------------------

# Maximum daily price move allowed on the BRVM (±7.5% per session).
BRVM_DAILY_LIMIT = 0.075

# Weight of each title in the break-even combination, from the fund's target
# tracking (compute_tracking 'sens'): titles to BUY carry more of the rebound,
# titles to SELL still help, but less.
PRIORITY_WEIGHTS = {"ACHAT": 2.0, "NEUTRE": 1.0, "VENTE": 0.5}


def _priority_of(sens) -> str:
    s = str(sens or "").upper()
    return s if s in ("ACHAT", "VENTE") else "NEUTRE"


def _waterfill(base: np.ndarray, room: np.ndarray, target: float) -> tuple[float, np.ndarray]:
    """Find the common factor f with  Σ base·min(f, room) = target.

    base : gain per unit of f for each line (FCFA)
    room : maximum f allowed for each line (its session cap)
    Returns (f, f_applied per line). If even every line at its cap cannot
    reach the target, f = inf and every line is at its cap.
    """
    if target <= 0 or len(base) == 0:
        return 0.0, np.zeros(len(base))
    if float((base * room).sum()) < target:
        return float("inf"), room.copy()
    order = np.argsort(room)
    r_sorted, b_sorted = room[order], base[order]
    done = 0.0                      # gain from lines already capped
    free = float(b_sorted.sum())    # base of lines not yet capped
    f = 0.0
    for k in range(len(r_sorted)):
        f_try = (target - done) / free if free > 0 else float("inf")
        if f_try <= r_sorted[k]:
            f = f_try
            break
        done += b_sorted[k] * r_sorted[k]
        free -= b_sorted[k]
    return f, np.minimum(f, room)


def compute_breakeven_targets(
    rows: pd.DataFrame,
    variation_jour: float,
    ref_prices: dict[str, float] | None = None,
    daily_limit: float = BRVM_DAILY_LIMIT,
    n_sessions: int = 1,
    priorities: dict[str, str] | None = None,
    weights: dict[str, float] | None = None,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Target prices that would bring a negative daily variation back to zero.

    `rows` is the DataFrame returned by build_dashboard; the loss to recover
    is L = −variation_jour. Raising a title's price by Δ improves the day
    P&L by quantité × Δ.

    Cap: on the BRVM a title cannot close more than daily_limit above its
    previous close in one session. Over `n_sessions` sessions left before
    the fund's next valuation (1 for daily FCPs, up to 5 for weekly ones),
    the highest reachable price is reference × (1 + daily_limit) ** n.
    `ref_prices` gives the reference (last close before the first of those
    sessions); the title's `prev_close` is used when missing.

    Returns (summary, single, combo):
      • single : one title alone recovers L  (cours + L / quantité), flagged
                 reachable when that price stays under the session cap.
      • combo  : combination over the titles DOWN today. Each one regains a
                 share of its own drop (cours actuel → cours veille) equal to
                 f × its priority weight, without exceeding its cap; lines
                 that hit their cap hand the rest to the others. If the titles
                 down today are not enough, the other lines are added
                 (weighted % rise, within their cap).

    Priority comes from the fund's target tracking (`priorities`:
    {ticker: sens}): ACHAT ×2, neutral ×1, VENTE ×0.5 (PRIORITY_WEIGHTS).
    Titles to buy are favoured; titles to sell still contribute, but less.
    """
    no = ({"perte": 0.0}, pd.DataFrame(), pd.DataFrame())
    if rows is None or rows.empty or variation_jour is None or variation_jour >= 0:
        return no
    act = rows[(rows["quantite"] > 0) & (rows["close"] > 0)].copy()
    if act.empty:
        return no
    ref_prices = ref_prices or {}
    priorities = priorities or {}
    weights = {**PRIORITY_WEIGHTS, **(weights or {})}

    perte = float(-variation_jour)
    valo = float(act["valorisation"].sum())
    act["ref"] = [
        float(ref_prices.get(t) or p or c)
        for t, p, c in zip(act["ticker"], act["prev_close"], act["close"])
    ]
    n_sessions = max(int(n_sessions), 1)
    act["plafond"] = act["ref"] * (1 + daily_limit) ** n_sessions
    act["marge"] = (act["plafond"] - act["close"]).clip(lower=0)  # FCFA / action
    act["priorite"] = [_priority_of(priorities.get(t)) for t in act["ticker"]]
    act["poids_prio"] = act["priorite"].map(weights).astype(float)

    # ── Uniform rise and single-title targets ─────────────────────────────
    hausse_uniforme = perte / valo if valo else float("nan")
    act["hausse_seule"] = perte / act["valorisation"]
    act["cours_cible_seul"] = act["close"] + perte / act["quantite"]
    act["atteignable"] = act["cours_cible_seul"] <= act["plafond"] + 1e-9
    act["cours_cible_uniforme"] = act["close"] * (1 + hausse_uniforme)
    single = (
        act[["ticker", "priorite", "quantite", "close", "poids", "cours_cible_seul",
             "hausse_seule", "atteignable", "cours_cible_uniforme", "plafond"]]
        .sort_values("hausse_seule").reset_index(drop=True)
    )

    # ── Combination over titles down today ────────────────────────────────
    act["baisse_unit"] = (act["prev_close"] - act["close"]).clip(lower=0)
    down = act[act["baisse_unit"] > 0]
    q, d, m, w = (down["quantite"].to_numpy(float), down["baisse_unit"].to_numpy(float),
                  down["marge"].to_numpy(float), down["poids_prio"].to_numpy(float))
    # unit of f = the title's own drop × its priority weight; cap = margin
    # expressed in that unit
    dw = d * w
    f, f_i = _waterfill(q * dw, np.divide(m, dw, out=np.zeros_like(m), where=dw > 0), perte)
    delta_down = f_i * dw
    part_down = f_i * w
    gain_down = float((q * delta_down).sum())

    # Not enough with titles down → other lines, same % rise, within cap
    reste = max(perte - gain_down, 0.0)
    others = act[act["baisse_unit"] <= 0]
    delta_oth = np.zeros(len(others))
    if reste > 1e-6 and len(others):
        qo, co, mo, wo = (others["quantite"].to_numpy(float), others["close"].to_numpy(float),
                          others["marge"].to_numpy(float), others["poids_prio"].to_numpy(float))
        cw = co * wo
        _, g = _waterfill(qo * cw, np.divide(mo, cw, out=np.zeros_like(mo), where=cw > 0), reste)
        delta_oth = g * cw
    gain_oth = float((others["quantite"].to_numpy(float) * delta_oth).sum()) if len(others) else 0.0

    combo = pd.concat([
        pd.DataFrame({
            "ticker": down["ticker"].to_numpy(), "groupe": "En baisse",
            "priorite": down["priorite"].to_numpy(), "quantite": q, "prev_close": down["prev_close"].to_numpy(float),
            "close": down["close"].to_numpy(float), "delta": delta_down,
            "part_regagnee": part_down, "plafond": down["plafond"].to_numpy(float),
        }),
        pd.DataFrame({
            "ticker": others["ticker"].to_numpy(), "groupe": "Complément",
            "priorite": others["priorite"].to_numpy(),
            "quantite": others["quantite"].to_numpy(float),
            "prev_close": others["prev_close"].to_numpy(float),
            "close": others["close"].to_numpy(float), "delta": delta_oth,
            "part_regagnee": np.nan, "plafond": others["plafond"].to_numpy(float),
        }),
    ], ignore_index=True)
    combo = combo[combo["delta"] > 1e-9].copy()
    combo["cours_cible"] = combo["close"] + combo["delta"]
    combo["hausse"] = combo["delta"] / combo["close"]
    combo["contribution"] = combo["quantite"] * combo["delta"]
    combo["au_plafond"] = combo["cours_cible"] >= combo["plafond"] - 1e-6
    combo["_rang"] = combo["priorite"].map({"ACHAT": 0, "NEUTRE": 1, "VENTE": 2})
    combo = combo.sort_values(["groupe", "_rang", "contribution"],
                              ascending=[False, True, False]) \
                 .drop(columns="_rang").reset_index(drop=True)

    couvert = gain_down + gain_oth
    summary = {
        "perte": perte,
        "valorisation": valo,
        "hausse_uniforme": hausse_uniforme,
        "n_titres_seuls_atteignables": int(act["atteignable"].sum()),
        "n_titres_en_baisse": int(len(down)),
        "part_baisse_regagnee": None if np.isinf(f) else float(f),
        "baisses_suffisent": not np.isinf(f),
        "complement_necessaire": reste > 1e-6,
        "couvert": couvert,
        "possible_en_une_seance": couvert >= perte - 1e-3,
        "daily_limit": daily_limit,
        "n_sessions": n_sessions,
        "weights": weights,
        "priorites_presentes": sorted(set(down["priorite"]),
                                      key=["ACHAT", "NEUTRE", "VENTE"].index),
        "suivi_cibles": bool(priorities),
        "plafond_cumule": (1 + daily_limit) ** n_sessions - 1,
    }
    return summary, single, combo


def sessions_until_valuation(fcp: str, as_of: pd.Timestamp) -> tuple[int, pd.Timestamp]:
    """Sessions left, as_of included, until the fund's next valuation date.

    Daily FCPs: 1 session (the as_of date). Weekly FCPs: business days from
    as_of up to the next occurrence of their valuation weekday (as_of itself
    if it is that weekday). Public holidays are not taken into account.
    Returns (n_sessions, valuation_date).
    """
    from fcp_calendar import WEEKLY_FCPS
    as_of = pd.Timestamp(as_of).normalize()
    if fcp not in WEEKLY_FCPS:
        return 1, as_of
    val_date = as_of + pd.Timedelta(days=(WEEKLY_FCPS[fcp] - as_of.weekday()) % 7)
    n = len(pd.bdate_range(as_of, val_date))
    return max(n, 1), val_date
