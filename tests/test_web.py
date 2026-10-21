"""Tester hjemmesiden og redaktionsværktøjet med Flasks testklient."""

from datetime import datetime, timedelta

import pytest

from gulvmaatten.db import Database
from gulvmaatten.models import Article, ReviewStatus
from gulvmaatten.publicering import afpublicer, autogodkend, publicer

KODEORD = "hemmeligt"


@pytest.fixture
def db_sti(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def app(db_sti, monkeypatch):
    monkeypatch.setenv("GULVMAATTEN_ADMIN_PASSWORD", KODEORD)
    from gulvmaatten.web import create_app
    return create_app(db_sti)


@pytest.fixture
def klient(app):
    return app.test_client()


def _artikel(db_sti, overskrift, by="Glostrup", arrangement_start=None, publiceret=True, **kw):
    db = Database(db_sti)
    a = Article(overskrift=overskrift, resume=f"Resumé af {overskrift}", broedtekst="Første afsnit.\n\nAndet afsnit.",
                kategori="kultur", by=by, kilder=["https://www.eksempel.dk/kilde"],
                status=ReviewStatus.NEEDS_REVIEW, er_arrangement=arrangement_start is not None,
                arrangement_start=arrangement_start, **kw)
    db.save_article(a)
    if publiceret:
        publicer(db, a)
    db.close()
    return a


def _log_ind(klient):
    return klient.post("/redaktion/login", data={"kodeord": KODEORD})


def _csrf(klient):
    with klient.session_transaction() as s:
        s.setdefault("csrf", "test-token")
        return s["csrf"]


def test_forside_viser_nyheder_og_arrangementer(klient, db_sti):
    _artikel(db_sti, "Ny legeplads i Byparken")
    _artikel(db_sti, "Koncert i Kulturhuset", by="Brøndby", arrangement_start=datetime.now() + timedelta(days=3),
             praktisk="Hvor: Brøndby Kulturhus\nPris: Gratis")
    _artikel(db_sti, "Forbi koncert", arrangement_start=datetime.now() - timedelta(days=3))
    _artikel(db_sti, "Ikke publiceret", publiceret=False)
    html = klient.get("/").get_data(as_text=True)
    assert "Ny legeplads i Byparken" in html
    assert "Koncert i Kulturhuset" in html and "Brøndby Kulturhus" in html
    assert "Forbi koncert" not in html, "afholdte arrangementer skal ikke vises"
    assert "Ikke publiceret" not in html


def test_byvalg_filtrerer_og_huskes(klient, db_sti):
    _artikel(db_sti, "Nyt fra Glostrup")
    _artikel(db_sti, "Nyt fra Brøndby", by="Brøndby")
    _artikel(db_sti, "Nyt fra begge", by="Glostrup og Brøndby")
    html = klient.get("/?by=brondby").get_data(as_text=True)
    assert "Nyt fra Brøndby" in html and "Nyt fra begge" in html and "Nyt fra Glostrup" not in html
    html = klient.get("/").get_data(as_text=True)
    assert "Nyt fra Glostrup" not in html, "byvalget skal huskes i en cookie"
    html = klient.get("/?by=").get_data(as_text=True)
    assert "Nyt fra Glostrup" in html


def test_artikelside_viser_praktisk_og_kilder(klient, db_sti):
    _artikel(db_sti, "Forfatteraften i Glostrup", praktisk="Hvornår: Torsdag kl. 19\nHvor: Sognegården")
    svar = klient.get("/artikel/forfatteraften-i-glostrup")
    html = svar.get_data(as_text=True)
    assert svar.status_code == 200
    assert "<p>Første afsnit.</p><p>Andet afsnit.</p>" in html
    assert "<dt>Hvor</dt><dd>Sognegården</dd>" in html
    assert "eksempel.dk/kilde" in html


def test_trukket_tilbage_giver_404(klient, db_sti):
    a = _artikel(db_sti, "Fejlagtig artikel")
    db = Database(db_sti)
    afpublicer(db, db.get_article(a.id))
    db.close()
    assert klient.get("/artikel/fejlagtig-artikel").status_code == 404
    assert "Fejlagtig artikel" not in klient.get("/").get_data(as_text=True)


def test_redaktionen_kraever_login(klient):
    svar = klient.get("/redaktion")
    assert svar.status_code == 302 and "/redaktion/login" in svar.headers["Location"]
    assert "Forkert kodeord" in klient.post("/redaktion/login", data={"kodeord": "forkert"},
                                            follow_redirects=True).get_data(as_text=True)
    assert _log_ind(klient).status_code == 302
    assert klient.get("/redaktion").status_code == 200


def test_redaktionen_er_lukket_uden_kodeord(db_sti, monkeypatch):
    monkeypatch.delenv("GULVMAATTEN_ADMIN_PASSWORD", raising=False)
    from gulvmaatten.web import create_app
    assert create_app(db_sti).test_client().get("/redaktion").status_code == 503


def test_ret_og_publicer_artikel(klient, db_sti):
    a = _artikel(db_sti, "Udkast", publiceret=False, usikkerheder="- Tjek datoen")
    _log_ind(klient)
    html = klient.get(f"/redaktion/artikel/{a.id}").get_data(as_text=True)
    assert "Tjek datoen" in html
    svar = klient.post(f"/redaktion/artikel/{a.id}", data={
        "csrf": _csrf(klient), "handling": "publicer", "overskrift": "Rettet overskrift", "resume": "Nyt resumé",
        "broedtekst": "Ny tekst.", "praktisk": "Pris: 50 kr.", "kategori": "kultur", "by": "Brøndby",
        "tags": "a, b", "usikkerheder": "", "redaktoer_note": "", "arrangement_start": "",
    })
    assert svar.status_code == 302
    db = Database(db_sti)
    rettet = db.get_article(a.id)
    assert rettet.status == ReviewStatus.PUBLISHED and rettet.overskrift == "Rettet overskrift"
    assert rettet.by == "Brøndby" and rettet.tags == ["a", "b"] and rettet.praktisk == "Pris: 50 kr."
    slug = db.get_publication(a.id).slug
    db.close()
    assert "Rettet overskrift" in klient.get(f"/artikel/{slug}").get_data(as_text=True)


def test_post_uden_csrf_afvises(klient, db_sti):
    a = _artikel(db_sti, "Udkast", publiceret=False)
    _log_ind(klient)
    assert klient.post(f"/redaktion/artikel/{a.id}", data={"handling": "publicer"}).status_code == 400


def test_autogodkendelse_kan_slaas_fra(klient, db_sti):
    _log_ind(klient)
    klient.post("/redaktion/indstillinger", data={"csrf": _csrf(klient), "autogodkend": "0"})
    db = Database(db_sti)
    assert autogodkend(db) is False
    db.close()


def test_backup_giver_en_database(klient, db_sti, tmp_path):
    _artikel(db_sti, "Gemmes i kopien")
    _log_ind(klient)
    svar = klient.get("/redaktion/backup")
    assert svar.status_code == 200
    kopi = tmp_path / "kopi.db"
    kopi.write_bytes(svar.data)
    assert Database(kopi).get_articles()[0].overskrift == "Gemmes i kopien"
