"""Den agentiske redaktion: vurdering, research og artikeludkast.

Hvert nyt eller ændret RawItem går gennem:

1. Vurdering   Claude giver en score 0-10 for lokal nyhedsværdi, en kategori,
               et risikoniveau og en kort begrundelse. Gemmes i tabellen
               `assessments`, så vi ikke vurderer det samme to gange.
2. Research    Vi henter den fulde artikelside og finder andre opslag i
               databasen, der ligner (samme ord i titlen). Alt gives videre.
3. Udkast      Claude skriver overskrift, resumé, brødtekst, praktiske
               detaljer, kilder og en liste over usikkerheder.
4. Aflevering  Udkastet gemmes som Article med status needs_review.
               Intet publiceres automatisk.

Reglerne i docs/workflow.md er skrevet direkte ind i systemprompten herunder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import anthropic
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .db import Database
from .fetch import hent
from .models import Article, RawItem, ReviewStatus, RiskLevel, Source, SourceType

MODEL = "claude-opus-5-5"
SCORE_TAERSKEL = 4  # Opslag med lavere score bliver ikke til artikler

SYSTEM_REDAKTION = """Du er redaktionssekretær på Gulvmåtten, et lokalt netmedie for Hundested i Halsnæs Kommune. Navnet kommer fra den gamle gratisavis i Hundested, som mange brugte som gulvmåtte.

Stofområdet er Hundested med Lynæs, Kikhavn, Torup og Dyssekilde. Havnen, Kulturkajen, Lynæs Surfcenter og Folkely Festival er byens kulturelle knudepunkter. Futsal og sejlsport fylder i sportsdækningen.

Frederiksværk og resten af kommunen er ikke vores stofområde. Historier derfra bringes kun, hvis de er usædvanlige, og så under kategorien "udlandsstof", hvor overskriften gerne må have et tørt glimt i øjet (fx "Udlandsstof: ..."). Kommunale beslutninger, der gælder hele Halsnæs, er almindeligt kommunestof.

Mediets regler, som du altid overholder:
1. Ingen opdigtede fakta. Alle tal, navne, datoer, steder, priser og citater skal stå i det kildemateriale, du får. Kan noget ikke bekræftes, skriver du det under usikkerheder, ikke i artiklen.
2. Kilde på alt. Du angiver altid de URL'er, du bygger på.
3. Korrekt før hurtigt. Modstridende eller uklare oplysninger giver ikke en artikel, men en note til redaktøren.
4. Høj risiko kræver menneske. Politik, kriminalitet, sundhed, navngivne privatpersoner og kontroversielle sager får risiko "high".
5. Ingen private persondata. Kun navne, der optræder i en offentlig kilde med redaktionel relevans, fx en borgmester, en forfatter eller en foredragsholder.
6. Sproget er dansk, neutralt, præcist og letlæst. Korte sætninger. Ingen reklamesprog, ingen udråbstegn, ingen vurderende tillægsord. Undtagelsen er udlandsstof, hvor en let ironisk tone er tilladt i overskriften.
7. Andre medier og opslag fra privatpersoner i Facebook-grupper er tips, ikke kilder. Privatpersoner i grupper nævnes aldrig ved navn. En historie fra Frederiksborg Amts Avis eller Halsnæs Avis må ikke skrives om. Den kræver en selvstændig kilde (kommunen, arrangøren, klubben). Har vi kun avisens version, skriver du det under usikkerheder.

