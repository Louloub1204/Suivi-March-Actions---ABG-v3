"""Postgres-backed storage for FCPs, transactions, and historical prices.

The connection string is read from Streamlit Secrets (`db.url`) when running
inside Streamlit, falling back to the `DATABASE_URL` environment variable
for local CLI scripts (seed loader, etc.).

The public API of this module is identical to the previous SQLite version,
so no other module needs to change.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

APP_DIR = Path(__file__).resolve().parent
SEED_DIR = APP_DIR / "seed_data"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    """Return the Postgres connection URL.

    Priority:
      1. Streamlit Secrets `[db] url = "..."`
      2. Environment variable DATABASE_URL
    """
    try:
        import streamlit as st
        url = st.secrets["db"]["url"]
        if url:
            return _normalize_url(url)
    except Exception:
        pass

    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return _normalize_url(url)

    raise RuntimeError(
        "Aucune URL de base de données configurée. "
        "Définissez `[db] url = '...'` dans Streamlit Secrets, "
        "ou la variable d'environnement DATABASE_URL pour un usage local."
    )


def _normalize_url(url: str) -> str:
    """Supabase / Neon often expose URLs as `postgres://...`. SQLAlchemy >= 1.4
    requires `postgresql://`. We rewrite if needed and force the psycopg2 driver.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            _get_db_url(),
            pool_pre_ping=True,
            pool_recycle=300,
            future=True,
        )
    return _engine


@contextmanager
def conn():
    """Yield a SQLAlchemy connection inside a transaction."""
    eng = get_engine()
    with eng.begin() as c:
        yield c


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS fcps (
        name TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id BIGSERIAL PRIMARY KEY,
        date DATE NOT NULL,
        fcp TEXT NOT NULL,
        ticker TEXT NOT NULL,
        sens TEXT NOT NULL CHECK (sens IN ('ACHAT','VENTE')),
        quantite DOUBLE PRECISION NOT NULL,
        prix DOUBLE PRECISION DEFAULT 0,
        valeur DOUBLE PRECISION DEFAULT 0,
        frais DOUBLE PRECISION DEFAULT 0,
        cost_in DOUBLE PRECISION DEFAULT 0,
        cost_out DOUBLE PRECISION DEFAULT 0,
        cmp_at_tx DOUBLE PRECISION DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tx_fcp_date ON transactions(fcp, date)",
    "CREATE INDEX IF NOT EXISTS idx_tx_ticker ON transactions(ticker)",
    """
    CREATE TABLE IF NOT EXISTS prices (
        date DATE NOT NULL,
        ticker TEXT NOT NULL,
        price DOUBLE PRECISION NOT NULL,
        source TEXT DEFAULT 'seed',
        PRIMARY KEY (date, ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date)",
    """
    """
    CREATE TABLE IF NOT EXISTS dividends_dated (
        id BIGSERIAL PRIMARY KEY,
        ticker TEXT NOT NULL,
        amount DOUBLE PRECISION NOT NULL,
        payment_date DATE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    CREATE TABLE IF NOT EXISTS quotes_today (
        ticker TEXT PRIMARY KEY,
        name TEXT,
        volume DOUBLE PRECISION,
        prev_close DOUBLE PRECISION,
        open DOUBLE PRECISION,
        close DOUBLE PRECISION,
        variation_pct DOUBLE PRECISION,
        fetched_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dividends (
        fcp TEXT NOT NULL,
        ticker TEXT NOT NULL,
        amount DOUBLE PRECISION NOT NULL,
        date DATE,
        PRIMARY KEY (fcp, ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_log (
        kind TEXT PRIMARY KEY,
        last_run_date DATE NOT NULL,
        last_run_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL,
        message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS targets (
        fcp        TEXT NOT NULL,
        ticker     TEXT NOT NULL,
        weight_pct DOUBLE PRECISION,
        amount_fcfa DOUBLE PRECISION,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (fcp, ticker)
    )
    """,
]


