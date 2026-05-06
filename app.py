"""SVM Outil — Streamlit app.

Replaces the legacy Excel "Outil_SVM.xlsx" workflow with:
  • A live dashboard for any of the 22 FCPs
  • Form-based transaction entry and editing
  • One-click BRVM price refresh (with manual CSV fallback)
  • Historical price archive identical in shape to the Excel "Cours" sheet

Run:
    streamlit run app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import db
from auth import require_login
from auto_sync import run_daily_auto_sync_if_needed, render_sync_status_sidebar
from fcp_calendar import is_weekly_fcp, weekday_label, WEEKLY_FCPS
from portfolio import (
    build_dashboard,
    compute_exposures,
    compute_recap,
    compute_tracking,
    concentration_metrics,
    previous_business_date,
)
from sectors import sector_of, all_sectors, annotate as annotate_sectors

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SVM — Outil de gestion FCP",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Auth gate (no-op if no password configured in secrets)
# ---------------------------------------------------------------------------
require_login()


# ---------------------------------------------------------------------------
# Dune Gold — custom CSS theme injection
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #2C1F0F !important;
}
[data-testid="stSidebar"] > div:first-child {
    color: #D4B896 !important;
}
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stRadio span {
    color: #D4B896 !important;
    font-size: 0.9rem;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    color: #BFA98A !important;
    font-size: 0.8rem;
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #EFA823 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #4A3010 !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
    background-color: #3A2810 !important;
    border-color: #5C3D18 !important;
    color: #FAC775 !important;
}
[data-testid="stSidebar"] label {
    color: #BFA98A !important;
}
[data-testid="stSidebar"] [data-testid="stDateInput"] input {
    background-color: #3A2810 !important;
    border-color: #5C3D18 !important;
    color: #FAC775 !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] * {
    color: #FAC775 !important;
    background-color: #3A2810 !important;
}
[data-testid="stSidebar"] [data-baseweb="radio"] span {
    color: #D4B896 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
    color: #8A6E48 !important;
}

/* ── Top bar / header ── */
[data-testid="stHeader"] {
    background-color: #FBF8F3 !important;
    border-bottom: 1px solid #E8D9C0;
}

/* ── Page background ── */
.stApp {
    background-color: #FBF8F3 !important;
}
.main .block-container {
    background-color: #FBF8F3 !important;
}

/* ── Main content text — always dark on light bg ── */
.main p, .main span, .main div,
[data-testid="stMainBlockContainer"] p,
[data-testid="stMainBlockContainer"] span {
    color: #2C1F0F;
}

/* ── Dataframe text — force dark, overrides any inherited color ── */
[data-testid="stDataFrame"] * {
    color: #2C1F0F !important;
}
.dvn-scroller {
    background-color: #FFFFFF !important;
}
[data-testid="stDataFrame"] canvas {
    color: #2C1F0F !important;
}

/* ── st.table (HTML table) ── */
[data-testid="stTable"] table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    color: #2C1F0F !important;
    background-color: #FFFFFF;
    border: 0.5px solid #E8D9C0;
    border-radius: 8px;
    overflow: hidden;
}
[data-testid="stTable"] thead tr {
    background-color: #F2EBE0 !important;
    border-bottom: 1px solid #E8D9C0;
}
[data-testid="stTable"] thead th {
    color: #633806 !important;
    font-weight: 500 !important;
    padding: 8px 12px !important;
    font-size: 0.8rem !important;
    text-align: left;
}
[data-testid="stTable"] tbody tr:nth-child(even) {
    background-color: #FBF8F3 !important;
}
[data-testid="stTable"] tbody tr:hover {
    background-color: #FAEEDA !important;
}
[data-testid="stTable"] tbody td {
    color: #2C1F0F !important;
    padding: 6px 12px !important;
    font-size: 0.83rem !important;
    border-bottom: 0.5px solid #F0E8DA;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background-color: #FFFFFF;
    border: 0.5px solid #E8D9C0;
    border-left: 3px solid #EF9F27;
    border-radius: 8px;
    padding: 0.75rem 1rem !important;
}
[data-testid="stMetricLabel"] {
    color: #8A6E48 !important;
    font-size: 0.78rem !important;
}
[data-testid="stMetricValue"] {
    color: #2C1F0F !important;
    font-size: 1.2rem !important;
    font-weight: 500 !important;
}
[data-testid="stMetricDelta"] {
    font-size: 0.78rem !important;
}

/* ── Buttons ── */
.stButton > button[kind="primary"],
.stButton > button {
    background-color: #EF9F27 !important;
    color: #2C1F0F !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
}
.stButton > button:hover {
    background-color: #D98A1A !important;
    color: #2C1F0F !important;
}
.stDownloadButton > button {
    background-color: #FFFFFF !important;
    color: #633806 !important;
    border: 1px solid #E8D9C0 !important;
    border-radius: 6px !important;
}
.stDownloadButton > button:hover {
    background-color: #FAEEDA !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 0.5px solid #E8D9C0 !important;
    border-radius: 8px !important;
    background-color: #FFFFFF !important;
}
[data-testid="stExpander"] summary {
    color: #633806 !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
}
[data-testid="stExpander"] summary span {
    color: #633806 !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid #E8D9C0 !important;
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    color: #8A6E48 !important;
    border-radius: 6px 6px 0 0 !important;
}
.stTabs [aria-selected="true"] {
    color: #633806 !important;
    border-bottom: 2px solid #EF9F27 !important;
    font-weight: 500 !important;
}

/* ── Info / success / warning boxes ── */
[data-testid="stInfo"] {
    background-color: #FAEEDA !important;
    border-left-color: #EF9F27 !important;
    color: #633806 !important;
}
[data-testid="stSuccess"] {
    background-color: #E8F5EE !important;
    border-left-color: #1D9E75 !important;
}
[data-testid="stWarning"] {
    background-color: #FAEEDA !important;
    border-left-color: #BA7517 !important;
}

/* ── Select boxes & inputs (main content) ── */
.main [data-testid="stSelectbox"] > div,
.main [data-testid="stMultiSelect"] > div {
    border-color: #E8D9C0 !important;
    background-color: #FFFFFF !important;
}
.main [data-testid="stTextInput"] input,
.main [data-testid="stNumberInput"] input {
    border-color: #E8D9C0 !important;
    background-color: #FFFFFF !important;
    color: #2C1F0F !important;
}
.main [data-testid="stTextInput"] input:focus,
.main [data-testid="stNumberInput"] input:focus {
    border-color: #EF9F27 !important;
    box-shadow: 0 0 0 2px rgba(239,159,39,0.2) !important;
}

/* ── Dividers ── */
.main hr {
    border-color: #E8D9C0 !important;
}

/* ── Progress bar ── */
[data-testid="stProgress"] > div > div {
    background-color: #EF9F27 !important;
}

/* ── Headings in main content ── */
.main h1, .main h2, .main h3 {
    color: #2C1F0F !important;
}
.main h1 { border-bottom: 2px solid #EF9F27; padding-bottom: 0.3rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def _bootstrap() -> None:
    """Ensure schema exists. Does NOT seed data — use seed_postgres.py for that."""
    db.init_db()


_bootstrap()


# ---------------------------------------------------------------------------
# Daily auto-sync — runs once per calendar day on first app open
# ---------------------------------------------------------------------------
# This runs BEFORE the cache layer is queried, so any data refreshed here
# is visible immediately in the rest of the app.
_did_sync = run_daily_auto_sync_if_needed()


# ---------------------------------------------------------------------------
# Cached data accessors — minimize Postgres round-trips
# ---------------------------------------------------------------------------
# These wrap the db.* readers with a 5-minute TTL. After any write
# (transactions, prices, dividends), call _clear_data_cache() to refresh.

@st.cache_data(ttl=300, show_spinner=False)
def _cached_transactions() -> pd.DataFrame:
    return db.get_all_transactions_for_compute()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_prices() -> pd.DataFrame:
    return db.get_prices()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_fcps() -> list[str]:
    return db.get_fcps()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_dividends_all(fcps_tuple: tuple[str, ...]) -> dict[str, dict[str, float]]:
    return {f: db.get_dividends(f) for f in fcps_tuple}


@st.cache_data(ttl=300, show_spinner=False)
def _cached_known_tickers() -> list[str]:
    return db.get_known_tickers()


def _clear_data_cache() -> None:
    """Invalidate all cached reads. Call after any write."""
    _cached_transactions.clear()
    _cached_prices.clear()
    _cached_fcps.clear()
    _cached_dividends_all.clear()
    _cached_known_tickers.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_xof(v: float, signed: bool = False) -> str:
    if v is None or pd.isna(v):
        return "-"
    if abs(v) < 0.5:
        return "-"
    sign = "+" if signed and v > 0 else ""
    return f"{sign}{v:,.0f} FCFA".replace(",", " ")


def fmt_pct(v: float, signed: bool = False) -> str:
    if v is None or pd.isna(v):
        return "-"
    if signed:
        return f"{v*100:+,.2f}%".replace(",", " ")
    return f"{v*100:,.2f}%".replace(",", " ")


def render_table(
    df: pd.DataFrame,
    height: int | None = None,
    color_cols: list[str] | None = None,
) -> None:
    """Render a DataFrame as a styled HTML table — bypasses Canvas/WebGL.

    Auto-formats raw numbers with space-separated thousands.
    color_cols: columns whose values (starting with + or -) get green/red.
    """
    color_cols = set(color_cols or [])

    # Auto-format any remaining raw numeric columns
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].map(
                lambda v: "-" if pd.isna(v)
                else f"{v:,.0f} FCFA".replace(",", " ")
            )
        elif pd.api.types.is_integer_dtype(df[col]):
            df[col] = df[col].map(
                lambda v: "-" if pd.isna(v)
                else f"{v:,}".replace(",", " ")
            )
        else:
            df[col] = df[col].fillna("-").astype(str)

    def _td(col: str, val: str) -> str:
        s = str(val).strip()
        td_base = "padding:6px 11px;white-space:nowrap;"
        if col not in color_cols:
            return f"<td style='{td_base}'>{s}</td>"
        if s.startswith("+") or s.startswith("▲"):
            return (f"<td style='{td_base}color:#1A6B3E;font-weight:500;'>"
                    f"▲ {s.lstrip('+').lstrip('▲').strip()}</td>")
        elif s.startswith("-") or s.startswith("▼"):
            return (f"<td style='{td_base}color:#B53A2F;font-weight:500;'>"
                    f"▼ {s.lstrip('-').lstrip('▼').strip()}</td>")
        else:
            return f"<td style='{td_base}color:#8A6E48;'>{s}</td>"

    th = (
        "style='background:#F2EBE0;color:#633806;font-weight:500;"
        "padding:7px 11px;font-size:0.79rem;text-align:left;"
        "border-bottom:1px solid #E8D9C0;white-space:nowrap;'"
    )
    header = "".join(f"<th {th}>{c}</th>" for c in df.columns)

    rows_html = ""
    for i, (_, row) in enumerate(df.iterrows()):
        bg = "#FFFFFF" if i % 2 == 0 else "#FBF8F3"
        cells = "".join(_td(col, str(row[col])) for col in df.columns)
        rows_html += (
            f"<tr style='background:{bg};"
            f"border-bottom:0.5px solid #F0E8DA;'>{cells}</tr>"
        )

    scroll = f"max-height:{height}px;overflow-y:auto;" if height else ""
    st.markdown(
        f"<div style='overflow-x:auto;{scroll}border:0.5px solid #E8D9C0;"
        f"border-radius:8px;background:#FFFFFF;margin-bottom:0.5rem;'>"
        f"<table style='width:100%;border-collapse:collapse;"
        f"font-size:0.82rem;color:#2C1F0F;'>"
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        f"</table></div>",
        unsafe_allow_html=True,
    )

def render_table(
    df: pd.DataFrame,
    height: int | None = None,
    color_cols: list[str] | None = None,
    color_source: dict[str, str] | None = None,
) -> None:
    """Render a DataFrame as a styled HTML table via st.markdown.

    This bypasses Streamlit's Canvas/WebGL renderer (st.dataframe) which
    ignores CSS color rules in custom themes.

    Args:
        df: DataFrame with already-formatted string values for display.
        height: optional max-height in px (adds vertical scroll).
        color_cols: list of column names to apply green/red coloring to.
            The cell value must start with '+' (green) or '-' or '▼' (red).
        color_source: dict mapping display col name → raw numeric col name
            in the original data. Not needed when values start with +/-.
    """
    color_cols = color_cols or []

    def _td(col: str, val: str) -> str:
        if col not in color_cols:
            return f"<td>{val}</td>"
        s = str(val).strip()
        if s.startswith("+") or s.startswith("▲"):
            style = "color:#1A6B3E;font-weight:500;"
        elif s.startswith("-") or s.startswith("▼"):
            style = "color:#B53A2F;font-weight:500;"
        else:
            style = "color:#8A6E48;"
        return f"<td style='{style}'>{val}</td>"

    header = "".join(
        f"<th style='background:#F2EBE0;color:#633806;font-weight:500;"
        f"padding:7px 11px;font-size:0.79rem;text-align:left;"
        f"border-bottom:1px solid #E8D9C0;white-space:nowrap;'>{c}</th>"
        for c in df.columns
    )

    rows_html = ""
    for i, (_, row) in enumerate(df.iterrows()):
        bg = "#FFFFFF" if i % 2 == 0 else "#FBF8F3"
        cells = "".join(_td(col, row[col]) for col in df.columns)
        rows_html += (
            f"<tr style='background:{bg};border-bottom:"
            f"0.5px solid #F0E8DA;'>{cells}</tr>"
        )

    scroll_style = (
        f"max-height:{height}px;overflow-y:auto;" if height else ""
    )

    html = (
        f"<div style='overflow-x:auto;{scroll_style}border:0.5px solid "
        f"#E8D9C0;border-radius:8px;background:#FFFFFF;margin-bottom:0.5rem;'>"
        f"<table style='width:100%;border-collapse:collapse;font-size:0.82rem;"
        f"color:#2C1F0F;'>"
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        f"</table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar - FCP selection + global controls
# ---------------------------------------------------------------------------
fcps = _cached_fcps()

with st.sidebar:
    st.markdown(
        "<h2 style='color:#EFA823;font-size:1.2rem;margin-bottom:2px;'>"
        "SVM · BRVM</h2>"
        "<p style='color:#8A6E48;font-size:0.75rem;margin-bottom:1rem;'>"
        "Gestion FCP — CGF GESTION</p>",
        unsafe_allow_html=True,
    )

    if not fcps:
        st.error("Aucun FCP en base. Initialisez les données dans Paramètres.")
        st.stop()

    fcp = st.selectbox("FCP actif", fcps, key="fcp_select")
    as_of = st.date_input("Date de valorisation", value=date.today())
    st.divider()

    page = st.radio(
        "Navigation",
        ["📈 Tableau de bord", "📊 Récap variations", "🎯 Expositions",
         "📋 Suivi des cibles", "💼 Transactions", "🌐 Cours BRVM",
         "📚 Historique cours", "⚙️ Paramètres"],
        label_visibility="collapsed",
    )

# Sync status footer (separate from the sidebar `with` block above so it's
# always rendered, including after the first auto-sync of the day)
render_sync_status_sidebar()


# ---------------------------------------------------------------------------
# Page: Dashboard
# ---------------------------------------------------------------------------
if page == "📈 Tableau de bord":
    st.header(f"{fcp}")
    as_of_ts = pd.Timestamp(as_of)

    tx_all = _cached_transactions()
    prices = _cached_prices()
    divs = _cached_dividends_all(tuple(fcps)).get(fcp, {})

    rows, totals = build_dashboard(tx_all, prices, fcp, as_of_ts, divs)
    prev_date = totals["prev_date"]

    if is_weekly_fcp(fcp):
        wd = weekday_label(WEEKLY_FCPS[fcp])
        st.caption(
            f"Valorisation au **{as_of_ts.strftime('%d/%m/%Y')}** — "
            f"FCP à valorisation hebdomadaire ({wd}) — "
            f"Comparaison avec **{prev_date.strftime('%d/%m/%Y')}**"
        )
    else:
        st.caption(
            f"Valorisation au **{as_of_ts.strftime('%d/%m/%Y')}** — "
            f"Comparaison avec **{prev_date.strftime('%d/%m/%Y')}**"
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Coût total", fmt_xof(totals["cout_total"]))
    c2.metric("Valorisation", fmt_xof(totals["valorisation"]))
    c3.metric(
        "+/- value latente",
        fmt_xof(totals["diff_estim"], signed=True),
        delta=fmt_pct(
            totals["diff_estim"] / totals["cout_total"] if totals["cout_total"] else 0
        ),
    )
    c4.metric(
        "Variation journalière",
        fmt_xof(totals["variation_jour"], signed=True),
        delta=fmt_pct(totals["variation_pct"]),
    )

    st.divider()

    if rows.empty:
        st.info("Aucune position pour ce FCP à cette date.")
    else:
        rows_active = rows[rows["quantite"] > 0]
        rows_zero = rows[rows["quantite"] == 0]

        st.subheader("Positions actives")
        render_table(
            pd.DataFrame({
                "Symbole": rows_active["ticker"],
                "Quantité": rows_active["quantite"].map(lambda v: f"{v:,.0f}".replace(",", " ")),
                "CMP": rows_active["cmp"].map(lambda v: f"{v:,.2f}".replace(",", " ")),
                "Coût total": rows_active["cout_total"].map(fmt_xof),
                "Valorisation": rows_active["valorisation"].map(fmt_xof),
                "+/- estim.": rows_active["diff_estim"].map(lambda v: fmt_xof(v, signed=True)),
                "Poids": rows_active["poids"].map(fmt_pct),
                "Cours veille": rows_active["prev_close"].map(lambda v: f"{v:,.0f}".replace(",", " ") if v else "-"),
                "Cours jour": rows_active["close"].map(lambda v: f"{v:,.0f}".replace(",", " ") if v else "-"),
                "Variation": rows_active["variation"].map(lambda v: fmt_xof(v, signed=True)),
                "+/- value jour": rows_active["plus_moins_value"].map(lambda v: fmt_xof(v, signed=True)),
            }),
            color_cols=["+/- estim.", "Variation", "+/- value jour"],
        )

        if not rows_zero.empty:
            with st.expander(f"Lignes soldées ({len(rows_zero)})"):
                render_table(
                    pd.DataFrame({
                        "Symbole": rows_zero["ticker"],
                        "Quantité": rows_zero["quantite"].map(lambda v: f"{v:,.0f}".replace(",", " ")),
                        "CMP": rows_zero["cmp"].map(lambda v: f"{v:,.2f}".replace(",", " ")),
                        "Coût total": rows_zero["cout_total"].map(fmt_xof),
                        "Valorisation": rows_zero["valorisation"].map(fmt_xof),
                        "+/- estim.": rows_zero["diff_estim"].map(lambda v: fmt_xof(v, signed=True)),
                        "Poids": rows_zero["poids"].map(fmt_pct),
                        "Cours veille": rows_zero["prev_close"].map(lambda v: f"{v:,.0f}".replace(",", " ") if v else "-"),
                        "Cours jour": rows_zero["close"].map(lambda v: f"{v:,.0f}".replace(",", " ") if v else "-"),
                        "Variation": rows_zero["variation"].map(lambda v: fmt_xof(v, signed=True)),
                        "+/- value jour": rows_zero["plus_moins_value"].map(lambda v: fmt_xof(v, signed=True)),
                    }),
                    color_cols=["+/- estim.", "Variation", "+/- value jour"],
                )

        st.divider()
        col_a, col_b = st.columns([2, 3])
        with col_a:
            st.subheader("Répartition par titre")
            chart_data = (
                rows_active.set_index("ticker")["valorisation"]
                .sort_values(ascending=False)
            )
            st.bar_chart(chart_data)

        with col_b:
            st.subheader("Top mouvements du jour")
            _top_raw = (
                rows_active
                .assign(_abs=rows_active["plus_moins_value"].abs())
                .nlargest(10, "_abs")
            )
            _top_mov = pd.DataFrame({
                "Symbole": _top_raw["ticker"].values,
                "+/- value jour": _top_raw["plus_moins_value"].map(
                    lambda v: fmt_xof(v, signed=True)
                ).values,
                "Variation unitaire": _top_raw["variation"].map(
                    lambda v: fmt_xof(v, signed=True)
                ).values,
            })
            render_table(
                _top_mov,
                color_cols=["+/- value jour", "Variation unitaire"],
            )

        st.download_button(
            "⬇️ Exporter le tableau (CSV)",
            data=rows.to_csv(index=False).encode("utf-8"),
            file_name=f"{fcp.replace(' ', '_')}_{as_of_ts.date()}.csv",
            mime="text/csv",
        )


# ---------------------------------------------------------------------------
# Page: Récap variations
# ---------------------------------------------------------------------------
elif page == "📊 Récap variations":
    st.header("Récap variations — tous les FCPs")
    as_of_ts = pd.Timestamp(as_of)
    st.caption(
        f"Variations à la date du **{as_of_ts.strftime('%d/%m/%Y')}** — "
        f"YTD calculé depuis le 01/01/{as_of_ts.year}"
    )

    with st.spinner("Calcul des variations pour les 24 FCPs…"):
        tx_all = _cached_transactions()
        prices = _cached_prices()
        all_fcps = _cached_fcps()
        divs_by_fcp = _cached_dividends_all(tuple(all_fcps))
        recap = compute_recap(tx_all, prices, all_fcps, as_of_ts, divs_by_fcp)

    if recap.empty:
        st.info("Aucune donnée à afficher.")
    else:
        # Aggregate header KPIs
        col1, col2, col3, col4 = st.columns(4)
        total_valo_all = float(recap["Valorisation"].sum())
        total_var_jour = float(recap["Var. jour"].sum())
        total_var_ytd = float(recap["Var. YTD"].sum())
        col1.metric("Valorisation totale", fmt_xof(total_valo_all))
        col2.metric("Variation jour cumulée", fmt_xof(total_var_jour, signed=True))
        col3.metric("Variation YTD cumulée", fmt_xof(total_var_ytd, signed=True))
        col4.metric("FCPs actifs", f"{(recap['Valorisation']>0).sum()} / {len(recap)}")

        st.divider()

        display = recap.copy()
        display["Valorisation"] = display["Valorisation"].map(fmt_xof)
        display["Var. jour"] = display["Var. jour"].map(lambda v: fmt_xof(v, signed=True))
        display["Var. jour %"] = display["Var. jour %"].map(fmt_pct)
        display["Valo début année"] = display["Valo début année"].map(fmt_xof)
        display["Var. YTD"] = display["Var. YTD"].map(lambda v: fmt_xof(v, signed=True))
        display["Var. YTD %"] = display["Var. YTD %"].map(fmt_pct)

        render_table(display, height=None,
                     color_cols=["Var. jour", "Var. jour %",
                                 "Var. YTD", "Var. YTD %"])

        st.download_button(
            "⬇️ Exporter le récap (CSV)",
            data=recap.to_csv(index=False).encode("utf-8"),
            file_name=f"recap_variations_{as_of_ts.date()}.csv",
            mime="text/csv",
        )

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Top variations du jour")
            top_day = (
                recap.assign(abs_=recap["Var. jour"].abs())
                .nlargest(10, "abs_")[["FCP", "Var. jour", "Var. jour %"]]
            )
            top_day["Var. jour"] = top_day["Var. jour"].map(
                lambda v: fmt_xof(v, signed=True)
            )
            top_day["Var. jour %"] = top_day["Var. jour %"].map(fmt_pct)
            render_table(top_day, height=None,
                         color_cols=["Var. jour", "Var. jour %"])
        with col_b:
            st.subheader("Top variations YTD")
            top_ytd = (
                recap.assign(abs_=recap["Var. YTD"].abs())
                .nlargest(10, "abs_")[["FCP", "Var. YTD", "Var. YTD %"]]
            )
            top_ytd["Var. YTD"] = top_ytd["Var. YTD"].map(
                lambda v: fmt_xof(v, signed=True)
            )
            top_ytd["Var. YTD %"] = top_ytd["Var. YTD %"].map(fmt_pct)
            render_table(top_ytd, height=None,
                         color_cols=["Var. YTD", "Var. YTD %"])


# ---------------------------------------------------------------------------
# Page: Expositions
# ---------------------------------------------------------------------------
elif page == "🎯 Expositions":
    st.header("Expositions cross-portefeuille")
    as_of_ts = pd.Timestamp(as_of)

    # ── Filtre FCP ──────────────────────────────────────────────────────────
    tx_all = _cached_transactions()
    prices = _cached_prices()
    all_fcps = _cached_fcps()
    divs_by_fcp = _cached_dividends_all(tuple(all_fcps))

    filtre_options = ["Tous les FCPs"] + all_fcps
    filtre_fcp = st.selectbox(
        "Périmètre d'analyse",
        options=filtre_options,
        index=0,
        key="exp_filtre_fcp",
    )

    # Compute exposures for the selected scope
    if filtre_fcp == "Tous les FCPs":
        fcps_scope = all_fcps
        scope_label = "tous les FCPs"
    else:
        fcps_scope = [filtre_fcp]
        scope_label = filtre_fcp

    st.caption(
        f"Photographie des positions au **{as_of_ts.strftime('%d/%m/%Y')}** — "
        f"périmètre : **{scope_label}**."
    )

    with st.spinner(f"Calcul des expositions — {scope_label}…"):
        divs_scope = {f: divs_by_fcp.get(f, {}) for f in fcps_scope}
        exp = compute_exposures(tx_all, prices, fcps_scope, as_of_ts, divs_scope)

    if exp.empty:
        st.info("Aucune position à afficher pour ce périmètre.")
    else:
        total_global = float(exp["valorisation"].sum())

        # --- KPIs ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Valorisation", fmt_xof(total_global))
        c2.metric("Tickers distincts", f"{exp['ticker'].nunique()}")
        c3.metric(
            "FCPs" if filtre_fcp == "Tous les FCPs" else "FCP",
            f"{exp['fcp'].nunique()}" if filtre_fcp == "Tous les FCPs" else filtre_fcp,
        )
        c4.metric("Lignes totales", f"{len(exp)}")

        st.divider()

        # --- Section 1: Top tickers ---
        st.subheader(
            "Top expositions — tous FCPs confondus"
            if filtre_fcp == "Tous les FCPs"
            else f"Top expositions — {filtre_fcp}"
        )

        global_by_ticker = (
            exp.groupby("ticker")["valorisation"].sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        global_by_ticker["Poids"] = global_by_ticker["valorisation"] / total_global

        col_a, col_b = st.columns([3, 2])
        with col_a:
            st.caption("Top 15 — barres en FCFA")
            top15 = global_by_ticker.head(15).set_index("ticker")["valorisation"]
            st.bar_chart(top15)

        with col_b:
            st.caption("Concentration top 10 vs reste")
            top10 = global_by_ticker.head(10)
            others_val = total_global - top10["valorisation"].sum()
            pie_df = pd.concat([
                top10[["ticker", "valorisation"]],
                pd.DataFrame([{"ticker": "Autres", "valorisation": others_val}]),
            ]).set_index("ticker")
            st.bar_chart(pie_df)

        # Full ranked table (collapsed by default)
        with st.expander(f"Voir tous les tickers ({len(global_by_ticker)})"):
            display_global = global_by_ticker.rename(columns={
                "ticker": "Symbole",
                "valorisation": "Valorisation",
            }).copy()
            display_global["Valorisation"] = display_global["Valorisation"].map(fmt_xof)
            display_global["Poids"] = display_global["Poids"].map(fmt_pct)
            render_table(display_global, height=None)

            st.download_button(
                "⬇️ Exporter (CSV)",
                data=global_by_ticker.to_csv(index=False).encode("utf-8"),
                file_name=f"expositions_globales_{as_of_ts.date()}.csv",
                mime="text/csv",
                key="dl_global",
            )

        st.divider()

        # --- Section 1bis: Répartition sectorielle ---
        st.subheader("Répartition sectorielle")

        exp_with_sector = annotate_sectors(exp)
        sector_global = (
            exp_with_sector.groupby("secteur")["valorisation"].sum()
            .sort_values(ascending=False)
        )
        sector_global_pct = sector_global / sector_global.sum()

        col_s1, col_s2 = st.columns([3, 2])
        with col_s1:
            st.caption("Exposition par secteur (FCFA)")
            st.bar_chart(sector_global)
        with col_s2:
            st.caption("Indicateurs sectoriels")
            top_sector = sector_global.index[0]
            top_sector_pct = sector_global_pct.iloc[0]
            n_sectors = len(sector_global)
            st.metric("Secteur dominant", top_sector)
            st.metric("Poids du secteur dominant", fmt_pct(top_sector_pct))
            st.metric("Nb secteurs représentés", f"{n_sectors}")

        # Detailed sector table with weights
        sector_table = pd.DataFrame({
            "Secteur": sector_global.index,
            "Valorisation": sector_global.values,
            "Poids global": sector_global_pct.values,
            "Nb tickers": [
                exp_with_sector[exp_with_sector["secteur"] == s]["ticker"].nunique()
                for s in sector_global.index
            ],
        })
        display_sector = sector_table.copy()
        display_sector["Valorisation"] = display_sector["Valorisation"].map(fmt_xof)
        display_sector["Poids global"] = display_sector["Poids global"].map(fmt_pct)
        render_table(display_sector, height=None)

        # Sector × FCP matrix
        with st.expander("Voir la matrice secteurs × FCPs"):
            sec_view_mode = st.radio(
                "Mode d'affichage",
                ["Montant (FCFA)", "Poids dans le FCP", "Poids global"],
                horizontal=True,
                key="exp_sec_view_mode",
            )

            sector_fcp = exp_with_sector.pivot_table(
                index="secteur", columns="fcp", values="valorisation",
                aggfunc="sum", fill_value=0,
            )
            sector_fcp = sector_fcp.loc[sector_global.index]  # keep order

            if sec_view_mode == "Montant (FCFA)":
                m = sector_fcp.copy()
                m["TOTAL"] = m.sum(axis=1)
                total_row = m.sum(axis=0)
                total_row.name = "TOTAL"
                m = pd.concat([m, total_row.to_frame().T])
                formatted = m.apply(lambda col: col.map(
                    lambda v: f"{v:,.0f}".replace(",", " ") if v > 0 else "-"
                ))
                export_sec_df = m
            elif sec_view_mode == "Poids dans le FCP":
                fcp_totals = sector_fcp.sum(axis=0)
                m = sector_fcp.div(fcp_totals, axis=1).fillna(0)
                formatted = m.apply(lambda col: col.map(
                    lambda v: f"{v*100:.1f}%" if v > 0 else "-"
                ))
                export_sec_df = m
            else:  # Poids global
                m = sector_fcp / total_global
                m["TOTAL"] = m.sum(axis=1)
                formatted = m.apply(lambda col: col.map(
                    lambda v: f"{v*100:.2f}%" if v > 0 else "-"
                ))
                export_sec_df = m

            render_table(formatted, height=None)

            st.download_button(
                "⬇️ Exporter la matrice sectorielle (CSV)",
                data=export_sec_df.to_csv().encode("utf-8"),
                file_name=f"matrice_secteurs_{as_of_ts.date()}.csv",
                mime="text/csv",
                key="dl_sec_matrix",
            )

        st.divider()

        # --- Section 2: Matrice ticker × FCP ---
        st.subheader(
            "Matrice détaillée tickers × FCPs"
            if filtre_fcp == "Tous les FCPs"
            else f"Détail des positions — {filtre_fcp}"
        )

        if filtre_fcp != "Tous les FCPs":
            # Single FCP view: simple table, no pivot needed
            view_mode_single = st.radio(
                "Mode d'affichage",
                ["Montant (FCFA)", "Poids dans le FCP"],
                horizontal=True,
                key="exp_view_mode",
            )
            single = global_by_ticker.copy().rename(
                columns={"ticker": "Ticker", "valorisation": "Valorisation"}
            )
            if view_mode_single == "Montant (FCFA)":
                single["Valorisation"] = single["Valorisation"].map(fmt_xof)
                single["Poids"] = single["Poids"].map(fmt_pct)
                render_table(single, height=500)
                export_df = global_by_ticker
            else:
                single["Valorisation"] = single["Valorisation"].map(fmt_xof)
                single["Poids"] = single["Poids"].map(fmt_pct)
                render_table(single, height=500)
                export_df = global_by_ticker
            st.download_button(
                "⬇️ Exporter (CSV)",
                data=export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"positions_{filtre_fcp.replace(' ','_')}_{as_of_ts.date()}.csv",
                mime="text/csv",
                key="dl_matrix",
            )

        else:
            # All FCPs: full pivot matrix
            view_mode = st.radio(
                "Mode d'affichage",
                ["Montant (FCFA)", "Poids dans le FCP", "Poids global"],
                horizontal=True,
                key="exp_view_mode",
            )

            matrix_val = exp.pivot_table(
                index="ticker", columns="fcp", values="valorisation",
                aggfunc="sum", fill_value=0,
            )
            matrix_val = matrix_val.loc[global_by_ticker["ticker"].tolist()]

            if view_mode == "Montant (FCFA)":
                matrix_display = matrix_val.copy()
                matrix_display["TOTAL"] = matrix_display.sum(axis=1)
                total_row = matrix_display.sum(axis=0)
                total_row.name = "TOTAL"
                matrix_display = pd.concat([matrix_display, total_row.to_frame().T])
                formatted = matrix_display.apply(lambda col: col.map(
                    lambda v: f"{v:,.0f}".replace(",", " ") if v > 0 else "-"
                ))
                render_table(formatted, height=600)
                export_df = matrix_display

            elif view_mode == "Poids dans le FCP":
                fcp_totals = matrix_val.sum(axis=0)
                matrix_pct = matrix_val.div(fcp_totals, axis=1).fillna(0)
                formatted = matrix_pct.apply(lambda col: col.map(
                    lambda v: f"{v*100:.1f}%" if v > 0 else "-"
                ))
                render_table(formatted, height=600)
                export_df = matrix_pct

            else:  # Poids global
                matrix_pct = matrix_val / total_global
                matrix_pct["TOTAL"] = matrix_pct.sum(axis=1)
                formatted = matrix_pct.apply(lambda col: col.map(
                    lambda v: f"{v*100:.2f}%" if v > 0 else "-"
                ))
                render_table(formatted, height=600)
                export_df = matrix_pct

            st.download_button(
                "⬇️ Exporter la matrice (CSV)",
                data=export_df.to_csv().encode("utf-8"),
                file_name=f"matrice_expositions_{as_of_ts.date()}.csv",
                mime="text/csv",
                key="dl_matrix",
            )

        st.divider()

        # --- Section 3: Concentration par FCP ---
        st.subheader(
            "Concentration par FCP"
            if filtre_fcp == "Tous les FCPs"
            else f"Concentration — {filtre_fcp}"
        )
        st.caption(
            "Poids cumulé des plus grosses positions. "
            "Permet d'identifier les portefeuilles les plus concentrés."
        )

        conc = concentration_metrics(exp)
        if not conc.empty:
            display_conc = conc.copy()
            display_conc["Valorisation"] = display_conc["Valorisation"].map(fmt_xof)
            for c in ["Top 1 %", "Top 3 %", "Top 5 %", "Top 10 %"]:
                display_conc[c] = display_conc[c].map(fmt_pct)
            render_table(display_conc, height=None)

            st.download_button(
                "⬇️ Exporter (CSV)",
                data=conc.to_csv(index=False).encode("utf-8"),
                file_name=f"concentration_{as_of_ts.date()}.csv",
                mime="text/csv",
                key="dl_conc",
            )


# ---------------------------------------------------------------------------
# Page: Suivi des cibles
# ---------------------------------------------------------------------------
elif page == "📋 Suivi des cibles":
    st.header(f"Suivi des cibles — {fcp}")
    as_of_ts = pd.Timestamp(as_of)
    st.caption(
        f"Comparaison positions actuelles vs pondérations cibles "
        f"au **{as_of_ts.strftime('%d/%m/%Y')}**."
    )

    tx_all = _cached_transactions()
    prices = _cached_prices()
    divs = _cached_dividends_all(tuple(fcps)).get(fcp, {})

    # ── Import de cibles ────────────────────────────────────────────────────
    with st.expander("📥 Importer les cibles (CSV ou Excel)", expanded=False):

        # Template download buttons
        st.caption("**Formats acceptés** — télécharge un modèle vide :")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            template_std = "ticker,weight_pct,amount_fcfa\nBOAC,15.0,\nSNTS,12.5,\nETIT,,500000000\n"
            st.download_button(
                "📄 Modèle standard (ticker / weight_pct / amount_fcfa)",
                data=template_std.encode(),
                file_name="modele_cibles_standard.csv",
                mime="text/csv",
                key="dl_tpl_std",
            )
        with col_t2:
            template_ntw = "name,ticker,weight\nSonatel,SNTS,15.0\nBank of Africa CI,BOAC,12.5\nETI Togo,ETIT,8.0\n"
            st.download_button(
                "📄 Modèle Name/Ticker/Weight",
                data=template_ntw.encode(),
                file_name="modele_cibles_ntw.csv",
                mime="text/csv",
                key="dl_tpl_ntw",
            )

        st.caption(
            "Formats supportés : "
            "**ticker + weight_pct + amount_fcfa** (standard) "
            "ou **name + ticker + weight** (poids en %). "
            "Les colonnes non renseignées peuvent être laissées vides. "
            "L'import écrase toutes les cibles existantes pour ce FCP."
        )

        up = st.file_uploader(
            "Fichier de cibles (.csv ou .xlsx)",
            type=["csv", "xlsx"],
            key="targets_upload",
        )
        if up is not None:
            try:
                if up.name.endswith(".xlsx"):
                    df_up = pd.read_excel(up)
                else:
                    df_up = pd.read_csv(up)

                # Normalize column names
                df_up.columns = [c.strip().lower() for c in df_up.columns]

                # Detect Name/Ticker/Weight format
                if "ticker" not in df_up.columns and "name" in df_up.columns:
                    st.error("Colonne 'ticker' manquante. Vérifiez que votre fichier "
                             "contient bien une colonne 'ticker'.")
                elif "ticker" not in df_up.columns:
                    st.error("Colonne 'ticker' manquante dans le fichier.")
                else:
                    # Handle Name/Ticker/Weight format
                    if "weight" in df_up.columns and "weight_pct" not in df_up.columns:
                        df_up = df_up.rename(columns={"weight": "weight_pct"})
                    if "weight_pct" not in df_up.columns:
                        df_up["weight_pct"] = None
                    if "amount_fcfa" not in df_up.columns:
                        df_up["amount_fcfa"] = None

                    df_up["ticker"] = df_up["ticker"].astype(str).str.strip().str.upper()

                    # Preview
                    preview_cols = [c for c in ["name","ticker","weight_pct","amount_fcfa"]
                                    if c in df_up.columns]
                    st.write(f"**{len(df_up)}** lignes détectées :")
                    preview = df_up[preview_cols].head(10).rename(columns={
                        "name": "Nom", "ticker": "Ticker",
                        "weight_pct": "Poids cible (%)",
                        "amount_fcfa": "Montant cible (FCFA)",
                    })
                    render_table(preview, height=None)

                    if st.button("Confirmer l'import", key="targets_import_confirm"):
                        n = db.replace_targets_for_fcp(fcp, df_up)
                        _clear_data_cache()
                        st.success(f"✅ {n} cibles chargées pour {fcp}.")
                        st.rerun()
            except Exception as e:
                st.error(f"Lecture impossible : {e}")

    # ── Saisie manuelle ─────────────────────────────────────────────────────
    with st.expander("✏️ Saisie / modification manuelle des cibles", expanded=False):
        st.caption(
            "Ajoute ou modifie une cible pour ce FCP. "
            "Renseigne au moins l'une des deux colonnes cibles."
        )

        known_tickers = _cached_known_tickers()
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            m_ticker = st.selectbox(
                "Titre", options=[""] + known_tickers, key="target_ticker"
            )
        with col_t2:
            m_weight = st.number_input(
                "Poids cible (%)", min_value=0.0, max_value=100.0,
                step=0.01, value=0.0, key="target_weight",
            )
        with col_t3:
            m_amount = st.number_input(
                "Montant cible (FCFA)", min_value=0.0, step=1000.0,
                value=0.0, key="target_amount",
            )

        col_save, col_del = st.columns([1, 1])
        with col_save:
            if st.button("💾 Enregistrer", key="target_save"):
                if not m_ticker:
                    st.warning("Sélectionne un ticker.")
                else:
                    db.upsert_target(
                        fcp, m_ticker,
                        m_weight if m_weight > 0 else None,
                        m_amount if m_amount > 0 else None,
                    )
                    _clear_data_cache()
                    st.success(f"✅ Cible enregistrée pour {m_ticker}.")
                    st.rerun()
        with col_del:
            if st.button("🗑️ Supprimer cette cible", key="target_del"):
                if not m_ticker:
                    st.warning("Sélectionne un ticker.")
                else:
                    db.delete_target(fcp, m_ticker)
                    _clear_data_cache()
                    st.success(f"Cible supprimée pour {m_ticker}.")
                    st.rerun()

    st.divider()

    # ── Tableau de suivi ─────────────────────────────────────────────────────
    targets_df = db.get_targets(fcp)

    if targets_df.empty:
        st.info(
            "Aucune cible définie pour ce FCP. "
            "Utilisez les panneaux ci-dessus pour importer ou saisir des cibles."
        )
    else:
        tracking = compute_tracking(
            tx_all, prices, targets_df, fcp, as_of_ts, divs
        )

        if tracking.empty:
            st.info("Aucune position ni cible à afficher.")
        else:
            # KPIs
            n_achat = int((tracking["sens"] == "ACHAT").sum())
            n_vente = int((tracking["sens"] == "VENTE").sum())
            n_ok    = int((tracking["sens"] == "OK").sum())
            total_a_acheter = tracking.loc[
                tracking["sens"] == "ACHAT", "ecart_fcfa"
            ].sum()
            total_a_vendre = tracking.loc[
                tracking["sens"] == "VENTE", "ecart_fcfa"
            ].sum()

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Lignes ACHAT", n_achat)
            c2.metric("Montant à acheter", fmt_xof(total_a_acheter))
            c3.metric("Lignes VENTE", n_vente)
            c4.metric("Montant à vendre", fmt_xof(abs(total_a_vendre)))
            c5.metric("Lignes OK ✓", n_ok)

            st.divider()

            # Color helper
            def _row_color(sens: str) -> str:
                return {"ACHAT": "🟢", "VENTE": "🔴", "OK": "✅", "—": "⚪"}.get(sens, "")

            # Format for display
            display = tracking.copy()
            display[""] = display["sens"].map(
                lambda s: {"ACHAT": "🟢", "VENTE": "🔴", "OK": "✅", "—": "⚪"}.get(s, "")
            )
            display["Cours"] = display["cours"].map(
                lambda v: fmt_xof(v) if pd.notna(v) and v else "—"
            )
            display["Qté actuelle"] = display["quantite_actuelle"].map(
                lambda v: f"{v:,.0f}".replace(",", " ") if v else "—"
            )
            display["Valo actuelle"] = display["valo_actuelle"].map(fmt_xof)
            display["Poids actuel"] = display["poids_actuel"].map(fmt_pct)
            display["Cible %"] = display["cible_pct"].map(
                lambda v: fmt_pct(v) if pd.notna(v) and v is not None else "—"
            )
            display["Cible FCFA"] = display["cible_fcfa"].map(
                lambda v: fmt_xof(v) if pd.notna(v) and v is not None else "—"
            )
            display["Écart FCFA"] = display["ecart_fcfa"].map(
                lambda v: fmt_xof(v, signed=True) if pd.notna(v) and v is not None else "—"
            )
            display["Écart %"] = display["ecart_pct"].map(
                lambda v: fmt_pct(v, signed=True) if pd.notna(v) and v is not None else "—"
            )
            display["Qté écart"] = display["quantite_ecart"].map(
                lambda v: f"{v:+,.0f}".replace(",", " ") if pd.notna(v) and v is not None else "—"
            )
            display["Sens"] = display["sens"]

            cols_show = [
                "", "ticker", "Qté actuelle", "Cours", "Valo actuelle",
                "Poids actuel", "Cible %", "Cible FCFA",
                "Écart FCFA", "Écart %", "Qté écart", "Sens",
            ]
            render_table(
                display[cols_show].rename(columns={"ticker": "Ticker"}),
                height=600,
                color_cols=["Écart FCFA", "Écart %", "Qté écart"],
            )

            # Export
            export_cols = [
                "ticker", "quantite_actuelle", "cours", "valo_actuelle",
                "poids_actuel", "cible_pct", "cible_fcfa",
                "ecart_fcfa", "ecart_pct", "quantite_ecart", "sens",
            ]
            st.download_button(
                "⬇️ Exporter le suivi (CSV)",
                data=tracking[export_cols].to_csv(index=False).encode("utf-8"),
                file_name=f"suivi_cibles_{fcp.replace(' ', '_')}_{as_of_ts.date()}.csv",
                mime="text/csv",
                key="dl_tracking",
            )

            # Cibles enregistrées (raw) en expander
            with st.expander("📋 Cibles enregistrées pour ce FCP"):
                raw_disp = targets_df.copy()
                raw_disp["weight_pct"] = raw_disp["weight_pct"].map(
                    lambda v: f"{v:.2f}%" if pd.notna(v) else "—"
                )
                raw_disp["amount_fcfa"] = raw_disp["amount_fcfa"].map(
                    lambda v: fmt_xof(v) if pd.notna(v) else "—"
                )
                render_table(raw_disp[["ticker", "weight_pct", "amount_fcfa", "updated_at"]], height=None)
                if st.button("🗑️ Effacer toutes les cibles de ce FCP", key="clear_all_targets"):
                    db.replace_targets_for_fcp(fcp, pd.DataFrame(columns=["ticker","weight_pct","amount_fcfa"]))
                    _clear_data_cache()
                    st.success("Toutes les cibles effacées.")
                    st.rerun()


# ---------------------------------------------------------------------------
# Page: Transactions
# ---------------------------------------------------------------------------
elif page == "💼 Transactions":
    st.header(f"Transactions — {fcp}")

    with st.expander("🔄 Synchronisation SharePoint CGF GESTION", expanded=False):
        st.caption(
            "Source : `PTF ACTIONS CGF GESTION v2.xlsm` (boursecgf.sharepoint.com). "
            "Le bouton ci-dessous télécharge le fichier et écrase les transactions de "
            "l'application avec la feuille **Transactions** (colonnes A à K). "
            "Les cours du jour ne sont **pas** touchés ici — utilisez l'onglet "
            "🌐 Cours BRVM pour cela."
        )

        col_btn, col_status = st.columns([1, 3])
        with col_btn:
            sync_clicked = st.button("🔄 Synchroniser", type="primary", key="sp_sync")
        with col_status:
            st.caption("⚠️ Cette action remplace toutes les transactions stockées.")

        if sync_clicked:
            try:
                from sharepoint_sync import (
                    DEFAULT_URL,
                    download_workbook,
                    read_transactions_from_bytes,
                )
                with st.spinner("Téléchargement depuis SharePoint…"):
                    xlsm = download_workbook(DEFAULT_URL, timeout=60)
                st.success(f"✅ Fichier téléchargé ({len(xlsm)/1024/1024:.1f} Mo)")

                with st.spinner("Lecture de la feuille Transactions…"):
                    new_tx = read_transactions_from_bytes(xlsm)
                st.success(f"✅ {len(new_tx):,} transactions lues".replace(",", " "))

                with st.spinner("Écriture en base…"):
                    n = db.replace_transactions(new_tx)
                st.success(f"✅ {n:,} transactions chargées en base".replace(",", " "))

                st.balloons()
                _clear_data_cache()
                st.rerun()

            except Exception as e:
                st.error(f"❌ Échec de la synchronisation : {e}")
                st.info(
                    "Vérifiez que le lien SharePoint anonyme est toujours actif. "
                    "En cas de blocage, utilisez l'import manuel ci-dessous."
                )

        st.divider()
        with st.expander("📥 Import manuel (.xlsm) — fallback"):
            up = st.file_uploader(
                "Téléverser le fichier `PTF ACTIONS CGF GESTION v2.xlsm`",
                type=["xlsm", "xlsx"],
                key="sp_manual_upload",
            )
            if up is not None:
                try:
                    from sharepoint_sync import read_transactions_from_bytes
                    xlsm = up.getvalue()
                    new_tx = read_transactions_from_bytes(xlsm)
                    st.write(
                        f"**{len(new_tx):,}** transactions détectées".replace(",", " ")
                    )
                    if st.button("Confirmer l'import", key="sp_manual_confirm"):
                        db.replace_transactions(new_tx)
                        st.success("Import réussi.")
                        _clear_data_cache()
                        st.rerun()
                except Exception as e:
                    st.error(f"Lecture impossible : {e}")

    st.divider()

    with st.expander("➕ Nouvelle transaction", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            t_date = st.date_input("Date", value=date.today(), key="tx_date")
            t_sens = st.selectbox("Sens", ["ACHAT", "VENTE"], key="tx_sens")
        with col2:
            known_tickers = _cached_known_tickers()
            ticker_input = st.selectbox(
                "Titre (ou tapez)",
                options=[""] + known_tickers,
                index=0,
                key="tx_ticker_select",
            )
            ticker_manual = st.text_input(
                "...ou nouveau symbole",
                value="",
                key="tx_ticker_manual",
            ).strip().upper()
            t_ticker = ticker_manual or ticker_input
        with col3:
            t_qte = st.number_input("Quantité", min_value=0.0, step=1.0, key="tx_qte")
            t_prix = st.number_input("Prix unitaire (FCFA)", min_value=0.0, step=1.0, key="tx_prix")
            t_frais = st.number_input("Frais (FCFA)", min_value=0.0, step=1.0,
                                       key="tx_frais", value=0.0)

        valeur_preview = t_qte * t_prix + (t_frais if t_sens == "ACHAT" else -t_frais)
        st.caption(f"Valeur calculée : **{fmt_xof(valeur_preview)}**")

        if st.button("💾 Enregistrer", type="primary"):
            if not t_ticker:
                st.error("Symbole requis.")
            elif t_qte <= 0 or t_prix <= 0:
                st.error("Quantité et prix doivent être > 0.")
            else:
                tx_id = db.add_transaction(
                    str(t_date), fcp, t_ticker, t_sens, t_qte, t_prix, t_frais
                )
                st.success(f"Transaction #{tx_id} enregistrée.")
                _clear_data_cache()
                st.rerun()

    st.divider()
    st.subheader("Historique")
    tx = db.get_transactions(fcp)
    if tx.empty:
        st.info("Aucune transaction pour ce FCP.")
    else:
        col_l, col_r = st.columns([3, 1])
        col_l.metric("Total transactions", f"{len(tx)}")
        col_r.download_button(
            "⬇️ Exporter (CSV)",
            data=tx.to_csv(index=False).encode("utf-8"),
            file_name=f"transactions_{fcp.replace(' ', '_')}.csv",
            mime="text/csv",
        )

        tx_display = tx[["id","date","fcp","ticker","sens",
                          "quantite","prix","valeur","frais",
                          "cost_in","cost_out"]].copy()
        tx_display = tx_display.rename(columns={
            "id":       "ID",
            "date":     "Date",
            "fcp":      "FCP",
            "ticker":   "Ticker",
            "sens":     "Sens",
            "quantite": "Quantité",
            "prix":     "Prix",
            "valeur":   "Valeur",
            "frais":    "Frais",
            "cost_in":  "Coût achat",
            "cost_out": "Coût cession",
        })
        for col in ["Prix","Valeur","Frais","Coût achat","Coût cession"]:
            tx_display[col] = pd.to_numeric(
                tx_display[col], errors="coerce"
            ).map(lambda v: "-" if pd.isna(v) or v == 0
                  else f"{v:,.0f}".replace(",", " "))
        tx_display["Quantité"] = pd.to_numeric(
            tx_display["Quantité"], errors="coerce"
        ).map(lambda v: f"{v:,.0f}".replace(",", " ") if pd.notna(v) else "-")
        render_table(tx_display, height=500)

        with st.expander("🗑️ Supprimer une transaction"):
            tx_id_del = st.number_input("ID à supprimer", min_value=0, step=1, key="tx_del_id")
            if st.button("Supprimer"):
                if tx_id_del > 0:
                    db.delete_transaction(int(tx_id_del))
                    st.success(f"Transaction #{tx_id_del} supprimée.")
                _clear_data_cache()
                st.rerun()


# ---------------------------------------------------------------------------
# Page: BRVM live quotes
# ---------------------------------------------------------------------------
elif page == "🌐 Cours BRVM":
    st.header("Cours BRVM — Mise à jour automatique")
    st.caption("Source : sikafinance.com/marches/aaz (fallback brvm.org)")

    last_refresh = db.get_last_brvm_refresh()
    if last_refresh:
        st.caption(f"📅 Dernier rafraîchissement : **{last_refresh}**")

    col1, col2 = st.columns([1, 3])
    with col1:
        do_fetch = st.button("🔄 Rafraîchir maintenant", type="primary")
    with col2:
        st.caption(
            "Chaque rafraîchissement écrase le cours du jour avec la dernière "
            "valeur reçue. Les jours précédents restent intacts."
        )

    if do_fetch:
        try:
            from scraper import fetch_with_session_date
            with st.spinner("Récupération des cours…"):
                quotes_df, sess = fetch_with_session_date(timeout=25)
            for _, row in quotes_df.iterrows():
                db.upsert_quote_today(row.to_dict())
            close_rows = quotes_df[["ticker", "close"]].dropna().copy()
            close_rows["date"] = sess.isoformat()
            close_rows = close_rows.rename(columns={"close": "price"})[["date", "ticker", "price"]]
            n_prices = db.upsert_prices(close_rows, source="brvm")
            _clear_data_cache()
            src = quotes_df.get("source_url", pd.Series(["?"])).iloc[0] if len(quotes_df) else "?"
            st.success(
                f"✅ {len(quotes_df)} cours récupérés depuis **{src}** "
                f"(séance du {sess.strftime('%d/%m/%Y')}). "
                f"{n_prices} cours archivés / mis à jour."
            )
        except Exception as e:
            st.error(f"Échec du rafraîchissement : {e}")
            st.info("Si le scraper échoue, utilisez l'import CSV ci-dessous.")

    st.divider()

    quotes = db.get_quotes_today()
    if quotes.empty:
        st.info("Pas encore de cours en mémoire — cliquez sur Rafraîchir.")
    else:
        st.subheader(f"Snapshot ({len(quotes)} titres)")
        if "fetched_at" in quotes.columns and not quotes["fetched_at"].isna().all():
            st.caption(f"Dernier rafraîchissement : {quotes['fetched_at'].max()}")
        display = quotes.copy()
        for c in ["volume", "prev_close", "open", "close"]:
            if c in display.columns:
                display[c] = display[c].map(
                    lambda v: f"{v:,.0f}".replace(",", " ") if pd.notna(v) else "-"
                )
        if "variation_pct" in display.columns:
            display["variation_pct"] = display["variation_pct"].map(
                lambda v: f"{v:+.2f}%" if pd.notna(v) else "-"
            )
        render_table(display.drop(columns=["fetched_at"], errors="ignore"), height=None)

    st.divider()
    with st.expander("📥 Import manuel CSV (fallback si scraping bloqué)"):
        st.caption("Format attendu : ticker,name,volume,prev_close,open,close,variation_pct")
        f = st.file_uploader("Fichier CSV", type=["csv"], key="quotes_csv")
        if f is not None:
            df = pd.read_csv(f)
            session_d = st.date_input("Date de séance", value=date.today(), key="manual_sess")
            if st.button("Importer ce CSV"):
                for _, r in df.iterrows():
                    db.upsert_quote_today(r.to_dict())
                close_rows = df[["ticker", "close"]].dropna().copy()
                close_rows["date"] = session_d.isoformat()
                close_rows = close_rows.rename(columns={"close": "price"})
                close_rows = close_rows[["date", "ticker", "price"]]
                n = db.upsert_prices(close_rows, source="manual_csv")
                st.success(f"Importé : {len(df)} cours, {n} archivés.")
                _clear_data_cache()
                st.rerun()


# ---------------------------------------------------------------------------
# Page: Price history
# ---------------------------------------------------------------------------
elif page == "📚 Historique cours":
    st.header("Historique des cours")

    with st.expander("🔄 Synchronisation SharePoint CGF GESTION", expanded=False):
        st.caption(
            "Source : `PTF ACTIONS CGF GESTION v2.xlsm` (boursecgf.sharepoint.com). "
            "Le bouton ci-dessous télécharge le fichier et écrase **tout l'historique** "
            "des cours en base avec la feuille **Cours** (colonnes A à BJ). "
            "Les transactions ne sont **pas** touchées ici."
        )

        col_btn, col_status = st.columns([1, 3])
        with col_btn:
            sync_clicked = st.button("🔄 Synchroniser", type="primary", key="sp_sync_cours")
        with col_status:
            st.caption(
                "⚠️ Cette action remplace tout l'historique des cours stocké, "
                "y compris les rafraîchissements BRVM récents."
            )

        if sync_clicked:
            try:
                from sharepoint_sync import (
                    DEFAULT_URL,
                    download_workbook,
                    read_full_cours_history,
                )
                with st.spinner("Téléchargement depuis SharePoint…"):
                    xlsm = download_workbook(DEFAULT_URL, timeout=60)
                st.success(f"✅ Fichier téléchargé ({len(xlsm)/1024/1024:.1f} Mo)")

                with st.spinner("Lecture de la feuille Cours (A:BJ)…"):
                    new_prices = read_full_cours_history(xlsm)
                st.success(
                    f"✅ {len(new_prices):,} cours lus "
                    f"({new_prices['ticker'].nunique()} titres, "
                    f"de {new_prices['date'].min()} à {new_prices['date'].max()})"
                    .replace(",", " ")
                )

                with st.spinner("Écriture en base…"):
                    n = db.replace_prices_history(new_prices, source="sharepoint")
                st.success(f"✅ {n:,} cours chargés en base".replace(",", " "))

                st.balloons()
                _clear_data_cache()
                st.rerun()

            except Exception as e:
                st.error(f"❌ Échec de la synchronisation : {e}")
                st.info(
                    "Vérifiez que le lien SharePoint anonyme est toujours actif. "
                    "En cas de blocage, utilisez l'import manuel ci-dessous."
                )

        st.divider()
        with st.expander("📥 Import manuel (.xlsm) — fallback"):
            up = st.file_uploader(
                "Téléverser le fichier `PTF ACTIONS CGF GESTION v2.xlsm`",
                type=["xlsm", "xlsx"],
                key="sp_manual_upload_cours",
            )
            if up is not None:
                try:
                    from sharepoint_sync import read_full_cours_history
                    xlsm = up.getvalue()
                    new_prices = read_full_cours_history(xlsm)
                    st.write(
                        f"**{len(new_prices):,}** cours détectés "
                        f"({new_prices['ticker'].nunique()} titres, "
                        f"de {new_prices['date'].min()} à {new_prices['date'].max()})"
                        .replace(",", " ")
                    )
                    if st.button("Confirmer l'import", key="sp_manual_confirm_cours"):
                        db.replace_prices_history(new_prices, source="sharepoint")
                        st.success("Import réussi.")
                        _clear_data_cache()
                        st.rerun()
                except Exception as e:
                    st.error(f"Lecture impossible : {e}")

    st.divider()

    prices = _cached_prices()
    if prices.empty:
        st.info("Base vide.")
    else:
        prices = prices.copy()
        prices["date"] = pd.to_datetime(prices["date"])
        tickers = sorted(prices["ticker"].unique())
        sel = st.multiselect(
            "Sélectionnez 1 à 5 titres", tickers,
            default=tickers[:1], max_selections=5,
        )
        if sel:
            sub = prices[prices["ticker"].isin(sel)]
            pivot = sub.pivot_table(index="date", columns="ticker", values="price")
            st.line_chart(pivot)

            with st.expander("Voir les données brutes"):
                render_table(sub.sort_values(["ticker", "date"]), height=None)


# ---------------------------------------------------------------------------
# Page: Settings
# ---------------------------------------------------------------------------
elif page == "⚙️ Paramètres":
    st.header("Paramètres")

    st.subheader("État de la base")
    tx = _cached_transactions()
    prices = _cached_prices()
    quotes = db.get_quotes_today()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FCPs", len(_cached_fcps()))
    c2.metric("Transactions", f"{len(tx):,}".replace(",", " "))
    c3.metric("Cours archivés", f"{len(prices):,}".replace(",", " "))
    c4.metric("Cours du jour", f"{len(quotes)}")

    st.divider()
    st.subheader(f"Dividendes — {fcp}")
    st.caption("Montant par action ajouté à la valorisation (équivalent col N dans Excel).")
    divs = _cached_dividends_all(tuple(fcps)).get(fcp, {})
    held_tickers = sorted(set(tx.loc[tx["fcp"] == fcp, "ticker"].dropna().tolist()))
    if not held_tickers:
        st.info("Aucun titre détenu pour ce FCP.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            div_ticker = st.selectbox("Titre", held_tickers, key="div_ticker")
        with col2:
            current = divs.get(div_ticker, 0.0)
            div_amount = st.number_input(
                "Dividende (FCFA / action)", value=float(current), step=1.0, key="div_amount"
            )
        with col3:
            st.write("")
            st.write("")
            if st.button("💾 Enregistrer dividende", key="div_save"):
                db.set_dividend(fcp, div_ticker, float(div_amount))
                st.success("Dividende enregistré.")
                _clear_data_cache()
                st.rerun()

        if divs:
            st.write("**Dividendes actifs :**")
            render_table(pd.DataFrame(list(divs.items()), columns=["Symbole", "Montant"]), height=None)

            col_del1, col_del2 = st.columns([1, 1])
            with col_del1:
                if st.button(
                    f"🗑️ Supprimer dividende {div_ticker}",
                    key="div_del_one",
                ):
                    db.set_dividend(fcp, div_ticker, 0.0)
                    _clear_data_cache()
                    st.success(f"Dividende de {div_ticker} supprimé.")
                    st.rerun()
            with col_del2:
                if st.button(
                    f"🗑️ Effacer tous les dividendes ({fcp})",
                    key="div_del_all",
                    type="secondary",
                ):
                    for ticker_d in list(divs.keys()):
                        db.set_dividend(fcp, ticker_d, 0.0)
                    _clear_data_cache()
                    st.success(f"Tous les dividendes de {fcp} supprimés.")
                    st.rerun()

    st.divider()
    st.subheader("Maintenance")
    st.info(
        "💡 Les données sont stockées dans Postgres (Supabase) et persistent "
        "automatiquement. Pour ré-initialiser depuis zéro, utilisez les boutons "
        "de synchronisation SharePoint dans les onglets **Transactions** et "
        "**Historique cours**, qui écrasent les tables avec la source officielle."
    )