Kategorier: nyheder, havnen, kultur, folkely, sport, mad, arrangementer, kommune, foreningsliv, byudvikling, trafik, udlandsstof.
"""


class Vurdering(BaseModel):
    """Claudes vurdering af ét opslag."""

    score: int = Field(ge=0, le=10, description="Lokal nyhedsværdi 0-10 for borgere i Hundested")
    kategori: str
    by: str = Field(description="Hundested, Halsnæs (hele kommunen) eller Frederiksværk")
    risiko: str = Field(description="low, medium eller high")
    er_arrangement: bool
    begrundelse: str = Field(description="1-2 sætninger")


class Udkast(BaseModel):
    """Claudes artikeludkast."""

    overskrift: str
    resume: str = Field(description="1-2 sætninger")
    broedtekst: str = Field(description="3-6 sætninger, almindelig tekst, afsnit adskilt med tom linje")
    praktisk: str = Field(description="Hvornår, hvor, pris, tilmelding. Tom streng hvis ikke relevant")
    tags: list[str]
    kilder: list[str] = Field(description="URL'er artiklen bygger på")
    usikkerheder: str = Field(description="Hvad der ikke kunne bekræftes. Tom streng hvis intet")
    risiko: str = Field(description="low, medium eller high")


@dataclass
class RedaktionResultat:
    raw_item_id: int
    titel: str
    score: int
    kategori: str
    artikel_id: int | None = None
    sprunget_over: str = ""


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


def vaelg_billede(item: RawItem, source: Source | None) -> dict:
    """Billede til artiklen: kildens eget billede, hvis kilden tillader det.
    Krediteringen følger altid med."""
    if not item.billede_url or not source or not source.billeder:
        return {"billede_url": "", "billede_kredit": ""}
    return {"billede_url": item.billede_url, "billede_kredit": f"Foto: {source.navn}"}


def _risiko(v: str) -> RiskLevel:
    try:
        return RiskLevel(v.lower().strip())
    except ValueError:
        return RiskLevel.MEDIUM


def _item_blok(item: RawItem, source: Source | None, fuld_tekst: str = "") -> str:
    kilde = f"{source.navn} (tillid {source.tillid}/5, {source.by})" if source else item.source_id
    dele = [
        f"Kilde: {kilde}",
        f"Om kilden: {source.regler.strip()}" if source and source.regler else "",
        f"URL: {item.url}",
        f"Titel: {item.titel}",
        f"Dato som kilden skriver den: {item.dato_tekst or 'ukendt'}",
        f"Resumé fra kilden: {item.tekst or '(intet)'}",
    ]
    if fuld_tekst:
        dele.append(f"Fuld tekst fra siden:\n{fuld_tekst}")
    return "\n".join(d for d in dele if d)


# --- Trin 1: vurdering --------------------------------------------------------

MAANEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
            "september", "oktober", "november", "december"]


def dagens_dato(nu: datetime | None = None) -> str:
    """Claude kender ikke dagens dato. Uden den kan et arrangement fra sidste
    sommer ligne et kommende."""
    nu = nu or datetime.now()
    return f"I dag er det {nu.day}. {MAANEDER[nu.month - 1]} {nu.year}."


def vurder(client: anthropic.Anthropic, item: RawItem, source: Source | None) -> Vurdering:
    prompt = (
        dagens_dato() + " Arrangementer, der allerede har fundet sted, har score 0, medmindre de er "
        "en nyhed i sig selv. Står der kun dag og måned, så antag det nærmeste år og tjek, om datoen er passeret.\n\n"
        "Vurdér dette opslag. Giv en score for lokal nyhedsværdi for borgere i Hundested, "
        "hvor 0 er irrelevant eller ren rutine (fx en kursusbeskrivelse, en udlejningsvare, en kampopstilling, "
        "en selskabsmeddelelse, et overstået arrangement) og 10 er noget, de fleste i byen vil vide. "
        "Arrangementer i Hundested, der er åbne for alle, ligger typisk på 5-7. Kommunale beslutninger "
        "med betydning for Hundested 7-9. Nyheder fra andre kommuner end Halsnæs er 0. "
        "Almindelige nyheder fra Frederiksværk er højst 3; kun det usædvanlige kan blive udlandsstof.\n\n"
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
        dagens_dato() + " Skriv ikke om noget, der er overstået, som om det ligger forude.\n",
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
                 hent_tekst=hent_artikeltekst) -> RedaktionResultat:
    """Kør hele pipelinen for ét opslag. `hent_tekst` kan byttes ud i tests."""
    source = sources.get(item.source_id)
    vurdering = vurder(client, item, source)
    db.save_assessment(item.id, vurdering.score, vurdering.kategori, vurdering.risiko, vurdering.begrundelse,
                       er_arrangement=vurdering.er_arrangement)
    resultat = RedaktionResultat(raw_item_id=item.id, titel=item.titel,
                                 score=vurdering.score, kategori=vurdering.kategori)
    # Kilder med særligt fokus (prioritet 3, fx Folkely) får en lavere tærskel
    if source and source.prioritet >= 3:
        taerskel -= 1
    if vurdering.score < taerskel:
        resultat.sprunget_over = f"score {vurdering.score} under tærskel {taerskel}"
        return resultat

    if source and source.kun_tip:
        # Andre mediers historier skrives ikke om, og borgeres opslag i Facebook-grupper
        # er ikke kilder. De bliver et tip til redaktøren.
        resultat.artikel_id = gem_tip(db, item, source, vurdering)
        return resultat

    fuld_tekst = hent_tekst(item.url)
    relaterede = find_relaterede(db, item)
    udkast = skriv_udkast(client, item, source, fuld_tekst, relaterede, vurdering)

    broedtekst = udkast.broedtekst
    if udkast.praktisk.strip():
        broedtekst += "\n\nPraktisk: " + udkast.praktisk.strip()
    kilder = list(dict.fromkeys([item.url] + udkast.kilder))
    # Højeste risiko fra vurdering og udkast vinder
    niveauer = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
    risiko = max(_risiko(vurdering.risiko), _risiko(udkast.risiko), key=niveauer.index)

    article = Article(
        overskrift=udkast.overskrift,
        resume=udkast.resume,
        broedtekst=broedtekst,
        kategori=vurdering.kategori,
        by=vurdering.by,
        tags=udkast.tags,
        kilder=kilder,
        usikkerheder=udkast.usikkerheder,
        risiko=risiko,
        status=ReviewStatus.NEEDS_REVIEW,
        raw_item_ids=[item.id] + [r.id for r in relaterede],
        oprettet=datetime.now(),
        **vaelg_billede(item, source),
    )
    resultat.artikel_id = db.save_article(article)
    return resultat


def gem_tip(db: Database, item: RawItem, source: Source, vurdering: Vurdering) -> int:
    """Et tip fra et andet medie. Vises for redaktøren, aldrig på hjemmesiden."""
    return db.save_article(Article(
        overskrift=f"Tip: {item.titel}",
        resume=vurdering.begrundelse,
        broedtekst=(f"Fundet hos {source.navn}. Det må ikke skrives om eller citeres. Find en selvstændig kilde, "
                    "fx kommunen, arrangøren eller klubben, før der skrives en artikel."),
        kategori=vurdering.kategori,
        by=vurdering.by,
        tags=["tip"],
        kilder=[item.url],
        risiko=RiskLevel.HIGH,
        status=ReviewStatus.NEEDS_REVIEW,
        raw_item_ids=[item.id],
    ))


def koer_redaktion(db: Database, client: anthropic.Anthropic, limit: int = 10,
                   taerskel: int = SCORE_TAERSKEL, source_id: str | None = None) -> list[RedaktionResultat]:
    """Behandl de nyeste opslag, der endnu ikke er vurderet."""
    sources = {s.id: s for s in db.get_sources(kun_aktive=False)}
    resultater = []
    # Boliglister og rene kalenderkilder vises i deres egne bokse og vurderes ikke som nyheder
    udelad = [s.id for s in sources.values() if s.type == SourceType.BOLIGSIDEN or s.kun_kalender]
    for item in db.get_unassessed_raw_items(limit=limit, source_id=source_id, udelad=udelad):
        resultater.append(behandl_item(db, client, item, sources, taerskel=taerskel))
    return resultater
