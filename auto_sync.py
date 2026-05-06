"""Auto-sync orchestrator.

Runs once per calendar day on app open:
  1. Sync transactions from SharePoint
  2. Sync cours history from SharePoint
  3. Refresh today's BRVM quotes (sikafinance / brvm.org)

Each step is independent — if step 1 fails, steps 2 and 3 still run.
The progress is shown in a Streamlit progress bar. The state is tracked
in the `sync_log` Postgres table so that the same calendar day never
re-runs the syncs.

Manual buttons in the UI continue to work and bypass the daily lock
(they always run the sync regardless of `needs_sync_today`).
"""
from __future__ import annotations

import streamlit as st

import db


SYNC_KINDS = ("transactions", "cours_history", "brvm_quotes")


def _sync_transactions() -> tuple[bool, str]:
    """Returns (success, message). Never raises."""
    try:
        from sharepoint_sync import (
            DEFAULT_URL,
            download_workbook,
            read_transactions_from_bytes,
        )
        xlsm = download_workbook(DEFAULT_URL, timeout=60)
        new_tx = read_transactions_from_bytes(xlsm)
        n = db.replace_transactions(new_tx)
        return True, f"{n} transactions chargées"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _sync_cours_history() -> tuple[bool, str]:
    try:
        from sharepoint_sync import (
            DEFAULT_URL,
            download_workbook,
            read_full_cours_history,
        )
        xlsm = download_workbook(DEFAULT_URL, timeout=60)
        new_prices = read_full_cours_history(xlsm)
        n = db.replace_prices_history(new_prices, source="sharepoint")
        return True, f"{n} cours chargés"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _sync_brvm_quotes() -> tuple[bool, str]:
    try:
        import pandas as pd
        from scraper import fetch_with_session_date

        quotes_df, sess = fetch_with_session_date(timeout=25)
        for _, row in quotes_df.iterrows():
            db.upsert_quote_today(row.to_dict())
        close_rows = quotes_df[["ticker", "close"]].dropna().copy()
        close_rows["date"] = sess.isoformat()
        close_rows = close_rows.rename(columns={"close": "price"})[
            ["date", "ticker", "price"]
        ]
        n = db.upsert_prices(close_rows, source="brvm")
        src = (
            quotes_df.get("source_url", pd.Series(["?"])).iloc[0]
            if len(quotes_df) else "?"
        )
        return True, f"{n} cours BRVM rafraîchis (source: {src})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


_SYNC_FUNCS = {
    "transactions": ("📥 Transactions SharePoint", _sync_transactions),
    "cours_history": ("📚 Historique cours SharePoint", _sync_cours_history),
    "brvm_quotes": ("🌐 Cours BRVM du jour", _sync_brvm_quotes),
}


def run_daily_auto_sync_if_needed() -> bool:
    """If today's syncs haven't been done yet, run them now with a progress UI.

    Returns True if at least one sync was attempted, False if everything
    was already up to date for today.
    """
    pending = [k for k in SYNC_KINDS if db.needs_sync_today(k)]
    if not pending:
        return False

    container = st.container()
    with container:
        st.info(
            "🔄 **Synchronisation quotidienne en cours…** "
            "Première ouverture du jour : l'app récupère les dernières "
            "données depuis SharePoint et BRVM. Patientez quelques secondes, "
            "ne fermez pas la fenêtre."
        )
        progress = st.progress(0, text="Initialisation…")
        results: list[tuple[str, bool, str]] = []

        for i, kind in enumerate(pending):
            label, fn = _SYNC_FUNCS[kind]
            progress.progress(
                int(i / len(pending) * 100),
                text=f"{label} — en cours…",
            )
            ok, msg = fn()
            db.record_sync(kind, "success" if ok else "error", msg)
            results.append((label, ok, msg))

        progress.progress(100, text="Terminé.")

        # Compact result summary
        ok_count = sum(1 for _, ok, _ in results if ok)
        err_count = len(results) - ok_count

        if err_count == 0:
            st.success(f"✅ Synchronisation terminée — {ok_count} actions réussies.")
        else:
            st.warning(
                f"⚠️ Synchronisation partielle : {ok_count} OK, {err_count} échec(s). "
                "Voir détail ci-dessous. Les boutons manuels dans les onglets "
                "permettent de relancer."
            )

        with st.expander("Détail des syncs", expanded=(err_count > 0)):
            for label, ok, msg in results:
                icon = "✓" if ok else "✗"
                st.write(f"{icon} **{label}** : {msg}")

    return True


def render_sync_status_sidebar() -> None:
    """Show a small footer in the sidebar with last sync timestamps."""
    with st.sidebar:
        st.divider()
        st.caption("**Dernière synchronisation auto**")
        for kind in SYNC_KINDS:
            label = _SYNC_FUNCS[kind][0]
            rec = db.get_sync_status(kind)
            if rec is None:
                st.caption(f"{label} : *jamais*")
            else:
                d = rec["last_run_date"]
                status_icon = "✓" if rec["status"] == "success" else "✗"
                st.caption(f"{label} : {status_icon} {d}")
