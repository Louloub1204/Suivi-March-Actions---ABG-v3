"""Sector classification for BRVM tickers.

Loads `seed_data/sectors.json` once and provides helpers to:
  - Resolve a ticker to its sector (with fallback to "Non classé")
  - List all sectors
  - Annotate a DataFrame with a sector column
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

# The file sits in seed_data/ next to this module.
# We resolve it relative to __file__ so it works regardless of cwd.
_HERE = Path(__file__).resolve().parent
SECTORS_FILE = _HERE / "seed_data" / "sectors.json"
UNKNOWN_LABEL = "Non classé"


@lru_cache(maxsize=1)
def _load() -> dict[str, str]:
    """Return a flat ticker → sector dictionary.

    The JSON file stores the inverse (sector → list of tickers); we flip it
    here for O(1) lookup. Cached for the lifetime of the process.
    """
    if not SECTORS_FILE.exists():
        # Log clearly for debugging so the Streamlit error log helps
        import warnings
        warnings.warn(
            f"sectors.json not found at {SECTORS_FILE}. "
            "All tickers will fall back to 'Non classé'. "
            "Make sure seed_data/sectors.json is committed to the repo.",
            stacklevel=2,
        )
        return {}
    raw = json.loads(SECTORS_FILE.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for sector, tickers in raw.items():
        for t in tickers:
            flat[t.strip().upper()] = sector
    return flat


def sector_of(ticker: str) -> str:
    """Return the sector for a ticker, or 'Non classé' if unknown."""
    return _load().get((ticker or "").strip().upper(), UNKNOWN_LABEL)


def all_sectors() -> list[str]:
    """List of unique sectors, sorted alphabetically."""
    return sorted(set(_load().values()))


def annotate(df: pd.DataFrame, ticker_col: str = "ticker",
             sector_col: str = "secteur") -> pd.DataFrame:
    """Return a copy of `df` with a new sector column added."""
    out = df.copy()
    out[sector_col] = out[ticker_col].map(sector_of)
    return out