def init_db(force: bool = False) -> None:
    """Create the schema if absent. Optionally seed from local CSVs.

    On Postgres this is idempotent and **does not auto-seed** (since the data
    is meant to live persistently). To populate an empty database, run the
    `seed_postgres.py` script provided alongside the app.
    """
    with conn() as c:
        for stmt in SCHEMA_STATEMENTS:
            c.execute(text(stmt))

    if force:
        seed_from_files()


def _is_empty() -> bool:
    with conn() as c:
        n = c.execute(text("SELECT COUNT(*) FROM transactions")).scalar() or 0
    return n == 0


def seed_from_files() -> None:
    """Load all CSV/JSON files from `seed_data/` into the database.

    Used by the `seed_postgres.py` CLI script. Calling this on a populated
    database will REPLACE the existing data — be careful.
    """
    if not SEED_DIR.exists():
        raise RuntimeError(f"seed_data/ folder not found at {SEED_DIR}")

    eng = get_engine()

    fcps_file = SEED_DIR / "fcps.json"
    if fcps_file.exists():
        names = json.loads(fcps_file.read_text(encoding="utf-8"))
        with eng.begin() as c:
            c.execute(text("DELETE FROM fcps"))
            for n in names:
                c.execute(
                    text("INSERT INTO fcps(name) VALUES (:n) ON CONFLICT DO NOTHING"),
                    {"n": n},
                )

    tx_file = SEED_DIR / "transactions.csv"
    if tx_file.exists():
        df = pd.read_csv(tx_file)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        with eng.begin() as c:
            c.execute(text("DELETE FROM transactions"))
        df.to_sql("transactions", eng, if_exists="append", index=False, method="multi", chunksize=500)

    cours_file = SEED_DIR / "cours.csv"
    if cours_file.exists():
        df = pd.read_csv(cours_file)
        df = df.drop_duplicates(subset=["date", "ticker"], keep="last")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["source"] = "seed"
        with eng.begin() as c:
            c.execute(text("DELETE FROM prices"))
        df.to_sql("prices", eng, if_exists="append", index=False, method="multi", chunksize=1000)

    t4_file = SEED_DIR / "table4.csv"
    if t4_file.exists():
        df = pd.read_csv(t4_file)
        df["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
        with eng.begin() as c:
            c.execute(text("DELETE FROM quotes_today"))
        df.to_sql("quotes_today", eng, if_exists="append", index=False, method="multi", chunksize=500)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_fcps() -> list[str]:
    with conn() as c:
        rows = c.execute(text("SELECT name FROM fcps ORDER BY name")).fetchall()
    return [r[0] for r in rows]


def get_transactions(fcp: str | None = None) -> pd.DataFrame:
    eng = get_engine()
    if fcp:
        return pd.read_sql_query(
            text("SELECT * FROM transactions WHERE fcp = :fcp ORDER BY date DESC, id DESC"),
            eng, params={"fcp": fcp},
        )
    return pd.read_sql_query(
        text("SELECT * FROM transactions ORDER BY date DESC, id DESC"), eng
    )


def get_all_transactions_for_compute() -> pd.DataFrame:
    eng = get_engine()
    return pd.read_sql_query(
        text("SELECT date, fcp, ticker, sens, quantite, prix, valeur, frais, "
             "cost_in, cost_out, cmp_at_tx FROM transactions"),
        eng,
    )


def get_prices() -> pd.DataFrame:
    eng = get_engine()
    return pd.read_sql_query(text("SELECT date, ticker, price FROM prices"), eng)


def get_quotes_today() -> pd.DataFrame:
    eng = get_engine()
    return pd.read_sql_query(text("SELECT * FROM quotes_today"), eng)


def get_dividends(fcp: str) -> dict[str, float]:
    with conn() as c:
        rows = c.execute(
            text("SELECT ticker, amount FROM dividends WHERE fcp = :fcp"),
            {"fcp": fcp},
        ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def get_known_tickers() -> list[str]:
    with conn() as c:
        rows = c.execute(
            text("SELECT DISTINCT ticker FROM prices ORDER BY ticker")
        ).fetchall()
    return [r[0] for r in rows]


def get_latest_archived_date() -> str | None:
    with conn() as c:
        row = c.execute(text("SELECT MAX(date) FROM prices")).scalar()
    return str(row) if row else None


def has_prices_on(d: str) -> bool:
    with conn() as c:
        n = c.execute(
            text("SELECT COUNT(*) FROM prices WHERE date = :d"),
            {"d": d},
        ).scalar() or 0
    return n > 0


def get_last_brvm_refresh() -> str | None:
    with conn() as c:
        row = c.execute(text("SELECT MAX(fetched_at) FROM quotes_today")).scalar()
    return row if row else None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def add_transaction(
    date: str, fcp: str, ticker: str, sens: str,
    quantite: float, prix: float, frais: float = 0,
) -> int:
    valeur = quantite * prix
    cost_in = valeur + frais if sens == "ACHAT" else 0.0
    cost_out = 0.0
    cmp_at_tx = 0.0

    if sens == "VENTE":
        with conn() as c:
            row = c.execute(
                text("""SELECT
                          SUM(CASE WHEN sens='ACHAT' THEN quantite ELSE -quantite END) AS qty,
                          SUM(cost_in - cost_out) AS cost
                        FROM transactions
                        WHERE fcp = :fcp AND ticker = :ticker AND date <= :d"""),
                {"fcp": fcp, "ticker": ticker, "d": date},
            ).fetchone()
        prior_qty = float(row[0] or 0) if row else 0
        prior_cost = float(row[1] or 0) if row else 0
        cmp_at_tx = prior_cost / prior_qty if prior_qty else 0.0
        cost_out = quantite * cmp_at_tx

    with conn() as c:
        result = c.execute(
            text("""INSERT INTO transactions
                    (date, fcp, ticker, sens, quantite, prix, valeur, frais,
                     cost_in, cost_out, cmp_at_tx)
                    VALUES (:date, :fcp, :ticker, :sens, :quantite, :prix, :valeur,
                            :frais, :cost_in, :cost_out, :cmp_at_tx)
                    RETURNING id"""),
            {
                "date": date, "fcp": fcp, "ticker": ticker, "sens": sens,
                "quantite": quantite, "prix": prix, "valeur": valeur,
                "frais": frais, "cost_in": cost_in, "cost_out": cost_out,
                "cmp_at_tx": cmp_at_tx,
            },
        )
        return int(result.scalar())


def delete_transaction(tx_id: int) -> None:
    with conn() as c:
        c.execute(
            text("DELETE FROM transactions WHERE id = :id"),
            {"id": tx_id},
        )


def upsert_prices(df: pd.DataFrame, source: str = "manual") -> int:
    """Insert or replace prices. One row per (date, ticker)."""
    if df.empty:
        return 0
    df = df.copy()
    df["source"] = source
    with conn() as c:
        for date_, ticker, price, src in df[
            ["date", "ticker", "price", "source"]
        ].itertuples(index=False, name=None):
            c.execute(
                text("""INSERT INTO prices(date, ticker, price, source)
                        VALUES (:d, :t, :p, :s)
                        ON CONFLICT (date, ticker)
                        DO UPDATE SET price = EXCLUDED.price, source = EXCLUDED.source"""),
                {"d": date_, "t": ticker, "p": price, "s": src},
            )
    return len(df)


def upsert_quote_today(quote: dict[str, Any]) -> None:
    with conn() as c:
        c.execute(
            text("""INSERT INTO quotes_today
                    (ticker, name, volume, prev_close, open, close, variation_pct, fetched_at)
                    VALUES (:ticker, :name, :volume, :prev_close, :open, :close,
                            :variation_pct, :fetched_at)
                    ON CONFLICT (ticker) DO UPDATE SET
                      name = EXCLUDED.name,
                      volume = EXCLUDED.volume,
                      prev_close = EXCLUDED.prev_close,
                      open = EXCLUDED.open,
                      close = EXCLUDED.close,
                      variation_pct = EXCLUDED.variation_pct,
                      fetched_at = EXCLUDED.fetched_at"""),
            {
                "ticker": quote.get("ticker"),
                "name": quote.get("name"),
                "volume": quote.get("volume"),
                "prev_close": quote.get("prev_close"),
                "open": quote.get("open"),
                "close": quote.get("close"),
                "variation_pct": quote.get("variation_pct"),
                "fetched_at": quote.get("fetched_at")
                              or pd.Timestamp.now().isoformat(timespec="seconds"),
            },
        )


def set_dividend(fcp: str, ticker: str, amount: float, date: str | None = None) -> None:
    with conn() as c:
        if amount == 0:
            c.execute(
                text("DELETE FROM dividends WHERE fcp = :fcp AND ticker = :ticker"),
                {"fcp": fcp, "ticker": ticker},
            )
        else:
            c.execute(
                text("""INSERT INTO dividends(fcp, ticker, amount, date)
                        VALUES (:fcp, :ticker, :amount, :date)
                        ON CONFLICT (fcp, ticker) DO UPDATE SET
                          amount = EXCLUDED.amount, date = EXCLUDED.date"""),
                {"fcp": fcp, "ticker": ticker, "amount": amount, "date": date},
            )


def replace_transactions(df: pd.DataFrame) -> int:
    """Wipe and reload the transactions table."""
    required = {"date", "fcp", "ticker", "sens", "quantite", "prix",
                "valeur", "frais", "cost_in", "cost_out", "cmp_at_tx"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes : {missing}")
    if df.empty:
        raise ValueError("Aucune transaction à charger.")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DELETE FROM transactions"))
    df[list(required)].to_sql(
        "transactions", eng, if_exists="append", index=False,
        method="multi", chunksize=500,
    )
    return len(df)


def replace_prices_history(df: pd.DataFrame, source: str = "sharepoint") -> int:
    """Wipe and reload the prices table."""
    required = {"date", "ticker", "price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes : {missing}")
    if df.empty:
        raise ValueError("Aucun cours à charger.")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["source"] = source
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DELETE FROM prices"))
    df[["date", "ticker", "price", "source"]].to_sql(
        "prices", eng, if_exists="append", index=False,
        method="multi", chunksize=1000,
    )
    return len(df)


# ---------------------------------------------------------------------------
# Sync log — tracks daily auto-sync runs
# ---------------------------------------------------------------------------

def get_sync_status(kind: str) -> dict | None:
    """Return the last sync record for `kind` (e.g. 'transactions', 'cours_history',
    'brvm_quotes'). Returns None if no run has been recorded yet."""
    with conn() as c:
        row = c.execute(
            text("SELECT kind, last_run_date, last_run_at, status, message "
                 "FROM sync_log WHERE kind = :k"),
            {"k": kind},
        ).fetchone()
    if not row:
        return None
    return {
        "kind": row[0],
        "last_run_date": row[1],
        "last_run_at": row[2],
        "status": row[3],
        "message": row[4],
    }


def record_sync(kind: str, status: str, message: str = "") -> None:
    """Record (or upsert) a sync run with today's date."""
    with conn() as c:
        c.execute(
            text("""INSERT INTO sync_log(kind, last_run_date, last_run_at, status, message)
                    VALUES (:k, CURRENT_DATE, CURRENT_TIMESTAMP, :s, :m)
                    ON CONFLICT (kind) DO UPDATE SET
                      last_run_date = CURRENT_DATE,
                      last_run_at = CURRENT_TIMESTAMP,
                      status = EXCLUDED.status,
                      message = EXCLUDED.message"""),
            {"k": kind, "s": status, "m": message},
        )


def needs_sync_today(kind: str) -> bool:
    """True if `kind` has not been successfully synced today."""
    rec = get_sync_status(kind)
    if not rec:
        return True
    if rec["status"] != "success":
        return True
    last = rec["last_run_date"]
    # last is a datetime.date object (Postgres DATE). Compare with today.
    import datetime as _dt
    today = _dt.date.today()
    return last != today


# ---------------------------------------------------------------------------
# Targets (pondérations cibles par FCP)
# ---------------------------------------------------------------------------

def get_targets(fcp: str | None = None) -> pd.DataFrame:
    """Return all targets, optionally filtered by FCP."""
    eng = get_engine()
    if fcp:
        return pd.read_sql_query(
            text("SELECT fcp, ticker, weight_pct, amount_fcfa, updated_at "
                 "FROM targets WHERE fcp = :fcp ORDER BY ticker"),
            eng, params={"fcp": fcp},
        )
    return pd.read_sql_query(
        text("SELECT fcp, ticker, weight_pct, amount_fcfa, updated_at "
             "FROM targets ORDER BY fcp, ticker"),
        eng,
    )


def upsert_target(fcp: str, ticker: str,
                  weight_pct: float | None,
                  amount_fcfa: float | None) -> None:
    """Insert or update a single target row."""
    with conn() as c:
        c.execute(
            text("""INSERT INTO targets(fcp, ticker, weight_pct, amount_fcfa, updated_at)
                    VALUES (:fcp, :ticker, :w, :a, CURRENT_TIMESTAMP)
                    ON CONFLICT (fcp, ticker) DO UPDATE SET
                      weight_pct  = EXCLUDED.weight_pct,
                      amount_fcfa = EXCLUDED.amount_fcfa,
                      updated_at  = CURRENT_TIMESTAMP"""),
            {"fcp": fcp, "ticker": ticker, "w": weight_pct, "a": amount_fcfa},
        )


def delete_target(fcp: str, ticker: str) -> None:
    with conn() as c:
        c.execute(
            text("DELETE FROM targets WHERE fcp = :fcp AND ticker = :ticker"),
            {"fcp": fcp, "ticker": ticker},
        )


def replace_targets_for_fcp(fcp: str, df: pd.DataFrame) -> int:
    """Wipe all targets for a FCP and reload from DataFrame.

    `df` must have columns: ticker, weight_pct (nullable), amount_fcfa (nullable).
    """
    df = df.copy()
    df["fcp"] = fcp
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DELETE FROM targets WHERE fcp = :fcp"), {"fcp": fcp})
    valid = df[df["ticker"].notna() & (df["ticker"] != "")]
    if valid.empty:
        return 0
    valid[["fcp", "ticker", "weight_pct", "amount_fcfa"]].to_sql(
        "targets", eng, if_exists="append", index=False,
        method="multi", chunksize=200,
    )
    return len(valid)


def replace_all_targets(df: pd.DataFrame) -> int:
    """Wipe the entire targets table and reload from DataFrame.

    `df` must have columns: fcp, ticker, weight_pct (nullable), amount_fcfa (nullable).
    """
    df = df.copy()
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DELETE FROM targets"))
    valid = df[df["ticker"].notna() & (df["ticker"] != "") &
               df["fcp"].notna() & (df["fcp"] != "")]
    if valid.empty:
        return 0
    valid[["fcp", "ticker", "weight_pct", "amount_fcfa"]].to_sql(
        "targets", eng, if_exists="append", index=False,
        method="multi", chunksize=200,
    )
    return len(valid)
# ---------------------------------------------------------------------------
# Dividends with payment dates
# ---------------------------------------------------------------------------

def get_dividends_dated() -> list[dict]:
    """Return all dividends with their payment dates."""
    eng = get_engine()
    df = pd.read_sql_query(
        text("SELECT id, ticker, amount, payment_date "
             "FROM dividends_dated ORDER BY payment_date DESC, ticker"),
        eng,
    )
    return df.to_dict("records")


def add_dividend_dated(
    ticker: str,
    amount: float,
    payment_date: str,
) -> int:
    """Insert a new dividend entry. Returns the new id."""
    with conn() as c:
        result = c.execute(
            text("""INSERT INTO dividends_dated(ticker, amount, payment_date)
                    VALUES (:ticker, :amount, :pd)
                    RETURNING id"""),
            {"ticker": ticker.strip().upper(),
             "amount": amount,
             "pd": payment_date},
        )
        return int(result.scalar())


def delete_dividend_dated(div_id: int) -> None:
    with conn() as c:
        c.execute(
            text("DELETE FROM dividends_dated WHERE id = :id"),
            {"id": div_id},
        )


def clear_all_dividends_dated() -> None:
    with conn() as c:
        c.execute(text("DELETE FROM dividends_dated"))
