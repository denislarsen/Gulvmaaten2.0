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


def test_gammel_praktisk_flyttes_ud_af_broedteksten(tmp_path):
    from gulvmaatten.db import Database
    sti = tmp_path / "gammel.db"
    db = Database(sti)
    a = Article(overskrift="X", resume="", broedtekst="Tekst.\n\nPraktisk:\nHvor: Her\nPris: Gratis",
                kategori="kultur", by="Glostrup")
    db.save_article(a)
    db.close()
    db = Database(sti)
    flyttet = db.get_article(a.id)
    assert flyttet.broedtekst == "Tekst." and flyttet.praktisk == "Hvor: Her\nPris: Gratis"
    db.close()
