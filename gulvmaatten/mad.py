"""Madsektionen: "Ugens spisested".

To faste opgaver, hver med sin egen frekvens i config/gulvmaatten.yaml (`mad:`):

1. Find nye spisesteder  Tjekker Hundested Havns oversigt over caféer og
                         restauranter og melder steder, der ikke står i
                         config/steder.yaml. De skrives ikke ind automatisk.
2. Ugens spisested       Vælger det spisested, der længst har ventet, henter
                         stedets egen hjemmeside og lader Claude skrive et
                         udkast til en præsentation.

En anmeldelse kræver, at nogen har spist der. Agenten kan ikke smage maden,
så udkastet indeholder kun fakta fra stedets egen side og en tjekliste til
redaktøren. Selve vurderingen og karakteren skrives af redaktøren efter et
besøg. Derfor har udkastet altid risiko "high", så det ikke kan glide igennem.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import yaml
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .agent import MODEL, SYSTEM_REDAKTION, dagens_dato, hent_artikeltekst
from .config import CONFIG_DIR, load_settings
from .db import Database
from .fetch import _og_image, hent
from .models import Article, ReviewStatus, RiskLevel

HAVN_SPISESTEDER_URL = "https://hundestedhavn.dk/kultur-oplevelser/"
KOERSEL_FIND_NYE = "find-nye-spisesteder"
KOERSEL_UGENS = "ugens-spisested"
TAG_PREFIX = "spisested:"


@dataclass
class Spisested:
    id: str
    navn: str
    adresse: str = ""
    web: str = ""
    facebook: str = ""
    instagram: str = ""
    note: str = ""


def load_spisesteder(path: Path | None = None) -> list[Spisested]:
    with open(path or CONFIG_DIR / "steder.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    felter = Spisested.__dataclass_fields__
    return [Spisested(**{k: v for k, v in d.items() if k in felter}) for d in data.get("spisesteder", [])]


def mad_indstillinger() -> dict:
    standard = {"ugens_spisested_hver_dage": 7, "find_nye_spisesteder_hver_dage": 30,
                "samme_sted_igen_efter_dage": 180}
    try:
        return {**standard, **(load_settings().get("mad") or {})}
    except FileNotFoundError:
        return standard


def er_forfalden(db: Database, navn: str, hver_dage: int, nu: datetime | None = None) -> bool:
    sidst = db.sidst_koert(navn)
    return sidst is None or (nu or datetime.now()) - sidst >= timedelta(days=hver_dage)


# --- 1. Find nye spisesteder --------------------------------------------------

def _norm(navn: str) -> str:
    """Til sammenligning af navne: små bogstaver, uden accenter og tegn.
    æ, ø og å bevares."""
    navn = navn.casefold().replace("é", "e").replace("è", "e")
    navn = "".join(c for c in unicodedata.normalize("NFC", navn) if c.isalnum() or c in "æøå")
    return navn


def parse_havnens_spisesteder(html: str) -> list[str]:
    """Navnene i afsnittet "Caféer & Restauranter" på havnens side."""
    soup = BeautifulSoup(html, "html.parser")
    overskrift = next((h for h in soup.find_all("h1") if "Restauranter" in h.get_text()), None)
    if overskrift is None:
        return []
    navne = []
    for el in overskrift.find_all_next(["h1", "h2"]):
        if el.name == "h1":
            break
        navn = el.get_text(" ", strip=True)
        if navn:
            navne.append(navn)
    return navne


def nye_spisesteder(fundne: list[str], kendte: list[Spisested]) -> list[str]:
    kendte_norm = [_norm(s.navn) for s in kendte]
    nye = []
    for navn in fundne:
        n = _norm(navn)
        if not any(n.startswith(k) or k.startswith(n) for k in kendte_norm if k):
            nye.append(navn)
    return nye


def find_nye_spisesteder(db: Database, html: str | None = None) -> list[str]:
    if html is None:
        html = hent(HAVN_SPISESTEDER_URL)
    nye = nye_spisesteder(parse_havnens_spisesteder(html), load_spisesteder())
    db.marker_koert(KOERSEL_FIND_NYE)
    return nye


# --- 2. Ugens spisested ----------------------------------------------------------

def sidst_omtalt(db: Database) -> dict[str, datetime]:
    """Hvornår hvert spisested sidst har fået et udkast (uanset status)."""
    resultat: dict[str, datetime] = {}
    for a in db.get_articles():
        for t in a.tags:
            if t.startswith(TAG_PREFIX):
                sid = t[len(TAG_PREFIX):]
                if sid not in resultat or a.oprettet > resultat[sid]:
                    resultat[sid] = a.oprettet
    return resultat


def vaelg_spisested(db: Database, steder: list[Spisested], samme_igen_efter_dage: int,
                    nu: datetime | None = None) -> Spisested | None:
    """Det sted, der aldrig har været med, ellers det der har ventet længst.
    Steder omtalt inden for `samme_igen_efter_dage` springes over."""
    nu = nu or datetime.now()
    omtalt = sidst_omtalt(db)
    kandidater = [s for s in steder
                  if s.id not in omtalt or nu - omtalt[s.id] >= timedelta(days=samme_igen_efter_dage)]
    if not kandidater:
        return None
    # Aldrig omtalt først (i listens rækkefølge), derefter ældste omtale
    return min(kandidater, key=lambda s: (s.id in omtalt, omtalt.get(s.id, datetime.min)))


class SpisestedUdkast(BaseModel):
    overskrift: str = Field(description="Begynder med 'Ugens spisested:'")
    resume: str = Field(description="1-2 sætninger")
    broedtekst: str = Field(description="Præsentation af stedet ud fra kildematerialet. 3-6 sætninger")
    praktisk: str = Field(description="Adresse, åbningstider, prisniveau, booking. Kun hvad kilden siger")
    tjekliste: list[str] = Field(description="Ting redaktøren skal undersøge eller smage ved besøget")
    kilder: list[str]
    usikkerheder: str


def skriv_spisested_udkast(client: anthropic.Anthropic, sted: Spisested, sidetekst: str) -> SpisestedUdkast:
    prompt = (
        dagens_dato() + "\n\n"
        "Skriv et udkast til Gulvmåttens faste rubrik 'Ugens spisested' om stedet herunder.\n\n"
        "Du har ikke besøgt stedet og kan ikke smage maden. Skriv derfor ingen vurdering af mad, "
        "service eller stemning, og ingen karakter. Beskriv kun, hvad stedet selv oplyser: hvad de "
        "serverer, hvornår de har åbent, beliggenhed, eventuelle faste arrangementer. Redaktøren besøger "
        "stedet og skriver selv anmeldelsen bagefter. Lav en tjekliste med 3-6 konkrete ting, redaktøren "
        "skal se efter eller spørge om.\n\n"
        f"Navn: {sted.navn}\nAdresse: {sted.adresse or 'ukendt'}\nHjemmeside: {sted.web or 'ingen'}\n"
        f"Facebook: {sted.facebook or 'ingen'}\nRedaktionens note: {sted.note or 'ingen'}\n\n"
        f"Tekst fra stedets hjemmeside:\n{sidetekst or '(kunne ikke hentes)'}"
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4000,
        output_config={"effort": "medium"},
        system=SYSTEM_REDAKTION,
        messages=[{"role": "user", "content": prompt}],
        output_format=SpisestedUdkast,
    )
    return response.parsed_output


def _hent_billede(url: str) -> str:
    try:
        return _og_image(BeautifulSoup(hent(url), "html.parser"), url)
    except Exception:  # noqa: BLE001
        return ""


def lav_ugens_spisested(db: Database, client: anthropic.Anthropic, steder: list[Spisested] | None = None,
                        hent_tekst=hent_artikeltekst, hent_billede=_hent_billede) -> int | None:
    """Lav et udkast om næste spisested. Returnerer artiklens id, eller None
    hvis alle steder er omtalt for nylig."""
    indst = mad_indstillinger()
    sted = vaelg_spisested(db, steder if steder is not None else load_spisesteder(),
                           indst["samme_sted_igen_efter_dage"])
    if sted is None:
        db.marker_koert(KOERSEL_UGENS)
        return None
    sidetekst = hent_tekst(sted.web) if sted.web else ""
    udkast = skriv_spisested_udkast(client, sted, sidetekst)

    broedtekst = udkast.broedtekst.strip()
    if udkast.praktisk.strip():
        broedtekst += "\n\nPraktisk: " + udkast.praktisk.strip()
    broedtekst += ("\n\nRedaktørens dom: [Udfyldes efter besøg. Skriv hvad du spiste, hvad det kostede, "
                   "og giv en karakter fra 1 til 6 gulvmåtter.]")
    billede = hent_billede(sted.web) if sted.web else ""
    kilder = list(dict.fromkeys([u for u in [sted.web, sted.facebook] if u] + udkast.kilder))
    article = Article(
        overskrift=udkast.overskrift,
        resume=udkast.resume,
        broedtekst=broedtekst,
        kategori="mad",
        by="Hundested",
        tags=[f"{TAG_PREFIX}{sted.id}", "ugens-spisested"],
        kilder=kilder,
        usikkerheder=udkast.usikkerheder,
        risiko=RiskLevel.HIGH,
        status=ReviewStatus.NEEDS_REVIEW,
        redaktoer_note="Tjekliste til besøget:\n" + "\n".join(f"- {t}" for t in udkast.tjekliste)
                       + ("\n\nBilledet er fra stedets egen hjemmeside. Spørg om lov, eller tag selv et."
                          if billede else ""),
        billede_url=billede,
        billede_kredit=f"Foto: {sted.navn}" if billede else "",
    )
    artikel_id = db.save_article(article)
    db.marker_koert(KOERSEL_UGENS)
    return artikel_id


def karakter(article: Article) -> int | None:
    """Karakteren (1-6 gulvmåtter) fra tagget `karakter:N`, som redaktøren sætter."""
    for t in article.tags:
        m = re.fullmatch(r"karakter:([1-6])", t)
        if m:
            return int(m.group(1))
    return None
