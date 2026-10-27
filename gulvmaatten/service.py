"""Faste servicehistorier, der skrives ud fra data, vi allerede har.

- "Det sker i Hundested i denne uge"  ud fra kalenderen
- "Boligmarkedet i Hundested"          ud fra Boligsidens liste for 3390

Teksten sættes sammen af en skabelon, ikke af Claude, så der kan ikke komme
oplysninger med, som ikke står i data. Som alt andet lægges de som udkast til
redaktøren.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from .db import Database
from .kalender import kalender_for
from .models import Article, Event, ReviewStatus, RiskLevel

KOERSEL_UGEN = "service-det-sker"
KOERSEL_BOLIG = "service-boligmarked"
BOLIG_KILDE = "boliger-til-salg"
MAANEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
            "september", "oktober", "november", "december"]
FLERTAL = {"Villa": "villaer", "Rækkehus": "rækkehuse", "Ejerlejlighed": "ejerlejligheder",
           "Fritidshus": "fritidshuse", "Andelsbolig": "andelsboliger", "Landejendom": "landejendomme",
           "Helårsgrund": "helårsgrunde", "Fritidsgrund": "fritidsgrunde", "Villalejlighed": "villalejligheder"}
UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]


def _kr(beloeb: float) -> str:
    return f"{int(round(beloeb)):,} kr.".replace(",", ".")


def _dag(d: datetime) -> str:
    return f"{UGEDAGE[d.weekday()]} {d.day}. {MAANEDER[d.month - 1]}"


def _linje(e: Event) -> str:
    tid = f" kl. {e.start:%H.%M}" if e.start.hour or e.start.minute else ""
    sted = f", {e.sted.split(',')[0]}" if e.sted else ""
    pris = f" ({e.pris})" if e.pris and len(e.pris) <= 24 else ""
    return f"- {_dag(e.start).capitalize()}{tid}: {e.titel}{sted}{pris}"


def det_sker_i_ugen(db: Database, nu: datetime | None = None, max_linjer: int = 12) -> int | None:
    nu = nu or datetime.now()
    events = [e for e in kalender_for(db, nu, dage=7) if not e.aflyst]
    if len(events) < 3:
        return None
    uge = nu.isocalendar().week
    steder = sorted({e.sted.split(",")[0] for e in events if e.sted})
    resume = (f"{len(events)} arrangementer i Hundested de næste syv dage, bl.a. "
              f"{', '.join(e.titel for e in events[:3])}.")
    broedtekst = (
        f"Gulvmåttens kalender har {len(events)} arrangementer i Hundested fra {_dag(nu)} og en uge frem. "
        f"De foregår blandt andet på {', '.join(steder[:4])}.\n\n"
        + "\n".join(_linje(e) for e in events[:max_linjer])
        + ("\n\nSe hele kalenderen på forsiden." if len(events) > max_linjer else "")
        + "\n\nTjek tid og pris hos arrangøren, før du går."
    )
    kilder = list(dict.fromkeys(e.url for e in events[:max_linjer] if e.url))
    a = Article(
        overskrift=f"Det sker i Hundested i uge {uge}",
        resume=resume, broedtekst=broedtekst, kategori="arrangementer", by="Hundested",
        tags=["service", f"det-sker-uge-{uge}"], kilder=kilder, risiko=RiskLevel.LOW,
        status=ReviewStatus.NEEDS_REVIEW,
        redaktoer_note="Skrevet automatisk ud fra kalenderen. Tjek, at intet er aflyst.",
        billede_url=next((e.billede_url for e in events if e.billede_url), ""),
    )
    if a.billede_url:
        kilde = db.get_source(next(e.source_id for e in events if e.billede_url == a.billede_url))
        a.billede_kredit = f"Foto: {kilde.navn}" if kilde else ""
    artikel_id = db.save_article(a)
    db.marker_koert(KOERSEL_UGEN, nu)
    return artikel_id


def boligmarkedet(db: Database, nu: datetime | None = None) -> int | None:
    nu = nu or datetime.now()
    # Kun boliger, der stadig var på listen ved seneste hentning
    alle = db.get_raw_items(source_id=BOLIG_KILDE, limit=1000)
    if not alle:
        return None
    seneste = max(b.sidst_set for b in alle)
    boliger = [b for b in alle if b.data.get("pris") and (seneste - b.sidst_set) < timedelta(hours=2)]
    if len(boliger) < 5:
        return None
    nye = [b for b in boliger if (b.data.get("dage_til_salg") or 999) <= 7]
    priser = [b.data["pris"] for b in boliger]
    kvm = [b.data["pris"] / b.data["boligareal"] for b in boliger
           if b.data.get("boligareal") and b.data.get("type") in ("Villa", "Rækkehus", "Ejerlejlighed")]
    billigst = min(boliger, key=lambda b: b.data["pris"])
    dyrest = max(boliger, key=lambda b: b.data["pris"])
    typer: dict[str, int] = {}
    for b in boliger:
        typer[b.data.get("type", "Andet")] = typer.get(b.data.get("type", "Andet"), 0) + 1
    fordeling = ", ".join(f"{n} {FLERTAL.get(t, t.lower()) if n > 1 else t.lower()}"
                          for t, n in sorted(typer.items(), key=lambda x: -x[1]))

    def beskriv(b) -> str:
        d = b.data
        return f"{d['adresse']} ({d.get('type', '').lower()}, {d.get('boligareal') or '?'} m²) til {_kr(d['pris'])}"

    broedtekst = (
        f"Der er {len(boliger)} boliger til salg i 3390 Hundested ifølge Boligsiden: {fordeling}.\n\n"
        f"{len(nye)} af dem er kommet til salg inden for den seneste uge. "
        f"Mediankontantprisen er {_kr(median(priser))}"
        + (f", og huse og lejligheder koster i mediantal {_kr(median(kvm))} pr. kvadratmeter." if kvm else ".")
        + f"\n\nBilligst er {beskriv(billigst)}. Dyrest er {beskriv(dyrest)}."
        + "\n\nTallene er udbudspriser, ikke salgspriser."
    )
    broedtekst = broedtekst.replace("kr..", "kr.")
    a = Article(
        overskrift=f"{len(boliger)} boliger til salg i Hundested",
        resume=f"{len(nye)} nye på markedet den seneste uge. Mediankontantprisen er {_kr(median(priser))}",
        broedtekst=broedtekst, kategori="nyheder", by="Hundested",
        tags=["service", "boligmarkedet", f"bolig-uge-{nu.isocalendar().week}"],
        kilder=["https://www.boligsiden.dk/", billigst.url, dyrest.url], risiko=RiskLevel.LOW,
        status=ReviewStatus.NEEDS_REVIEW,
        redaktoer_note="Skrevet automatisk ud fra Boligsidens liste for 3390.",
    )
    artikel_id = db.save_article(a)
    db.marker_koert(KOERSEL_BOLIG, nu)
    return artikel_id
