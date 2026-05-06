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

from dataclasses import dataclass

import pandas as pd

from fcp_calendar import previous_cours_date


@dataclass
class PortfolioRow:
    ticker: str
    quantite: float
    cmp: float
    cout_total: float
    valorisation: float
    diff_estim: float
    poids: float
    prev_close: float
    close: float
    variation: float
    plus_moins_value: float
    dividende: float = 0.0


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
    if transactions.empty:
        return pd.DataFrame(columns=["ticker", "quantite", "cout_total", "cmp"])

    df = transactions.copy()
    df["date"] = pd.to_datetime(df["date"])
    mask = (df["fcp"] == fcp) & (df["date"] <= pd.Timestamp(as_of_date))
    df = df.loc[mask]

    if df.empty:
        return pd.DataFrame(columns=["ticker", "quantite", "cout_total", "cmp"])

    df["signed_qty"] = df.apply(
        lambda r: r["quantite"] if r["sens"] == "ACHAT" else -r["quantite"],
        axis=1,
    )
    grouped = df.groupby("ticker").agg(
        quantite=("signed_qty", "sum"),
        cost_in=("cost_in", "sum"),
        cost_out=("cost_out", "sum"),
    )
    grouped["cout_total"] = grouped["cost_in"] - grouped["cost_out"]
    grouped["cmp"] = grouped.apply(
        lambda r: r["cout_total"] / r["quantite"] if r["quantite"] else 0.0,
        axis=1,
    )
    return grouped[["quantite", "cout_total", "cmp"]].reset_index()


def get_price_on(cours: pd.DataFrame, ticker: str, target_date: pd.Timestamp) -> float | None:
    """Last known price for `ticker` on or before `target_date`. None if absent."""
    if cours.empty:
        return None
    df = cours[cours["ticker"] == ticker].copy()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= pd.Timestamp(target_date)].sort_values("date")
    if df.empty:
        return None
    return float(df.iloc[-1]["price"])


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
    df = transactions
    mask = (
        (df["fcp"] == fcp)
        & (df["ticker"] == ticker)
        & (pd.to_datetime(df["date"]) <= pd.Timestamp(cutoff))
    )
    sub = df.loc[mask]
    if sub.empty:
        return 0.0
    achat = sub.loc[sub["sens"] == "ACHAT", "quantite"].sum()
    vente = sub.loc[sub["sens"] == "VENTE", "quantite"].sum()
    return float(achat - vente)


def _period_trades(transactions: pd.DataFrame, fcp: str, ticker: str,
                   prev_date: pd.Timestamp,
                   as_of_date: pd.Timestamp) -> pd.DataFrame:
    """Trades on this ticker in the window `(prev_date, as_of_date]`.

    Lower bound exclusive (a trade on prev_date is in the held bucket);
    upper bound inclusive.
    """
    if transactions.empty:
        return transactions.iloc[0:0]
    df = transactions
    d = pd.to_datetime(df["date"])
    mask = (
        (df["fcp"] == fcp)
        & (df["ticker"] == ticker)
        & (d > pd.Timestamp(prev_date))
        & (d <= pd.Timestamp(as_of_date))
    )
    return df.loc[mask, ["sens", "quantite", "prix", "frais"]].copy()


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

    # Pre-filter transactions for this FCP to speed up subsequent ticker queries.
    tx_fcp = transactions[transactions["fcp"] == fcp].copy() if not transactions.empty \
             else transactions.iloc[0:0]

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
        df = transactions.copy()
        df["date"] = pd.to_datetime(df["date"])
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
            cible_pct = None
            cible_fcfa = None
        else:
            r = t_row.iloc[0]
            cible_pct = float(r["weight_pct"]) / 100.0 if pd.notna(r.get("weight_pct")) else None
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
    df["_sort"] = df["sens"].map(order)
    df = (df.sort_values(["_sort", "ecart_fcfa"],
                         ascending=[True, True],
                         key=lambda col: col.abs() if col.name == "ecart_fcfa" else col)
          .drop(columns=["_sort"])
          .reset_index(drop=True))
    return df
