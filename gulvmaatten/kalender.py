"""Kalenderen: "Det sker i Hundested".

Claude læser opslag og sider og trækker de konkrete arrangementer ud: titel,
tid, sted, pris og tilmelding. To slags opslag gennemgås:

- Alle opslag fra kilder med `kalender: true` (biblioteket, spisestedernes
  eventsider, surfcentrets kalender). En side kan rumme mange arrangementer.
- Opslag fra andre kilder, som redaktionen har vurderet som et arrangement.

Kalenderen er service, ikke journalistik: et arrangement kommer med, selv om
det ikke er en nyhed. Det kræver derfor ikke en redaktørs godkendelse, men
agenten må kun bruge oplysninger, der står i kilden, og hvert arrangement
linker til kilden. Når en kildes side ændrer sig, læses den igen, og
arrangementerne fra den erstattes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import anthropic
from pydantic import BaseModel, Field

from .agent import MODEL, SYSTEM_REDAKTION, dagens_dato, hent_artikeltekst
from .db import Database
from .models import LOKALE_STEDER, Event, RawItem, Source

HORISONT_DAGE = 90


class Arrangement(BaseModel):
    titel: str = Field(description="Kort og neutral, uden emojis og udråbstegn")
    start: str = Field(description="ISO 8601, fx 2026-10-30T16:00. Kun dato (2026-10-30) hvis klokkeslæt mangler")
    slut: str = Field(description="ISO 8601 eller tom streng")
    sted: str = Field(description="Sted og evt. adresse, som kilden skriver det")
    by: str = Field(description="Hundested, Frederiksværk eller anden by")
    pris: str = Field(description="Som kilden skriver det, fx 'Gratis' eller '75 kr.'. Tom hvis ukendt")
    tilmelding: str = Field(description="Hvordan man tilmelder sig eller køber billet. Tom hvis ukendt")
    arrangoer: str
    beskrivelse: str = Field(description="Én neutral sætning om, hvad det er")
    url: str = Field(description="Link til arrangementet hvis kilden har et, ellers kildens URL")
    aflyst: bool


class Udtraek(BaseModel):
    arrangementer: list[Arrangement]


@dataclass
class KalenderResultat:
    raw_item_id: int
    titel: str
    antal: int


def _dt(v: str) -> datetime | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", ""))
    except ValueError:
        return None


def udtraek_arrangementer(client: anthropic.Anthropic, item: RawItem, source: Source | None,
                          tekst: str) -> Udtraek:
    prompt = (
        f"{dagens_dato()}\n\n"
        "Find de konkrete arrangementer i materialet herunder, som er åbne for offentligheden og finder sted "
        f"fra i dag og op til {HORISONT_DAGE} dage frem. Spring over, hvad der allerede er sket, kurser og "
        "produkter uden fast dato, udlejning og lukkede medlemsarrangementer.\n"
        "Tilbagevendende arrangementer (fx 'hver fredag') skrives som én række pr. dato, dog højst de næste "
        "fire gange. Står der kun dag og måned, så brug det nærmeste kommende år.\n"
        "Brug kun oplysninger, der står i materialet. Gæt aldrig et klokkeslæt, en pris eller et sted. "
        "Er der ingen arrangementer, så returnér en tom liste.\n\n"
        f"Kilde: {source.navn if source else item.source_id}\n"
        f"URL: {item.url}\n"
        f"Titel: {item.titel}\n"
        f"Dato som kilden skriver den: {item.dato_tekst or 'ukendt'}\n"
        f"Tekst:\n{tekst}"
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=6000,
        output_config={"effort": "low"},
        system=SYSTEM_REDAKTION,
        messages=[{"role": "user", "content": prompt}],
        output_format=Udtraek,
    )
    return response.parsed_output


def behandl_kalender_item(db: Database, client: anthropic.Anthropic, item: RawItem, source: Source | None,
                          hent_tekst=hent_artikeltekst, nu: datetime | None = None) -> KalenderResultat:
    nu = nu or datetime.now()
    tekst = item.tekst
    # Korte opslag (fx et RSS-resumé) suppleres med den fulde side
    if len(tekst) < 600 and item.url and (not source or item.url != source.url):
        tekst = (tekst + "\n\n" + hent_tekst(item.url)).strip()
    udtraek = udtraek_arrangementer(client, item, source, tekst)
    events = []
    for a in udtraek.arrangementer:
        start = _dt(a.start)
        if start is None:
            continue
        slut = _dt(a.slut)
        if (slut or start).date() < nu.date():
            continue
        events.append(Event(
            titel=a.titel.strip(), start=start, slut=slut, sted=a.sted.strip(), by=a.by.strip() or "Hundested",
            pris=a.pris.strip(), tilmelding=a.tilmelding.strip(), arrangoer=a.arrangoer.strip(),
            aflyst=a.aflyst, url=a.url.strip() or item.url, beskrivelse=a.beskrivelse.strip(),
            billede_url=item.billede_url if source and source.billeder else "",
            source_id=item.source_id,
        ))
    db.erstat_events(item.id, events)
    db.marker_kalender_udtraek(item)
    return KalenderResultat(raw_item_id=item.id, titel=item.titel, antal=len(events))


def kamp_event(item: RawItem) -> Event:
    """En kamp fra et kampprogram har allerede dato, hold og bane. Den kommer
    direkte i kalenderen uden at Claude skal læse den."""
    d = item.data
    hold = f" ({d['hold']})" if d.get("hold") and d["hold"].lower() != "senior" else ""
    return Event(
        titel=f"Fodbold: {d['hjemme']} – {d['ude']}{hold}", start=datetime.fromisoformat(d["start"]),
        sted=d.get("bane", ""), by="Hundested", arrangoer=d.get("hjemme", ""), url=item.url,
        beskrivelse=d.get("raekke", ""), source_id=item.source_id,
    )


def koer_kalender(db: Database, client: anthropic.Anthropic | None, limit: int = 30) -> list[KalenderResultat]:
    sources = {s.id: s for s in db.get_sources(kun_aktive=False)}
    resultater = []
    for item in db.opslag_til_kalender(limit=limit):
        if item.data.get("kamp"):
            db.erstat_events(item.id, [kamp_event(item)])
            db.marker_kalender_udtraek(item)
            resultater.append(KalenderResultat(raw_item_id=item.id, titel=item.titel, antal=1))
        elif client is not None:
            resultater.append(behandl_kalender_item(db, client, item, sources.get(item.source_id)))
    return resultater


def i_hundested(e: Event) -> bool:
    """Kalenderen viser Hundested. Arrangementer i resten af kommunen springes over."""
    tekst = f"{e.by} {e.sted}".lower()
    return not e.by or any(sted in tekst for sted in LOKALE_STEDER)


def _noegle(e: Event) -> tuple:
    titel = "".join(c for c in e.titel.lower() if c.isalnum())[:15]
    return (e.start.date(), titel)


def ryd_dubletter(events: list[Event]) -> list[Event]:
    """Samme arrangement kan stå flere steder (fx på bibliotekets liste og på
    arrangementets egen side). Behold den version med flest oplysninger."""
    def fylde(e: Event) -> int:
        return (e.start.hour != 0 or e.start.minute != 0) * 4 + bool(e.sted) * 2 + bool(e.pris) + bool(e.beskrivelse)

    bedste: dict[tuple, Event] = {}
    for e in events:
        k = _noegle(e)
        if k not in bedste or fylde(e) > fylde(bedste[k]):
            bedste[k] = e
    return sorted(bedste.values(), key=lambda e: (e.start, e.titel))


def kalender_for(db: Database, fra: datetime, dage: int = HORISONT_DAGE) -> list[Event]:
    from datetime import timedelta

    # Hele dage: fra midnat i dag til midnat efter sidste dag
    dagstart = datetime.combine(fra.date(), datetime.min.time())
    events = db.kommende_events(dagstart, dagstart + timedelta(days=dage + 1))
    return ryd_dubletter([e for e in events if i_hundested(e)])


def fremhaevede(events: list[Event], antal: int = 2) -> list[Event]:
    """Til forsidens topstrimmel: de næste arrangementer, der ikke gentager sig."""
    titler: dict[str, int] = {}
    for e in events:
        titler[_noegle(e)[1]] = titler.get(_noegle(e)[1], 0) + 1
    enkelte = [e for e in events if titler[_noegle(e)[1]] == 1 and not e.aflyst]
    return enkelte[:antal]
