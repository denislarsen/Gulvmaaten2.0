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
    sitemap TEXT,
    regler TEXT,
    aktiv INTEGER DEFAULT 1,
    sidst_hentet TEXT,
    prioritet INTEGER DEFAULT 1,
    billeder INTEGER DEFAULT 1
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
    billede_url TEXT,
    data TEXT,
    UNIQUE(source_id, url)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_item_id INTEGER NOT NULL REFERENCES raw_items(id),
    content_hash TEXT NOT NULL,
    score INTEGER,
    kategori TEXT,
    risiko TEXT,
    begrundelse TEXT,
    tidspunkt TEXT NOT NULL
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
    redaktoer_note TEXT,
    billede_url TEXT,
    billede_kredit TEXT
);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    slug TEXT UNIQUE NOT NULL,
    publiceret TEXT NOT NULL,
    rettelsesnote TEXT,
    trukket_tilbage TEXT
);

-- Hvornår faste opgaver (fx "Ugens spisested") sidst er kørt
CREATE TABLE IF NOT EXISTS koersler (
    navn TEXT PRIMARY KEY,
    sidst_koert TEXT NOT NULL
);
"""

# Kolonner tilføjet efter første version. Ældre databaser får dem ved opstart.
MIGRATIONER = [
    ("sources", "prioritet", "INTEGER DEFAULT 1"),
    ("sources", "billeder", "INTEGER DEFAULT 1"),
    ("raw_items", "billede_url", "TEXT"),
    ("raw_items", "data", "TEXT"),
    ("articles", "billede_url", "TEXT"),
    ("articles", "billede_kredit", "TEXT"),
]


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
        self._migrer()

    def _migrer(self) -> None:
        for tabel, kolonne, typ in MIGRATIONER:
            findes = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({tabel})")}
            if kolonne not in findes:
                self.conn.execute(f"ALTER TABLE {tabel} ADD COLUMN {kolonne} {typ}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- Sources -----------------------------------------------------------

    def upsert_source(self, s: Source) -> None:
        self.conn.execute(
            """INSERT INTO sources
               (id, navn, url, type, kategori, by, tillid, frekvens_timer, sprog, verificeret, html, sitemap, regler, aktiv,
                prioritet, billeder)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 navn=excluded.navn, url=excluded.url, type=excluded.type, kategori=excluded.kategori,
                 by=excluded.by, tillid=excluded.tillid, frekvens_timer=excluded.frekvens_timer,
                 sprog=excluded.sprog, verificeret=excluded.verificeret, html=excluded.html,
                 sitemap=excluded.sitemap, regler=excluded.regler, aktiv=excluded.aktiv,
                 prioritet=excluded.prioritet, billeder=excluded.billeder""",
            (s.id, s.navn, s.url, s.type.value, s.kategori, s.by, s.tillid, s.frekvens_timer,
             s.sprog, int(s.verificeret), json.dumps(s.html), json.dumps(s.sitemap), s.regler, int(s.aktiv),
             s.prioritet, int(s.billeder)),
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
            sitemap=json.loads(r["sitemap"] or "{}"),
            regler=r["regler"] or "", aktiv=bool(r["aktiv"]),
            sidst_hentet=_parse_dt(r["sidst_hentet"]),
            prioritet=r["prioritet"] or 1, billeder=bool(r["billeder"]),
        )

    def get_source(self, source_id: str) -> Source | None:
        row = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return self._row_to_source(row) if row else None

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
                """INSERT INTO raw_items (source_id, url, titel, tekst, dato_tekst, fundet, sidst_set, content_hash,
                   billede_url, data)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (item.source_id, item.url, item.titel, item.tekst, item.dato_tekst, now, now, item.content_hash,
                 item.billede_url, json.dumps(item.data)),
            )
            item.id = cur.lastrowid
            self.conn.commit()
            return "ny"
        item.id = row["id"]
        if row["content_hash"] != item.content_hash:
            self.conn.execute(
                """UPDATE raw_items SET titel=?, tekst=?, dato_tekst=?, sidst_set=?, content_hash=?,
                   billede_url=?, data=? WHERE id=?""",
                (item.titel, item.tekst, item.dato_tekst, now, item.content_hash, item.billede_url,
                 json.dumps(item.data), item.id),
            )
            self.conn.commit()
            return "aendret"
        # Billede og strukturerede felter tæller ikke som en ændring af opslaget,
        # men holdes opdateret.
        self.conn.execute("UPDATE raw_items SET sidst_set=?, billede_url=?, data=? WHERE id=?",
                          (now, item.billede_url, json.dumps(item.data), item.id))
        self.conn.commit()
        return "uaendret"

    def get_raw_item(self, source_id: str, url: str) -> RawItem | None:
        row = self.conn.execute(
            "SELECT * FROM raw_items WHERE source_id=? AND url=?", (source_id, url)).fetchone()
        return self._row_to_raw(row) if row else None

    def get_raw_item_by_id(self, raw_item_id: int) -> RawItem | None:
        row = self.conn.execute("SELECT * FROM raw_items WHERE id=?", (raw_item_id,)).fetchone()
        return self._row_to_raw(row) if row else None

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
            content_hash=r["content_hash"], billede_url=r["billede_url"] or "",
            data=json.loads(r["data"] or "{}"),
        )

    # --- Assessments (vurderinger) ------------------------------------------

    def save_assessment(self, raw_item_id: int, score: int, kategori: str, risiko: str, begrundelse: str) -> None:
        row = self.conn.execute("SELECT content_hash FROM raw_items WHERE id=?", (raw_item_id,)).fetchone()
        self.conn.execute(
            "INSERT INTO assessments (raw_item_id, content_hash, score, kategori, risiko, begrundelse, tidspunkt) "
            "VALUES (?,?,?,?,?,?,?)",
            (raw_item_id, row["content_hash"] if row else "", score, kategori, risiko, begrundelse,
             _dt(datetime.now())),
        )
        self.conn.commit()

    def get_unassessed_raw_items(self, limit: int = 10, source_id: str | None = None,
                                 udelad: list[str] | None = None) -> list[RawItem]:
        """Opslag uden vurdering af deres nuværende indhold. Et opslag, der er
        ændret siden sidste vurdering, kommer med igen."""
        sql = """SELECT r.* FROM raw_items r
                 WHERE NOT EXISTS (SELECT 1 FROM assessments a
                                   WHERE a.raw_item_id = r.id AND a.content_hash = r.content_hash)"""
        params: list = []
        if source_id:
            sql += " AND r.source_id = ?"
            params.append(source_id)
        if udelad:
            sql += f" AND r.source_id NOT IN ({','.join('?' * len(udelad))})"
            params.extend(udelad)
        sql += " ORDER BY r.fundet DESC, r.id DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_raw(r) for r in self.conn.execute(sql, params)]

    def score_for(self, raw_item_id: int) -> int:
        """Seneste vurderingsscore for et opslag, 0 hvis det ikke er vurderet."""
        row = self.conn.execute("SELECT score FROM assessments WHERE raw_item_id=? ORDER BY id DESC LIMIT 1",
                                (raw_item_id,)).fetchone()
        return row["score"] if row else 0

    def get_assessments(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            """SELECT a.*, r.titel, r.source_id FROM assessments a JOIN raw_items r ON r.id = a.raw_item_id
               ORDER BY a.tidspunkt DESC LIMIT ?""", (limit,)))

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
                   risiko, status, raw_item_ids, event_id, oprettet, opdateret, redaktoer_note, billede_url, billede_kredit)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (a.overskrift, a.resume, a.broedtekst, a.kategori, a.by, json.dumps(a.tags), json.dumps(a.kilder),
                 a.usikkerheder, a.risiko.value, a.status.value, json.dumps(a.raw_item_ids), a.event_id,
                 _dt(a.oprettet), _dt(a.opdateret), a.redaktoer_note, a.billede_url, a.billede_kredit),
            )
            a.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE articles SET overskrift=?, resume=?, broedtekst=?, kategori=?, by=?, tags=?, kilder=?,
                   usikkerheder=?, risiko=?, status=?, raw_item_ids=?, event_id=?, opdateret=?, redaktoer_note=?,
                   billede_url=?, billede_kredit=?
                   WHERE id=?""",
                (a.overskrift, a.resume, a.broedtekst, a.kategori, a.by, json.dumps(a.tags), json.dumps(a.kilder),
                 a.usikkerheder, a.risiko.value, a.status.value, json.dumps(a.raw_item_ids), a.event_id,
                 _dt(a.opdateret), a.redaktoer_note, a.billede_url, a.billede_kredit, a.id),
            )
        self.conn.commit()
        return a.id

    def get_article(self, article_id: int) -> Article | None:
        row = self.conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        return self._row_to_article(row) if row else None

    def get_articles(self, status: ReviewStatus | list[ReviewStatus] | None = None) -> list[Article]:
        if status:
            statusser = status if isinstance(status, list) else [status]
            pladser = ",".join("?" * len(statusser))
            rows = self.conn.execute(f"SELECT * FROM articles WHERE status IN ({pladser}) ORDER BY oprettet DESC",
                                     [s.value for s in statusser])
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
            redaktoer_note=r["redaktoer_note"] or "", billede_url=r["billede_url"] or "",
            billede_kredit=r["billede_kredit"] or "",
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

    def get_publication(self, article_id: int) -> Publication | None:
        row = self.conn.execute("SELECT * FROM publications WHERE article_id=? ORDER BY id DESC LIMIT 1",
                                (article_id,)).fetchone()
        if not row:
            return None
        return Publication(id=row["id"], article_id=row["article_id"], slug=row["slug"],
                           publiceret=_parse_dt(row["publiceret"]), rettelsesnote=row["rettelsesnote"] or "",
                           trukket_tilbage=_parse_dt(row["trukket_tilbage"]))

    # --- Faste kørsler -------------------------------------------------------

    def sidst_koert(self, navn: str) -> datetime | None:
        row = self.conn.execute("SELECT sidst_koert FROM koersler WHERE navn=?", (navn,)).fetchone()
        return _parse_dt(row["sidst_koert"]) if row else None

    def marker_koert(self, navn: str, when: datetime | None = None) -> None:
        self.conn.execute(
            "INSERT INTO koersler (navn, sidst_koert) VALUES (?,?) "
            "ON CONFLICT(navn) DO UPDATE SET sidst_koert=excluded.sidst_koert",
            (navn, _dt(when or datetime.now())))
        self.conn.commit()
