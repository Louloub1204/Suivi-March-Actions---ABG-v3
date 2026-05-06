"""FCP valuation calendar.

Some FCPs do not value daily; they value once a week on a fixed day. For
those, the "previous cours" used to compute daily variation must be the
previous occurrence of that weekday, not yesterday.

Mapping provided by the user.
"""
from __future__ import annotations

import pandas as pd

# Python weekday indices: Monday=0, Tuesday=1, ..., Sunday=6
WEEKLY_FCPS: dict[str, int] = {
    # FCPs that value on Friday → previous cours = previous Friday
    "FCP IFC-BOAD": 4,
    "VISION MONETAIRE": 4,
    # FCPs that value on Monday → previous cours = previous Monday
    "FCP DIASPORA": 0,
    "FCP WALO": 0,
    "FCPE DP WORLD DAKAR": 0,
    "FCP DJOLOF": 0,
    # FCPs that value on Tuesday → previous cours = previous Tuesday
    "FCP RENTE PERPÉTUELLE": 1,
    "FCP CAPITAL RETRAITE": 1,
    "FCPE SINI GNESIGUI": 1,
    # FCPs that value on Wednesday → previous cours = previous Wednesday
    "FCP EXPAT": 2,
    "FCPE FORCE PAD": 2,
    "UCA DOGUICIMI": 2,
    # FCPs that value on Thursday → previous cours = previous Thursday
    "FCPCR SONATEL": 3,
}


def previous_cours_date(fcp: str, as_of: pd.Timestamp) -> pd.Timestamp:
    """Return the date to use as 'previous cours' for this FCP and as-of date.

    For weekly-valuation FCPs: the previous occurrence of the configured
    weekday, strictly before `as_of` (so if as_of itself falls on the
    valuation weekday, we go back 7 days).

    For all other FCPs: the previous business day (Monday → previous Friday).
    """
    as_of = pd.Timestamp(as_of)

    if fcp in WEEKLY_FCPS:
        target_weekday = WEEKLY_FCPS[fcp]
        # Days to subtract so that the result lands on `target_weekday`,
        # strictly before `as_of`.
        delta = (as_of.weekday() - target_weekday) % 7
        if delta == 0:
            delta = 7
        return as_of - pd.Timedelta(days=delta)

    # Default: previous business day. Monday → Friday (3 days back), else 1 day.
    return as_of - pd.Timedelta(days=3 if as_of.weekday() == 0 else 1)


def is_weekly_fcp(fcp: str) -> bool:
    return fcp in WEEKLY_FCPS


def weekday_label(idx: int) -> str:
    return ["lundi", "mardi", "mercredi", "jeudi", "vendredi",
            "samedi", "dimanche"][idx]
