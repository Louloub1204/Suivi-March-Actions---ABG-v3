"""One-shot seed script to populate the Postgres database.

Usage:
    export DATABASE_URL='postgresql://user:password@host:port/dbname'
    python seed_postgres.py

This script:
  1. Creates the schema (idempotent)
  2. Wipes existing data
  3. Loads everything from seed_data/ (FCPs, transactions, prices, today's snapshot)

Run this ONCE after creating your Supabase/Neon project. After that, the app
manages all writes itself via the Streamlit UI.
"""
from __future__ import annotations

import os
import sys

import db


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        print(
            "ERREUR : la variable d'environnement DATABASE_URL n'est pas définie.\n"
            "\n"
            "Exemple sous bash :\n"
            "  export DATABASE_URL='postgresql://postgres:PASSWORD@db.xyz.supabase.co:5432/postgres'\n"
            "\n"
            "Exemple sous PowerShell :\n"
            "  $env:DATABASE_URL='postgresql://...'\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print("→ Création du schéma…")
    db.init_db()

    print("→ Chargement des données depuis seed_data/…")
    db.seed_from_files()

    fcps = db.get_fcps()
    n_tx = len(db.get_all_transactions_for_compute())
    n_prices = len(db.get_prices())
    n_quotes = len(db.get_quotes_today())

    print()
    print("=" * 50)
    print(f"  ✓ {len(fcps)} FCPs")
    print(f"  ✓ {n_tx:,} transactions".replace(",", " "))
    print(f"  ✓ {n_prices:,} cours archivés".replace(",", " "))
    print(f"  ✓ {n_quotes} cours du jour")
    print("=" * 50)
    print("\nBase prête. Tu peux déployer l'app sur Streamlit Cloud.")


if __name__ == "__main__":
    main()
