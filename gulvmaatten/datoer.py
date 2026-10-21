"""Tolkning og visning af datoer.

Kilderne skriver datoer på fire forskellige måder:

    2026-08-04T09:55:54+00:00          Glostrup Kommune (ISO)
    Mon, 08 Jan 2024 09:21:00 +0000    Brøndby Kommune (RSS)
    20.10.2026                         Brøndby IF
    3. november 2026 17:00 - 19:00     bibliotekerne

`tolk_dato` forstår dem alle og returnerer None, hvis den ikke kan.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime

MAANEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli",
            "august", "september", "oktober", "november", "december"]
UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]

_DANSK = re.compile(r"(\d{1,2})\.\s*(" + "|".join(MAANEDER) + r")\s+(\d{4})(?:\D{1,12}?(\d{1,2})[:.](\d{2}))?",
                    re.IGNORECASE)
_PUNKTUM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\D{1,12}?(\d{1,2})[:.](\d{2}))?")


def _byg(aar: str, maaned: int, dag: str, time: str | None, minut: str | None) -> datetime | None:
    try:
        return datetime(int(aar), maaned, int(dag), int(time or 0), int(minut or 0))
    except ValueError:
        return None


def tolk_dato(tekst: str) -> datetime | None:
    """Find den første dato i en tekst. Klokkeslæt tages med, hvis det står der."""
    tekst = (tekst or "").strip()
    if not tekst:
        return None
    try:
        return datetime.fromisoformat(tekst).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(tekst).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        pass
    m = _DANSK.search(tekst)
    if m:
        return _byg(m[3], MAANEDER.index(m[2].lower()) + 1, m[1], m[4], m[5])
    m = _PUNKTUM.search(tekst)
    if m:
        return _byg(m[3], int(m[2]), m[1], m[4], m[5])
    return None


def dansk_dato(d: date | datetime | None, ugedag: bool = True) -> str:
    """'torsdag den 19. november 2026'"""
    if not d:
        return ""
    tekst = f"{d.day}. {MAANEDER[d.month - 1]} {d.year}"
    return f"{UGEDAGE[d.weekday()]} den {tekst}" if ugedag else tekst


def klokken(d: datetime | None) -> str:
    """'kl. 19.00', eller tom streng hvis der ikke er et klokkeslæt."""
    if not isinstance(d, datetime) or (d.hour == 0 and d.minute == 0):
        return ""
    return f"kl. {d.hour:02d}.{d.minute:02d}"
