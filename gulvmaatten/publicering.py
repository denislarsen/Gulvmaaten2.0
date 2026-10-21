"""Publicering: fra godkendt udkast til side på hjemmesiden.

En artikel er synlig på hjemmesiden, når den har status `published` og en
Publication, der ikke er trukket tilbage. Publication giver artiklen dens
faste adresse (slug), fx /artikel/forfatteraften-med-jens-christian-grondahl.

Autogodkendelse styres fra redaktionsværktøjet og gemmes i databasen. Er den
aldrig sat dér, bruges `automatisk_publicering` fra config/gulvmaatten.yaml.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from .config import load_settings
from .db import Database
from .models import Article, Publication, ReviewStatus

AUTOGODKEND = "autogodkend"


def lav_slug(tekst: str, max_laengde: int = 80) -> str:
    """'Grøndahl fortæller i Glostrup' -> 'groendahl-fortaeller-i-glostrup'"""
    tekst = tekst.lower()
    for dansk, ascii_ in (("æ", "ae"), ("ø", "oe"), ("å", "aa")):
        tekst = tekst.replace(dansk, ascii_)
    tekst = unicodedata.normalize("NFKD", tekst).encode("ascii", "ignore").decode()
    tekst = re.sub(r"[^a-z0-9]+", "-", tekst).strip("-")
    return tekst[:max_laengde].rstrip("-") or "artikel"


def autogodkend(db: Database) -> bool:
    vaerdi = db.get_setting(AUTOGODKEND)
    if vaerdi is not None:
        return vaerdi == "1"
    try:
        return bool(load_settings().get("automatisk_publicering", False))
    except OSError:
        return False


def saet_autogodkend(db: Database, til: bool) -> None:
    db.set_setting(AUTOGODKEND, "1" if til else "0")


def publicer(db: Database, article: Article) -> Publication:
    """Læg artiklen på hjemmesiden. En artikel, der har været trukket tilbage,
    kommer tilbage på sin gamle adresse."""
    article.status = ReviewStatus.PUBLISHED
    db.save_article(article)
    p = db.get_publication(article.id)
    if p is None:
        slug = lav_slug(article.overskrift)
        if db.slug_findes(slug):
            slug = f"{slug}-{article.id}"
        p = Publication(article_id=article.id, slug=slug, publiceret=datetime.now())
        db.save_publication(p)
    elif p.trukket_tilbage:
        p.trukket_tilbage = None
        db.update_publication(p)
    return p


def afpublicer(db: Database, article: Article) -> None:
    """Fjern artiklen fra hjemmesiden. Den kan publiceres igen senere."""
    article.status = ReviewStatus.RETRACTED
    db.save_article(article)
    p = db.get_publication(article.id)
    if p and not p.trukket_tilbage:
        p.trukket_tilbage = datetime.now()
        db.update_publication(p)
