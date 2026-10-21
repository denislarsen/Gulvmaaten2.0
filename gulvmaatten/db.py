"""SQLite-lager for Gulvmåtten.

Holder det simpelt: én fil, én tabel pr. datatype. Lister gemmes som JSON.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Article, Event, Publication, RawItem, ReviewStatus, RiskLevel, Source, SourceType

DEFAULT_DB = Path("data/gulvmaatten.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    navn TEXT NOT NULL,
    url TEXT NOT NULL,
    type TEXT NOT NULL,
    kategori TEXT,
    by TEXT,
    tillid INTEGER,
    frekvens_timer INTEGER,
    sprog TEXT,
    verificeret INTEGER,
    html TEXT,
    regler TEXT,
    aktiv INTEGER DEFAULT 1,
    sidst_hentet TEXT
);

CREATE TABLE IF NOT EXISTS raw_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id),
    url TEXT NOT NULL,
    titel TEXT NOT NULL,
    tekst TEXT,
    dato_tekst TEXT,
    fundet TEXT NOT NULL,
    sidst_set TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(source_id, url)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titel TEXT NOT NULL,
    start TEXT,
    slut TEXT,
    sted TEXT,
    by TEXT,
    pris TEXT,
    tilmelding TEXT,
    arrangoer TEXT,
    aflyst INTEGER DEFAULT 0,
    raw_item_ids TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    overskrift TEXT NOT NULL,
    resume TEXT,
    broedtekst TEXT,
    kategori TEXT,
    by TEXT,
    tags TEXT,
    kilder TEXT,
    usikkerheder TEXT,
    risiko TEXT,
    status TEXT,
    raw_item_ids TEXT,
    event_id INTEGER REFERENCES events(id),
    oprettet TEXT,
    opdateret TEXT,
    redaktoer_note TEXT
);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    slug TEXT UNIQUE NOT NULL,
    publiceret TEXT NOT NULL,
    rettelsesnote TEXT,
    trukket_tilbage TEXT
);
"""


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Database:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- Sources -----------------------------------------------------------

    def upsert_source(self, s: Source) -> None:
        self.conn.execute(
            """INSERT INTO sources
               (id, navn, url, type, kategori, by, tillid, frekvens_timer, sprog, verificeret, html, regler, aktiv)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 navn=excluded.navn, url=excluded.url, type=excluded.type, kategori=excluded.kategori,
                 by=excluded.by, tillid=excluded.tillid, frekvens_timer=excluded.frekvens_timer,
                 sprog=excluded.sprog, verificeret=excluded.verificeret, html=excluded.html,
                 regler=excluded.regler, aktiv=excluded.aktiv""",
            (s.id, s.navn, s.url, s.type.value, s.kategori, s.by, s.tillid, s.frekvens_timer,
             s.sprog, int(s.verificeret), json.dumps(s.html), s.regler, int(s.aktiv)),
        )
        self.conn.commit()

    def get_sources(self, kun_aktive: bool = True) -> list[Source]:
        sql = "SELECT * FROM sources" + (" WHERE aktiv=1" if kun_aktive else "") + " ORDER BY id"
        return [self._row_to_source(r) for r in self.conn.execute(sql)]

    def mark_fetched(self, source_id: str, when: datetime | None = None) -> None:
        self.conn.execute("UPDATE sources SET sidst_hentet=? WHERE id=?",
                          (_dt(when or datetime.now()), source_id))
        self.conn.commit()

    @staticmethod
    def _row_to_source(r: sqlite3.Row) -> Source:
        return Source(
            id=r["id"], navn=r["navn"], url=r["url"], type=SourceType(r["type"]),
            kategori=r["kategori"] or "", by=r["by"] or "", tillid=r["tillid"] or 3,
            frekvens_timer=r["frekvens_timer"] or 24, sprog=r["sprog"] or "da",
            verificeret=bool(r["verificeret"]), html=json.loads(r["html"] or "{}"),
            regler=r["regler"] or "", aktiv=bool(r["aktiv"]),
            sidst_hentet=_parse_dt(r["sidst_hentet"]),
        )

    # --- RawItems ----------------------------------------------------------

    def record_raw_item(self, item: RawItem) -> str:
        """Gem et opslag. Returnerer 'ny', 'aendret' eller 'uaendret'."""
        row = self.conn.execute(
            "SELECT id, content_hash FROM raw_items WHERE source_id=? AND url=?",
            (item.source_id, item.url),
        ).fetchone()
        now = _dt(datetime.now())
        if row is None:
            cur = self.conn.execute(
                """INSERT INTO raw_items (source_id, url, titel, tekst, dato_tekst, fundet, sidst_set, content_hash)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (item.source_id, item.url, item.titel, item.tekst, item.dato_tekst, now, now, item.content_hash),
            )
            item.id = cur.lastrowid
            self.conn.commit()
            return "ny"
        item.id = row["id"]
        if row["content_hash"] != item.content_hash:
            self.conn.execute(
                """UPDATE raw_items SET titel=?, tekst=?, dato_tekst=?, sidst_set=?, content_hash=? WHERE id=?""",
                (item.titel, item.tekst, item.dato_tekst, now, item.content_hash, item.id),
            )
            self.conn.commit()
            return "aendret"
        self.conn.execute("UPDATE raw_items SET sidst_set=? WHERE id=?", (now, item.id))
        self.conn.commit()
        return "uaendret"

    def get_raw_items(self, source_id: str | None = None, limit: int = 100) -> list[RawItem]:
        if source_id:
            rows = self.conn.execute(
                "SELECT * FROM raw_items WHERE source_id=? ORDER BY fundet DESC LIMIT ?", (source_id, limit))
        else:
            rows = self.conn.execute("SELECT * FROM raw_items ORDER BY fundet DESC LIMIT ?", (limit,))
        return [self._row_to_raw(r) for r in rows]

    @staticmethod
    def _row_to_raw(r: sqlite3.Row) -> RawItem:
        return RawItem(
            id=r["id"], source_id=r["source_id"], url=r["url"], titel=r["titel"],
            tekst=r["tekst"] or "", dato_tekst=r["dato_tekst"] or "",
            fundet=_parse_dt(r["fundet"]), sidst_set=_parse_dt(r["sidst_set"]),
            content_hash=r["content_hash"],
        )

    # --- Events ------------------------------------------------------------

    def save_event(self, e: Event) -> int:
        if e.id is None:
            cur = self.conn.execute(
                """INSERT INTO events (titel, start, slut, sted, by, pris, tilmelding, arrangoer, aflyst, raw_item_ids)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (e.titel, _dt(e.start), _dt(e.slut), e.sted, e.by, e.pris, e.tilmelding, e.arrangoer,
                 int(e.aflyst), json.dumps(e.raw_item_ids)),
            )
            e.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE events SET titel=?, start=?, slut=?, sted=?, by=?, pris=?, tilmelding=?, arrangoer=?,
                   aflyst=?, raw_item_ids=? WHERE id=?""",
                (e.titel, _dt(e.start), _dt(e.slut), e.sted, e.by, e.pris, e.tilmelding, e.arrangoer,
                 int(e.aflyst), json.dumps(e.raw_item_ids), e.id),
            )
        self.conn.commit()
        return e.id

    # --- Articles ----------------------------------------------------------

    def save_article(self, a: Article) -> int:
        a.opdateret = datetime.now()
        if a.id is None:
            cur = self.conn.execute(
                """INSERT INTO articles (overskrift, resume, broedtekst, kategori, by, tags, kilder, usikkerheder,
                   risiko, status, raw_item_ids, event_id, oprettet, opdateret, redaktoer_note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (a.overskrift, a.resume, a.broedtekst, a.kategori, a.by, json.dumps(a.tags), json.dumps(a.kilder),
                 a.usikkerheder, a.risiko.value, a.status.value, json.dumps(a.raw_item_ids), a.event_id,
                 _dt(a.oprettet), _dt(a.opdateret), a.redaktoer_note),
            )
            a.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE articles SET overskrift=?, resume=?, broedtekst=?, kategori=?, by=?, tags=?, kilder=?,
                   usikkerheder=?, risiko=?, status=?, raw_item_ids=?, event_id=?, opdateret=?, redaktoer_note=?
                   WHERE id=?""",
                (a.overskrift, a.resume, a.broedtekst, a.kategori, a.by, json.dumps(a.tags), json.dumps(a.kilder),
                 a.usikkerheder, a.risiko.value, a.status.value, json.dumps(a.raw_item_ids), a.event_id,
                 _dt(a.opdateret), a.redaktoer_note, a.id),
            )
        self.conn.commit()
        return a.id

    def get_articles(self, status: ReviewStatus | None = None) -> list[Article]:
        if status:
            rows = self.conn.execute("SELECT * FROM articles WHERE status=? ORDER BY oprettet DESC", (status.value,))
        else:
            rows = self.conn.execute("SELECT * FROM articles ORDER BY oprettet DESC")
        return [self._row_to_article(r) for r in rows]

    @staticmethod
    def _row_to_article(r: sqlite3.Row) -> Article:
        return Article(
            id=r["id"], overskrift=r["overskrift"], resume=r["resume"] or "", broedtekst=r["broedtekst"] or "",
            kategori=r["kategori"] or "", by=r["by"] or "", tags=json.loads(r["tags"] or "[]"),
            kilder=json.loads(r["kilder"] or "[]"), usikkerheder=r["usikkerheder"] or "",
            risiko=RiskLevel(r["risiko"] or "low"), status=ReviewStatus(r["status"] or "new"),
            raw_item_ids=json.loads(r["raw_item_ids"] or "[]"), event_id=r["event_id"],
            oprettet=_parse_dt(r["oprettet"]), opdateret=_parse_dt(r["opdateret"]),
            redaktoer_note=r["redaktoer_note"] or "",
        )

    # --- Publications ------------------------------------------------------

    def save_publication(self, p: Publication) -> int:
        cur = self.conn.execute(
            "INSERT INTO publications (article_id, slug, publiceret, rettelsesnote, trukket_tilbage) VALUES (?,?,?,?,?)",
            (p.article_id, p.slug, _dt(p.publiceret), p.rettelsesnote, _dt(p.trukket_tilbage)),
        )
        p.id = cur.lastrowid
        self.conn.commit()
        return p.id
