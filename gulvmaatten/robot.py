"""Robotten: henter kilder og skriver udkast med faste mellemrum.

Kører som en baggrundstråd inde i hjemmesiden (`python -m gulvmaatten serve`),
så der kun er ét program at holde kørende, og databasefilen kun bruges ét sted.

Hver runde:
1. Registrér kilderne fra config/sources.yaml (nye kilder kommer med)
2. Hent de kilder, der er forfaldne efter deres frekvens
3. Vurdér højst ROBOT_LIMIT nye opslag og skriv udkast

Uden API-nøgle springes trin 3 over, så siden stadig virker.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import load_sources
from .db import Database
from .fetch import fetch_all

log = logging.getLogger("gulvmaatten.robot")

ROBOT_LIMIT = int(os.environ.get("GULVMAATTEN_ROBOT_LIMIT", "10"))  # Hvert opslag koster et API-kald
INTERVAL_MINUTTER = int(os.environ.get("GULVMAATTEN_ROBOT_INTERVAL", "60"))


def api_noegle() -> str | None:
    # Claude Codes skymiljø fjerner ANTHROPIC_API_KEY, så GULVMAATTEN_API_KEY bruges som alternativ.
    return os.environ.get("GULVMAATTEN_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


@dataclass
class RobotStatus:
    """Hvad robotten sidst lavede. Vises i redaktionsværktøjet."""

    koerer: bool = False
    sidst_startet: datetime | None = None
    sidst_faerdig: datetime | None = None
    naeste: datetime | None = None
    linjer: list[str] = field(default_factory=list)
    fejl: str = ""


STATUS = RobotStatus()
_LAAS = threading.Lock()


def koer_en_runde(db_path: Path | str, limit: int = ROBOT_LIMIT) -> list[str]:
    """Én runde. Returnerer en kort beskrivelse af, hvad der skete."""
    linjer: list[str] = []
    db = Database(db_path)
    try:
        for s in load_sources():
            db.upsert_source(s)
        for r in fetch_all(db, kun_forfaldne=True):
            linjer.append(str(r))
        if not linjer:
            linjer.append("Ingen kilder var forfaldne.")

        noegle = api_noegle()
        if not noegle:
            linjer.append("Ingen API-nøgle (GULVMAATTEN_API_KEY), så der er ikke skrevet udkast.")
            return linjer
        import anthropic

        from .agent import koer_redaktion

        client = anthropic.Anthropic(api_key=noegle)
        resultater = koer_redaktion(db, client, limit=limit)
        skrevet = [r for r in resultater if r.artikel_id]
        publiceret = [r for r in skrevet if r.publiceret]
        linjer.append(f"{len(resultater)} opslag vurderet, {len(skrevet)} udkast skrevet, "
                      f"{len(publiceret)} publiceret.")
        for r in skrevet:
            linjer.append(f"  #{r.artikel_id} {r.titel}")
        return linjer
    finally:
        db.close()


def koer_nu(db_path: Path | str) -> bool:
    """Kør en runde nu, hvis robotten ikke allerede er i gang. Returnerer False, hvis den var."""
    if not _LAAS.acquire(blocking=False):
        return False
    try:
        STATUS.koerer = True
        STATUS.sidst_startet = datetime.now()
        STATUS.fejl = ""
        try:
            STATUS.linjer = koer_en_runde(db_path)
        except Exception as e:  # noqa: BLE001 - robotten må ikke dø af én fejl
            log.exception("Robotrunden fejlede")
            STATUS.fejl = f"{type(e).__name__}: {e}"
        STATUS.sidst_faerdig = datetime.now()
        for linje in STATUS.linjer:
            log.info(linje)
        return True
    finally:
        STATUS.koerer = False
        _LAAS.release()


def koer_nu_i_baggrunden(db_path: Path | str) -> None:
    threading.Thread(target=koer_nu, args=(db_path,), daemon=True, name="robot-nu").start()


def start(db_path: Path | str, interval_minutter: int = INTERVAL_MINUTTER) -> threading.Thread:
    """Start robotten i en baggrundstråd. Første runde kører med det samme."""

    def loop() -> None:
        while True:
            koer_nu(db_path)
            STATUS.naeste = datetime.fromtimestamp(time.time() + interval_minutter * 60)
            time.sleep(interval_minutter * 60)

    t = threading.Thread(target=loop, daemon=True, name="robot")
    t.start()
    return t
