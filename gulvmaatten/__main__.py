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
"""

from __future__ import annotations

import argparse
import os
import sys

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


def cmd_redaktion(db: Database, args) -> None:
    # Claude Codes skymiljø fjerner ANTHROPIC_API_KEY, så GULVMAATTEN_API_KEY bruges som alternativ.
    api_key = os.environ.get("GULVMAATTEN_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Ingen API-nøgle. Sæt GULVMAATTEN_API_KEY i miljøets indstillinger (Environment variables).")
    import anthropic

    from .agent import koer_redaktion

    client = anthropic.Anthropic(api_key=api_key)
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
    r.add_argument("--taerskel", type=int, default=5, help="Mindste score for at skrive udkast")
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

    args = p.parse_args(argv)
    db = Database(args.db)
    try:
        args.fn(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
