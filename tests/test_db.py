from datetime import datetime

from gulvmaatten.models import Article, Event, Publication, ReviewStatus, RiskLevel


def test_source_roundtrip(db, html_source):
    db.upsert_source(html_source)
    s = db.get_sources()[0]
    assert s.id == "test-kommune"
    assert s.html["opslag"] == "article.news-item"
    assert s.verificeret is False


def test_article_og_publication(db):
    a = Article(
        overskrift="Ny legeplads i Byparken", resume="Åbner til foråret.", broedtekst="...",
        kategori="byudvikling", by="Glostrup", kilder=["https://www.eksempel.dk/nyheder/legeplads"],
        risiko=RiskLevel.LOW, status=ReviewStatus.NEEDS_REVIEW,
    )
    aid = db.save_article(a)
    assert db.get_articles(ReviewStatus.NEEDS_REVIEW)[0].id == aid

    a.status = ReviewStatus.APPROVED
    db.save_article(a)
    assert db.get_articles(ReviewStatus.NEEDS_REVIEW) == []
    assert db.get_articles(ReviewStatus.APPROVED)[0].kilder == a.kilder

    pid = db.save_publication(Publication(article_id=aid, slug="ny-legeplads-i-byparken"))
    assert pid == 1


def test_event(db):
    e = Event(titel="Foredrag", start=datetime(2026, 11, 6, 19, 0), sted="Biblioteket", by="Brøndby")
    eid = db.save_event(e)
    e.aflyst = True
    assert db.save_event(e) == eid


def test_gammel_database_faar_nye_kolonner(tmp_path):
    import sqlite3

    from gulvmaatten.db import Database

    sti = tmp_path / "gammel.db"
    con = sqlite3.connect(sti)
    con.execute("CREATE TABLE raw_items (id INTEGER PRIMARY KEY, source_id TEXT, url TEXT, titel TEXT, tekst TEXT, "
                "dato_tekst TEXT, fundet TEXT, sidst_set TEXT, content_hash TEXT, UNIQUE(source_id, url))")
    con.commit()
    con.close()
    d = Database(sti)
    kolonner = {r["name"] for r in d.conn.execute("PRAGMA table_info(raw_items)")}
    assert {"billede_url", "data"} <= kolonner
    d.close()
