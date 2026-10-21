"""Kommandolinje for Gulvmåtten.

    python -m gulvmaatten init            Opret database og registrér kilder
    python -m gulvmaatten fetch           Hent alle kilder
    python -m gulvmaatten fetch --due     Hent kun kilder, der er forfaldne
    python -m gulvmaatten fetch --source glostrup-kommune-nyheder
    python -m gulvmaatten list            Vis de seneste opslag
    python -m gulvmaatten sources         Vis kilderne og hvornår de sidst er hentet
"""

from __future__ import annotations

import argparse
import sys

from .config import load_sources
from .db import DEFAULT_DB, Database
from .fetch import fetch_all, fetch_source


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

    args = p.parse_args(argv)
    db = Database(args.db)
    try:
        args.fn(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
