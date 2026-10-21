"""Den agentiske redaktion: vurdering, research og artikeludkast.

Hvert nyt eller ændret RawItem går gennem:

0. Alderstjek  Opslag med en dato mere end MAX_ALDER_DAGE tilbage springes
               over uden at spørge Claude. Det koster ingenting.
1. Vurdering   Claude giver en score 0-10 for lokal nyhedsværdi, en kategori,
               et risikoniveau og en kort begrundelse. Gemmes i tabellen
               `assessments`, så vi ikke vurderer det samme to gange.
2. Research    Vi henter den fulde artikelside og finder andre opslag i
               databasen, der ligner (samme ord i titlen). Alt gives videre.
3. Udkast      Claude skriver overskrift, resumé, brødtekst, praktiske
               detaljer, kilder og en liste over usikkerheder.
4. Aflevering  Udkastet gemmes som Article med status needs_review.
               Er autogodkendelse slået til i redaktionsværktøjet, publiceres
               det med det samme. Ellers venter det på redaktøren.

Reglerne i docs/workflow.md er skrevet direkte ind i systemprompten herunder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import anthropic
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .datoer import dansk_dato, tolk_dato
from .db import Database
from .fetch import hent
from .models import Article, RawItem, ReviewStatus, RiskLevel, Source
from .publicering import autogodkend, publicer

MODEL = "claude-opus-5-5"
SCORE_TAERSKEL = 5  # Opslag med lavere score bliver ikke til artikler
MAX_ALDER_DAGE = 14  # Ældre opslag springes over uden et API-kald

SYSTEM_REDAKTION = """Du er redaktionssekretær på Gulvmåtten, et lokalt netmedie for Glostrup og Brøndby på Københavns Vestegn.

Mediets regler, som du altid overholder:
1. Ingen opdigtede fakta. Alle tal, navne, datoer, steder, priser og citater skal stå i det kildemateriale, du får. Kan noget ikke bekræftes, skriver du det under usikkerheder, ikke i artiklen.
2. Kilde på alt. Du angiver altid de URL'er, du bygger på.
3. Korrekt før hurtigt. Modstridende eller uklare oplysninger giver ikke en artikel, men en note til redaktøren.
4. Høj risiko kræver menneske. Politik, kriminalitet, sundhed, navngivne privatpersoner og kontroversielle sager får risiko "high".
5. Ingen private persondata. Kun navne, der optræder i en offentlig kilde med redaktionel relevans, fx en borgmester, en forfatter eller en foredragsholder.
6. Sproget er dansk, neutralt, præcist og letlæst. Korte sætninger. Ingen reklamesprog, ingen udråbstegn, ingen vurderende tillægsord.

Sådan skriver du et udkast:
7. Udkastet må aldrig modsige sin egen usikkerhedsliste. Står en oplysning som usikker, må artiklen ikke fremstille den som sikker. Læs udkastet igennem til sidst og ret det, hvis artikel og usikkerheder ikke passer sammen.
8. Usikre oplysninger udelader du helst. Er oplysningen vigtig for læseren, skriver du den forsigtigt og tydeligt med kilde, fx "Ifølge biblioteket ..." eller "Biblioteket oplyser ikke, hvornår ...". Gæt aldrig.
9. Resuméet er artiklens indledning. Brødtekstens første afsnit må ikke gentage resuméet, hverken ordret eller med andre ord. Brødteksten fortsætter, hvor resuméet slap, med nye oplysninger.
10. Praktiske oplysninger skrives med ét punkt pr. linje, fx "Hvornår: ...", "Hvor: ...", "Pris: ...", "Tilmelding: ...". Aldrig flere punkter på samme linje.
11. Usikkerhedslisten er en tjekliste til redaktøren. Den indeholder kun det, redaktøren skal undersøge eller tage stilling til, før artiklen kan udgives. Ét punkt pr. linje, hvert punkt indledt med "- ". Skriv ikke ting, der er i orden, ting du har bekræftet, eller forklaringer på, hvad du har udeladt af sproglige grunde.

