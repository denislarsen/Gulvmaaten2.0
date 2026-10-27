"""Kommandolinje for Gulvmåtten.

    python -m gulvmaatten init            Opret database og registrér kilder
    python -m gulvmaatten fetch           Hent alle kilder
    python -m gulvmaatten fetch --due     Hent kun kilder, der er forfaldne
    python -m gulvmaatten fetch --source glostrup-kommune-nyheder
    python -m gulvmaatten list            Vis de seneste opslag
    python -m gulvmaatten sources         Vis kilderne og hvornår de sidst er hentet
    python -m gulvmaatten redaktion       Vurdér nye opslag og skriv udkast (kræver GULVMAATTEN_API_KEY)
    python -m gulvmaatten redaktion --limit 5 --source glostrup-kommune-nyheder
    python -m gulvmaatten udkast          Vis artikeludkast, der afventer redaktør
    python -m gulvmaatten vis 3           Vis artikel nr. 3 i fuld længde
    python -m gulvmaatten vurderinger     Vis de seneste vurderinger
    python -m gulvmaatten godkend 3       Godkend artikel nr. 3 (fx --karakter 5 for en anmeldelse)
    python -m gulvmaatten afvis 3         Afvis artikel nr. 3
    python -m gulvmaatten spisesteder find    Tjek havnens liste for nye spisesteder
    python -m gulvmaatten spisesteder ugens   Skriv udkast til "Ugens spisested" (kræver API-nøgle)
    python -m gulvmaatten site            Publicér godkendte artikler og byg hjemmesiden i site/
    python -m gulvmaatten site --forhaandsvisning   Tag også udkast med
    python -m gulvmaatten kalender        Find arrangementer til kalenderen (kræver API-nøgle)
    python -m gulvmaatten kalender --vis  Vis de kommende arrangementer
    python -m gulvmaatten service         Skriv ugens servicehistorier (kalender og boligmarked)
    python -m gulvmaatten planlagt        Kør alt, der er forfaldent (til cron)
    python -m gulvmaatten server          Vis hjemmesiden, kør de faste opgaver hver time og
                                          giv redaktøren en side på /redaktion (fx på Railway)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import load_sources
from .db import DEFAULT_DB, Database
from .fetch import fetch_all, fetch_source
from .models import ReviewStatus


def cmd_init(db: Database, args) -> None:
    sources = load_sources()
    for s in sources:
        db.upsert_source(s)
    print(f"Database: {db.path}")
    print(f"{len(sources)} kilder registreret.")


def cmd_fetch(db: Database, args) -> None:
    if args.source:
        matches = [s for s in db.get_sources() if s.id == args.source]
        if not matches:
            sys.exit(f"Ukendt kilde: {args.source}. Kør 'sources' for at se dem.")
        results = [fetch_source(db, matches[0])]
    else:
        results = fetch_all(db, kun_forfaldne=args.due)
    for r in results:
        print(r)
    if not results:
        print("Ingen kilder var forfaldne.")


def cmd_list(db: Database, args) -> None:
    items = db.get_raw_items(source_id=args.source, limit=args.limit)
    if not items:
        print("Ingen opslag endnu. Kør 'fetch' først.")
        return
    for it in items:
        dato = f" ({it.dato_tekst})" if it.dato_tekst else ""
        print(f"[{it.source_id}] {it.titel}{dato}\n    {it.url}")


def cmd_sources(db: Database, args) -> None:
    for s in db.get_sources(kun_aktive=False):
        hentet = s.sidst_hentet.strftime("%Y-%m-%d %H:%M") if s.sidst_hentet else "aldrig"
        ver = "" if s.verificeret else "  (ikke verificeret)"
        print(f"{s.id:40} {s.type.value:4} tillid {s.tillid}  sidst hentet: {hentet}{ver}")


def _claude_client():
    from .drift import IngenNoegle, claude_client

    try:
        return claude_client()
    except IngenNoegle as e:
        sys.exit(str(e))


def cmd_redaktion(db: Database, args) -> None:
    from .agent import koer_redaktion

    client = _claude_client()
    resultater = koer_redaktion(db, client, limit=args.limit, taerskel=args.taerskel, source_id=args.source)
    if not resultater:
        print("Ingen nye opslag at vurdere.")
        return
    for r in resultater:
        if r.artikel_id:
            print(f"[{r.score:2}] {r.titel}\n     -> udkast #{r.artikel_id} ({r.kategori}), afventer redaktør")
        else:
            print(f"[{r.score:2}] {r.titel}\n     -> sprunget over: {r.sprunget_over}")
    antal = sum(1 for r in resultater if r.artikel_id)
    print(f"\n{len(resultater)} vurderet, {antal} udkast skrevet.")


def cmd_udkast(db: Database, args) -> None:
    status = ReviewStatus(args.status) if args.status else ReviewStatus.NEEDS_REVIEW
    artikler = db.get_articles(status)
    if not artikler:
        print(f"Ingen artikler med status {status.value}.")
        return
    for a in artikler:
        flag = "  !! HØJ RISIKO" if a.risiko.value == "high" else ""
        print(f"#{a.id:3} [{a.kategori}] {a.overskrift}{flag}")
        print(f"      {a.resume}")
        if a.usikkerheder:
            print(f"      Usikkert: {a.usikkerheder}")


def cmd_vis(db: Database, args) -> None:
    a = db.get_article(args.id)
    if not a:
        sys.exit(f"Ingen artikel med id {args.id}.")
    print(f"{a.overskrift}\n{'=' * len(a.overskrift)}")
    print(f"{a.kategori} | {a.by} | risiko: {a.risiko.value} | status: {a.status.value}")
    print(f"tags: {', '.join(a.tags)}\n")
    print(a.resume + "\n")
    print(a.broedtekst + "\n")
    if a.usikkerheder:
        print(f"USIKKERHEDER: {a.usikkerheder}\n")
    print("Kilder:")
    for k in a.kilder:
        print(f"  {k}")


def cmd_vurderinger(db: Database, args) -> None:
    rows = db.get_assessments(limit=args.limit)
    if not rows:
        print("Ingen vurderinger endnu. Kør 'redaktion' først.")
        return
    for r in rows:
        print(f"[{r['score']:2}] {r['kategori']:22} {r['risiko']:6} {r['titel']}\n     {r['begrundelse']}")


def _hent_artikel(db: Database, article_id: int):
    a = db.get_article(article_id)
    if not a:
        sys.exit(f"Ingen artikel med id {article_id}.")
    return a


def cmd_godkend(db: Database, args) -> None:
    from .drift import KanIkkeGodkendes, godkend

    try:
        a = godkend(db, args.id, args.karakter)
    except KanIkkeGodkendes as e:
        sys.exit(str(e))
    print(f"#{a.id} godkendt: {a.overskrift}")


def cmd_afvis(db: Database, args) -> None:
    from .drift import KanIkkeGodkendes, afvis

    try:
        a = afvis(db, args.id)
    except KanIkkeGodkendes as e:
        sys.exit(str(e))
    print(f"#{a.id} afvist: {a.overskrift}")


def cmd_spisesteder(db: Database, args) -> None:
    from . import mad

    if args.handling == "find":
        nye = mad.find_nye_spisesteder(db)
        if nye:
            print("Nye spisesteder på havnens liste. Tilføj dem i config/steder.yaml:")
            for n in nye:
                print(f"  {n}")
        else:
            print("Ingen nye spisesteder på havnens liste.")
    else:
        artikel_id = mad.lav_ugens_spisested(db, _claude_client())
        if artikel_id:
            a = db.get_article(artikel_id)
            print(f"Udkast #{artikel_id}: {a.overskrift}\n{a.redaktoer_note}")
        else:
            print("Alle spisesteder er omtalt for nylig.")


def cmd_kalender(db: Database, args) -> None:
    from datetime import datetime

    from .kalender import koer_kalender

    if not args.vis:
        for r in koer_kalender(db, _claude_client(), limit=args.limit):
            print(f"{r.antal:3} arrangementer  {r.titel[:70]}")
    for e in db.kommende_events(datetime.now()):
        tid = e.start.strftime("%d/%m %H:%M") if e.start.hour or e.start.minute else e.start.strftime("%d/%m")
        print(f"{tid:12} {e.titel[:50]:50} {e.sted[:30]}{'  AFLYST' if e.aflyst else ''}")


def cmd_service(db: Database, args) -> None:
    from . import service

    for navn, fn in (("Det sker i ugen", service.det_sker_i_ugen), ("Boligmarkedet", service.boligmarkedet)):
        artikel_id = fn(db)
        print(f"{navn}: udkast #{artikel_id}" if artikel_id else f"{navn}: ikke nok data")


def cmd_site(db: Database, args) -> None:
    from .site import byg_site

    filer = byg_site(db, Path(args.ud), forhaandsvisning=args.forhaandsvisning)
    print(f"{len(filer)} filer skrevet i {args.ud}/. Åbn {args.ud}/index.html i en browser.")


def cmd_planlagt(db: Database, args) -> None:
    """Kør alt, der er forfaldent. Beregnet til at blive kaldt fra cron, fx hver time."""
    from .drift import koer_planlagt

    koer_planlagt(db, _claude_client(), limit=args.limit)


def cmd_server(db: Database, args) -> None:
    from .server import start

    db.close()
    start(port=args.port, db_sti=Path(args.db), hver_minutter=args.hver)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="gulvmaatten", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(DEFAULT_DB), help="Sti til databasen")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)
    f = sub.add_parser("fetch")
    f.add_argument("--due", action="store_true", help="Hent kun forfaldne kilder")
    f.add_argument("--source", help="Hent kun denne kilde")
    f.set_defaults(fn=cmd_fetch)
    ls = sub.add_parser("list")
    ls.add_argument("--source")
    ls.add_argument("--limit", type=int, default=30)
    ls.set_defaults(fn=cmd_list)
    sub.add_parser("sources").set_defaults(fn=cmd_sources)
    r = sub.add_parser("redaktion")
    r.add_argument("--limit", type=int, default=10, help="Højst så mange opslag (hvert koster et API-kald)")
    r.add_argument("--taerskel", type=int, default=4, help="Mindste score for at skrive udkast")
    r.add_argument("--source", help="Kun opslag fra denne kilde")
    r.set_defaults(fn=cmd_redaktion)
    u = sub.add_parser("udkast")
    u.add_argument("--status", choices=[s.value for s in ReviewStatus])
    u.set_defaults(fn=cmd_udkast)
    v = sub.add_parser("vis")
    v.add_argument("id", type=int)
    v.set_defaults(fn=cmd_vis)
    vu = sub.add_parser("vurderinger")
    vu.add_argument("--limit", type=int, default=30)
    vu.set_defaults(fn=cmd_vurderinger)
    g = sub.add_parser("godkend")
    g.add_argument("id", type=int)
    g.add_argument("--karakter", type=int, choices=range(1, 7), help="Gulvmåtter (1-6) til en anmeldelse")
    g.set_defaults(fn=cmd_godkend)
    a = sub.add_parser("afvis")
    a.add_argument("id", type=int)
    a.set_defaults(fn=cmd_afvis)
    sp = sub.add_parser("spisesteder")
    sp.add_argument("handling", choices=["find", "ugens"])
    sp.set_defaults(fn=cmd_spisesteder)
    k = sub.add_parser("kalender")
    k.add_argument("--vis", action="store_true", help="Vis kun kalenderen, kald ikke Claude")
    k.add_argument("--limit", type=int, default=30)
    k.set_defaults(fn=cmd_kalender)
    sub.add_parser("service").set_defaults(fn=cmd_service)
    st = sub.add_parser("site")
    st.add_argument("--ud", default="site", help="Mappe til hjemmesiden")
    st.add_argument("--forhaandsvisning", action="store_true", help="Tag udkast med, markeret UDKAST")
    st.set_defaults(fn=cmd_site)
    pl = sub.add_parser("planlagt")
    pl.add_argument("--limit", type=int, default=20, help="Højst så mange opslag til redaktionen pr. kørsel")
    pl.set_defaults(fn=cmd_planlagt)
    sv = sub.add_parser("server")
    sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    sv.add_argument("--hver", type=int, default=60, help="Minutter mellem de faste kørsler (0 = slået fra)")
    sv.set_defaults(fn=cmd_server)

    args = p.parse_args(argv)
    db = Database(args.db)
    try:
        args.fn(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
