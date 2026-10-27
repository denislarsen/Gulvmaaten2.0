"""Adgang til hjemmesiden, mens den ikke er offentlig.

To måder at komme ind på:

- **Personligt link** (`/adgang/<token>`). Redaktøren laver et link til hver
  person og sender det, fx på sms. Linket er et langt, tilfældigt "token", som
  ikke kan gættes. Når det åbnes, får browseren en session-cookie, og man er
  logget ind i 30 dage. Et link kan spærres igen, så logges personen ud.
- **Ejerens kode** (`/log-ind`) fra miljøvariablen GULVMAATTEN_REDAKTOER_KODE.
  Den bruges første gang, før der findes links.

Roller: `laeser` kan se hjemmesiden; `redaktoer` kan også bruge /redaktion.

Hverken links eller sessioner gemmes i klartekst, kun et SHA-256-fingeraftryk,
så en kopi af databasen ikke giver adgang.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from .db import Database

ROLLER = ("laeser", "redaktoer")
SESSION_DAGE = 30


def _hash(vaerdi: str) -> str:
    return hashlib.sha256(vaerdi.encode("utf-8")).hexdigest()


@dataclass
class Bruger:
    navn: str
    rolle: str
    adgang_id: int | None = None

    @property
    def er_redaktoer(self) -> bool:
        return self.rolle == "redaktoer"


def opret_adgang(db: Database, navn: str, rolle: str = "laeser") -> tuple[int, str]:
    """Opret et personligt link. Returnerer (id, token). Tokenet vises kun her."""
    if rolle not in ROLLER:
        raise ValueError(f"Ukendt rolle: {rolle}")
    token = secrets.token_urlsafe(32)
    cur = db.conn.execute(
        "INSERT INTO adgange (navn, rolle, token_hash, oprettet) VALUES (?,?,?,?)",
        (navn.strip(), rolle, _hash(token), datetime.now().isoformat()))
    db.conn.commit()
    return cur.lastrowid, token


def adgange(db: Database) -> list:
    return list(db.conn.execute("SELECT * FROM adgange ORDER BY spaerret, navn"))


def spaer_adgang(db: Database, adgang_id: int) -> None:
    db.conn.execute("UPDATE adgange SET spaerret=1 WHERE id=?", (adgang_id,))
    db.conn.execute("DELETE FROM sessioner WHERE adgang_id=?", (adgang_id,))
    db.conn.commit()


def _ny_session(db: Database, bruger: Bruger) -> str:
    sid = secrets.token_urlsafe(32)
    nu = datetime.now()
    db.conn.execute(
        "INSERT INTO sessioner (hash, adgang_id, navn, rolle, oprettet, udloeber) VALUES (?,?,?,?,?,?)",
        (_hash(sid), bruger.adgang_id, bruger.navn, bruger.rolle, nu.isoformat(),
         (nu + timedelta(days=SESSION_DAGE)).isoformat()))
    db.conn.commit()
    return sid


def log_ind_med_token(db: Database, token: str) -> str | None:
    """Returnerer en ny session, hvis linket findes og ikke er spærret."""
    row = db.conn.execute("SELECT * FROM adgange WHERE token_hash=? AND spaerret=0", (_hash(token),)).fetchone()
    if not row:
        return None
    db.conn.execute("UPDATE adgange SET sidst_brugt=? WHERE id=?", (datetime.now().isoformat(), row["id"]))
    return _ny_session(db, Bruger(navn=row["navn"], rolle=row["rolle"], adgang_id=row["id"]))


def log_ind_som_ejer(db: Database) -> str:
    return _ny_session(db, Bruger(navn="Ejer", rolle="redaktoer"))


def bruger_fra_session(db: Database, sid: str) -> Bruger | None:
    if not sid:
        return None
    row = db.conn.execute("SELECT * FROM sessioner WHERE hash=?", (_hash(sid),)).fetchone()
    if not row or datetime.fromisoformat(row["udloeber"]) < datetime.now():
        return None
    if row["adgang_id"] is not None:
        adg = db.conn.execute("SELECT spaerret, rolle FROM adgange WHERE id=?", (row["adgang_id"],)).fetchone()
        if not adg or adg["spaerret"]:
            return None
        return Bruger(navn=row["navn"], rolle=adg["rolle"], adgang_id=row["adgang_id"])
    return Bruger(navn=row["navn"], rolle=row["rolle"])


def log_ud(db: Database, sid: str) -> None:
    db.conn.execute("DELETE FROM sessioner WHERE hash=?", (_hash(sid),))
    db.conn.commit()
