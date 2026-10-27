"""Fælles for kommandolinjen og serveren: godkendelse og den faste kørsel."""

from __future__ import annotations

import os
from typing import Callable

import anthropic

from .db import Database
from .fetch import fetch_all
from .models import Article, ReviewStatus


class KanIkkeGodkendes(ValueError):
    pass


class IngenNoegle(RuntimeError):
    pass


def claude_client() -> anthropic.Anthropic:
    # Claude Codes skymiljø fjerner ANTHROPIC_API_KEY, så GULVMAATTEN_API_KEY bruges som alternativ.
    api_key = os.environ.get("GULVMAATTEN_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise IngenNoegle("Ingen API-nøgle. Sæt GULVMAATTEN_API_KEY i miljøets indstillinger.")
    return anthropic.Anthropic(api_key=api_key)


def godkend(db: Database, article_id: int, karakter: int | None = None) -> Article:
    a = db.get_article(article_id)
    if not a:
        raise KanIkkeGodkendes(f"Ingen artikel med id {article_id}.")
    if not a.kilder:
        raise KanIkkeGodkendes("Artiklen har ingen kilder og kan ikke godkendes.")
    if "tip" in a.tags:
        raise KanIkkeGodkendes("Et tip fra et andet medie kan ikke publiceres. Find en selvstændig kilde.")
    if "[Udfyldes efter besøg" in a.broedtekst:
        raise KanIkkeGodkendes("Anmeldelsen mangler redaktørens dom. Ret brødteksten, før den godkendes.")
    if karakter:
        a.tags = [t for t in a.tags if not t.startswith("karakter:")] + [f"karakter:{karakter}"]
    a.status = ReviewStatus.APPROVED
    db.save_article(a)
    return a


def afvis(db: Database, article_id: int) -> Article:
    a = db.get_article(article_id)
    if not a:
        raise KanIkkeGodkendes(f"Ingen artikel med id {article_id}.")
    a.status = ReviewStatus.REJECTED
    db.save_article(a)
    return a


def koer_planlagt(db: Database, client: anthropic.Anthropic, limit: int = 20,
                  log: Callable[[str], None] = print) -> None:
    """Kør alt, der er forfaldent: kilder, redaktion, kalender, servicehistorier og mad."""
    from . import mad, service
    from .agent import koer_redaktion
    from .kalender import koer_kalender

    for r in fetch_all(db, kun_forfaldne=True):
        log(str(r))
    resultater = koer_redaktion(db, client, limit=limit)
    log(f"Redaktion: {len(resultater)} vurderet, {sum(1 for r in resultater if r.artikel_id)} udkast.")
    kal = koer_kalender(db, client, limit=limit)
    log(f"Kalender: {len(kal)} opslag læst, {sum(r.antal for r in kal)} arrangementer fundet.")
    indst = mad.mad_indstillinger()
    if mad.er_forfalden(db, mad.KOERSEL_FIND_NYE, indst["find_nye_spisesteder_hver_dage"]):
        nye = mad.find_nye_spisesteder(db)
        log(f"Nye spisesteder: {', '.join(nye) if nye else 'ingen'}")
    for koersel, fn in ((service.KOERSEL_UGEN, service.det_sker_i_ugen), (service.KOERSEL_BOLIG, service.boligmarkedet)):
        if mad.er_forfalden(db, koersel, 7):
            artikel_id = fn(db)
            log(f"{koersel}: udkast #{artikel_id}" if artikel_id else f"{koersel}: ikke nok data")
    if mad.er_forfalden(db, mad.KOERSEL_UGENS, indst["ugens_spisested_hver_dage"]):
        artikel_id = mad.lav_ugens_spisested(db, client)
        log(f"Ugens spisested: udkast #{artikel_id}" if artikel_id else "Ugens spisested: intet nyt sted")