Kategorier: arrangementer, kommune, kultur, sport, foreningsliv, byudvikling, skole-og-institution, trafik.
"""


class Vurdering(BaseModel):
    """Claudes vurdering af ét opslag."""

    score: int = Field(ge=0, le=10, description="Lokal nyhedsværdi 0-10 for borgere i Glostrup/Brøndby")
    kategori: str
    by: str = Field(description="Glostrup, Brøndby eller Begge")
    risiko: str = Field(description="low, medium eller high")
    er_arrangement: bool
    begrundelse: str = Field(description="1-2 sætninger")


class Udkast(BaseModel):
    """Claudes artikeludkast."""

    overskrift: str
    resume: str = Field(description="Indledningen: 1-2 sætninger")
    broedtekst: str = Field(description="3-6 sætninger, almindelig tekst, afsnit adskilt med tom linje. "
                                        "Første afsnit må ikke gentage resuméet")
    praktisk: str = Field(description="Hvornår, hvor, pris, tilmelding. Ét punkt pr. linje, adskilt med linjeskift. "
                                      "Tom streng hvis ikke relevant")
    tags: list[str]
    kilder: list[str] = Field(description="URL'er artiklen bygger på")
    usikkerheder: str = Field(description="Kun det redaktøren skal tjekke, ét punkt pr. linje indledt med '- '. "
                                          "Må ikke modsiges af artiklen. Tom streng hvis intet")
    risiko: str = Field(description="low, medium eller high")


@dataclass
class RedaktionResultat:
    raw_item_id: int
    titel: str
    score: int
    kategori: str
    artikel_id: int | None = None
    sprunget_over: str = ""
    publiceret: bool = False


# --- Hjælpere ----------------------------------------------------------------

STOPORD = {"og", "i", "på", "til", "for", "med", "af", "om", "en", "et", "der", "den", "det", "de",
           "er", "som", "fra", "ved", "har", "kan", "skal", "nu", "ny", "nye", "hos", "mod"}


def noegleord(titel: str) -> set[str]:
    ord_ = re.findall(r"[a-zæøåA-ZÆØÅ0-9]{3,}", titel.lower())
    return {o for o in ord_ if o not in STOPORD}


def find_relaterede(db: Database, item: RawItem, max_antal: int = 5) -> list[RawItem]:
    """Andre opslag med mindst to fælles nøgleord i titlen."""
    mine = noegleord(item.titel)
    if len(mine) < 2:
        return []
    kandidater = []
    for andet in db.get_raw_items(limit=2000):
        if andet.id == item.id:
            continue
        faelles = mine & noegleord(andet.titel)
        if len(faelles) >= 2:
            kandidater.append((len(faelles), andet))
    kandidater.sort(key=lambda t: t[0], reverse=True)
    return [k for _, k in kandidater[:max_antal]]


def hent_artikeltekst(url: str, max_tegn: int = 6000) -> str:
    """Hent brødteksten fra en artikelside. Fejler stille med tom streng."""
    try:
        html = hent(url)
    except Exception:  # noqa: BLE001
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body
    if not main:
        return ""
    tekst = main.get_text("\n", strip=True)
    tekst = re.sub(r"\n{3,}", "\n\n", tekst)
    return tekst[:max_tegn]


def _risiko(v: str) -> RiskLevel:
    try:
        return RiskLevel(v.lower().strip())
    except ValueError:
        return RiskLevel.MEDIUM


def _item_blok(item: RawItem, source: Source | None, fuld_tekst: str = "") -> str:
    kilde = f"{source.navn} (tillid {source.tillid}/5, {source.by})" if source else item.source_id
    dele = [
        f"Kilde: {kilde}",
        f"URL: {item.url}",
        f"Titel: {item.titel}",
        f"Dato som kilden skriver den: {item.dato_tekst or 'ukendt'}",
        f"Resumé fra kilden: {item.tekst or '(intet)'}",
    ]
    if fuld_tekst:
        dele.append(f"Fuld tekst fra siden:\n{fuld_tekst}")
    return "\n".join(dele)


# --- Trin 1: vurdering --------------------------------------------------------

def vurder(client: anthropic.Anthropic, item: RawItem, source: Source | None,
           nu: datetime | None = None) -> Vurdering:
    prompt = (
        f"Dagens dato er {dansk_dato(nu or datetime.now())}. Arrangementer, der allerede har fundet sted, "
        "og nyheder, der er mere end to uger gamle, får score 0.\n\n"
        "Vurdér dette opslag. Giv en score for lokal nyhedsværdi for borgere i Glostrup og Brøndby, "
        "hvor 0 er irrelevant eller ren rutine (fx en enkelt landzonetilladelse, en kampopstilling, "
        "en selskabsmeddelelse) og 10 er noget, de fleste i byen vil vide. Arrangementer, der er åbne for "
        "alle, ligger typisk på 5-7. Kommunale beslutninger med bred betydning 7-9.\n\n"
        + _item_blok(item, source)
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        system=SYSTEM_REDAKTION,
        messages=[{"role": "user", "content": prompt}],
        output_format=Vurdering,
    )
    return response.parsed_output


# --- Trin 3: udkast -----------------------------------------------------------

def skriv_udkast(client: anthropic.Anthropic, item: RawItem, source: Source | None,
                 fuld_tekst: str, relaterede: list[RawItem], vurdering: Vurdering) -> Udkast:
    dele = [
        "Skriv et artikeludkast ud fra materialet herunder. Brug kun oplysninger, der står i materialet. "
        f"Redaktionens vurdering: kategori {vurdering.kategori}, risiko {vurdering.risiko}.\n",
        "=== HOVEDKILDE ===",
        _item_blok(item, source, fuld_tekst),
    ]
    if relaterede:
        dele.append("\n=== ANDRE OPSLAG, DER MULIGVIS HANDLER OM DET SAMME ===")
        for r in relaterede:
            dele.append(_item_blok(r, None) + "\n")
    dele.append(
        "\nHvis de andre opslag modsiger hovedkilden, så skriv det under usikkerheder. "
        "Hvis opslaget er en gentagelse af et tilbagevendende arrangement (fx ugentlig IT-café), "
        "så skriv en kort servicenotits frem for en nyhedsartikel."
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4000,
        output_config={"effort": "medium"},
        system=SYSTEM_REDAKTION,
        messages=[{"role": "user", "content": "\n".join(dele)}],
        output_format=Udkast,
    )
    return response.parsed_output


# --- Samlet arbejdsgang -------------------------------------------------------

def behandl_item(db: Database, client: anthropic.Anthropic, item: RawItem,
                 sources: dict[str, Source], taerskel: int = SCORE_TAERSKEL,
                 hent_tekst=hent_artikeltekst, nu: datetime | None = None) -> RedaktionResultat:
    """Kør hele pipelinen for ét opslag. `hent_tekst` og `nu` kan byttes ud i tests."""
    nu = nu or datetime.now()
    source = sources.get(item.source_id)
    dato = tolk_dato(item.dato_tekst)
    if dato and dato < nu - timedelta(days=MAX_ALDER_DAGE):
        begrundelse = f"For gammelt: dateret {dansk_dato(dato, ugedag=False)}."
        db.save_assessment(item.id, 0, "", "low", begrundelse)
        return RedaktionResultat(raw_item_id=item.id, titel=item.titel, score=0, kategori="",
                                 sprunget_over=begrundelse)

    vurdering = vurder(client, item, source, nu)
    db.save_assessment(item.id, vurdering.score, vurdering.kategori, vurdering.risiko, vurdering.begrundelse)
    resultat = RedaktionResultat(raw_item_id=item.id, titel=item.titel,
                                 score=vurdering.score, kategori=vurdering.kategori)
    if vurdering.score < taerskel:
        resultat.sprunget_over = f"score {vurdering.score} under tærskel {taerskel}"
        return resultat

    fuld_tekst = hent_tekst(item.url)
    relaterede = find_relaterede(db, item)
    udkast = skriv_udkast(client, item, source, fuld_tekst, relaterede, vurdering)

    kilder = list(dict.fromkeys([item.url] + udkast.kilder))
    # Højeste risiko fra vurdering og udkast vinder
    niveauer = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
    risiko = max(_risiko(vurdering.risiko), _risiko(udkast.risiko), key=niveauer.index)

    article = Article(
        overskrift=udkast.overskrift,
        resume=udkast.resume,
        broedtekst=udkast.broedtekst.strip(),
        praktisk=udkast.praktisk.strip(),
        er_arrangement=vurdering.er_arrangement,
        # Datoen tages fra kilden, ikke fra Claude, så den ikke kan blive gættet
        arrangement_start=dato if vurdering.er_arrangement else None,
        kategori=vurdering.kategori,
        by=vurdering.by if vurdering.by != "Begge" else "Glostrup og Brøndby",
        tags=udkast.tags,
        kilder=kilder,
        usikkerheder=udkast.usikkerheder,
        risiko=risiko,
        status=ReviewStatus.NEEDS_REVIEW,
        raw_item_ids=[item.id] + [r.id for r in relaterede],
        oprettet=datetime.now(),
    )
    resultat.artikel_id = db.save_article(article)
    if autogodkend(db):
        publicer(db, article)
        resultat.publiceret = True
    return resultat


def koer_redaktion(db: Database, client: anthropic.Anthropic, limit: int = 10,
                   taerskel: int = SCORE_TAERSKEL, source_id: str | None = None) -> list[RedaktionResultat]:
    """Behandl de nyeste opslag, der endnu ikke er vurderet."""
    sources = {s.id: s for s in db.get_sources(kun_aktive=False)}
    resultater = []
    for item in db.get_unassessed_raw_items(limit=limit, source_id=source_id):
        resultater.append(behandl_item(db, client, item, sources, taerskel=taerskel))
    return resultater
