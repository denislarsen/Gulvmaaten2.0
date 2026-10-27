"""Redaktørsiden og godkendelse, med en rigtig server på en tilfældig port."""

import base64
import threading
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from gulvmaatten import server
from gulvmaatten.db import Database
from gulvmaatten.drift import KanIkkeGodkendes, godkend
from gulvmaatten.models import Article, ReviewStatus


def _artikel(db, **kw):
    a = Article(overskrift="Ny bænk på havnen", resume="Resumé.", broedtekst="Tekst.", kategori="havnen",
                by="Hundested", kilder=["https://kilde.dk"], status=ReviewStatus.NEEDS_REVIEW)
    for k, v in kw.items():
        setattr(a, k, v)
    return db.save_article(a)


def test_godkend_afviser_tips_og_anmeldelser_uden_dom(db):
    tip = _artikel(db, tags=["tip"])
    anmeldelse = _artikel(db, kategori="mad", broedtekst="Redaktørens dom: [Udfyldes efter besøg.]")
    for artikel_id in (tip, anmeldelse):
        with pytest.raises(KanIkkeGodkendes):
            godkend(db, artikel_id)
    assert godkend(db, _artikel(db), karakter=None).status == ReviewStatus.APPROVED


@pytest.fixture
def koerende(tmp_path, monkeypatch):
    db_sti = tmp_path / "test.db"
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("forside", encoding="utf-8")
    monkeypatch.setattr(server, "SITE_DIR", site)
    monkeypatch.setenv("GULVMAATTEN_REDAKTOER_KODE", "hemmelig")
    db = Database(db_sti)
    artikel_id = _artikel(db)
    db.close()
    server.Haandtering.db_sti = db_sti
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Haandtering, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", db_sti, artikel_id
    httpd.shutdown()


def _hent(url, kode=None, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None)
    if kode:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"red:{kode}".encode()).decode())
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def test_forsiden_er_aaben_men_redaktionen_kraever_kode(koerende):
    url, _, _ = koerende
    assert _hent(url + "/") == (200, "forside")
    assert _hent(url + "/redaktion")[0] == 401
    assert _hent(url + "/redaktion", "forkert")[0] == 401
    status, html = _hent(url + "/redaktion", "hemmelig")
    assert status == 200 and "Ny bænk på havnen" in html


def test_ret_og_godkend_via_formular(koerende, monkeypatch):
    url, db_sti, artikel_id = koerende
    byggede = []
    monkeypatch.setattr(server, "byg_site", lambda db, ud: byggede.append(ud))
    status, _ = _hent(f"{url}/redaktion/{artikel_id}", "hemmelig",
                      {"handling": "godkend", "overskrift": "Ny bænk på Nordre Beddingsvej"})
    assert status == 200  # efter omdirigering til listen
    db = Database(db_sti)
    a = db.get_article(artikel_id)
    assert a.overskrift == "Ny bænk på Nordre Beddingsvej" and a.status == ReviewStatus.APPROVED
    db.close()
    assert byggede, "hjemmesiden bygges igen efter en godkendelse"
