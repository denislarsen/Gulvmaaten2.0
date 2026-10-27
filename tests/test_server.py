"""Adgang, redaktørsiden og godkendelse, med en rigtig server på en tilfældig port."""

import http.client
import threading
import urllib.parse
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from gulvmaatten import adgang, server
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


def test_adgangslinks_gemmes_ikke_i_klartekst_og_kan_spaerres(db):
    adgang_id, token = adgang.opret_adgang(db, "Hanne")
    assert token not in str([tuple(r) for r in db.conn.execute("SELECT * FROM adgange")])
    sid = adgang.log_ind_med_token(db, token)
    assert adgang.bruger_fra_session(db, sid).navn == "Hanne"
    adgang.spaer_adgang(db, adgang_id)
    assert adgang.bruger_fra_session(db, sid) is None
    assert adgang.log_ind_med_token(db, token) is None


class Klient:
    """Lille HTTP-klient, der husker sin cookie og ikke følger omdirigeringer."""

    def __init__(self, port):
        self.port = port
        self.cookie = ""

    def __call__(self, metode, sti, data=None, origin=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port)
        hoveder = {"Cookie": self.cookie} if self.cookie else {}
        krop = urllib.parse.urlencode(data) if data else None
        if krop:
            hoveder["Content-Type"] = "application/x-www-form-urlencoded"
        if origin:
            hoveder["Origin"] = origin
        con.request(metode, sti, body=krop, headers=hoveder)
        r = con.getresponse()
        indhold = r.read().decode("utf-8", "replace")
        saet = r.getheader("Set-Cookie")
        if saet:
            self.cookie = saet.split(";")[0]
        con.close()
        return r.status, r.getheader("Location"), indhold


@pytest.fixture
def koerende(tmp_path, monkeypatch):
    db_sti = tmp_path / "test.db"
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("forside", encoding="utf-8")
    monkeypatch.setattr(server, "SITE_DIR", site)
    monkeypatch.setattr(server, "byg_site", lambda db, ud, **kw: None)
    monkeypatch.setenv("GULVMAATTEN_REDAKTOER_KODE", "hemmelig")
    monkeypatch.delenv("GULVMAATTEN_ADGANG", raising=False)
    db = Database(db_sti)
    artikel_id = _artikel(db)
    db.close()
    server.Haandtering.db_sti = db_sti
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Haandtering, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], db_sti, artikel_id
    httpd.shutdown()


def test_privat_side_kraever_login(koerende):
    port, _, _ = koerende
    k = Klient(port)
    status, sted, _ = k("GET", "/")
    assert status == 303 and sted == "/log-ind"
    assert k("GET", "/sundhed")[0] == 200
    assert "Disallow: /" in k("GET", "/robots.txt")[2]
    assert k("GET", "/redaktion")[1] == "/log-ind"


def test_offentlig_side_kraever_kun_login_til_redaktionen(koerende, monkeypatch):
    port, _, _ = koerende
    monkeypatch.setenv("GULVMAATTEN_ADGANG", "offentlig")
    k = Klient(port)
    assert k("GET", "/")[:3:2] == (200, "forside")
    assert k("GET", "/redaktion")[1] == "/log-ind"


def test_ejer_logger_ind_retter_og_godkender(koerende):
    port, db_sti, artikel_id = koerende
    k = Klient(port)
    assert k("POST", "/log-ind", {"kode": "forkert"})[0] == 401
    status, sted, _ = k("POST", "/log-ind", {"kode": "hemmelig"})
    assert status == 303 and sted == "/redaktion" and "gulvmaatten_session=" in k.cookie
    assert "Ny bænk på havnen" in k("GET", "/redaktion")[2]
    status, sted, _ = k("POST", f"/redaktion/{artikel_id}",
                        {"handling": "godkend", "overskrift": "Ny bænk på Nordre Beddingsvej"})
    assert status == 303 and "godkendt" in sted
    db = Database(db_sti)
    a = db.get_article(artikel_id)
    assert a.overskrift == "Ny bænk på Nordre Beddingsvej" and a.status == ReviewStatus.APPROVED
    db.close()
    # Formularer fra en anden side afvises
    assert k("POST", f"/redaktion/{artikel_id}", {"handling": "afvis"}, origin="https://ond.example")[0] == 403


def test_personligt_link_til_laeser(koerende):
    port, _, _ = koerende
    ejer = Klient(port)
    ejer("POST", "/log-ind", {"kode": "hemmelig"})
    _, _, html = ejer("POST", "/redaktion/adgang", {"navn": "Hanne", "rolle": "laeser"})
    link = html.split('value="')[1].split('"')[0]
    sti = urllib.parse.urlsplit(link).path
    assert sti.startswith("/adgang/")

    hanne = Klient(port)
    status, sted, _ = hanne("GET", sti)
    assert status == 303 and sted == "/", "linket sender videre, så det ikke står i adresselinjen"
    assert hanne("GET", "/")[2] == "forside"
    assert hanne("GET", "/redaktion")[0] == 403, "en læser kan ikke komme i redaktionen"

    # Ejeren spærrer linket, og Hanne er logget ud med det samme
    db = Database(koerende[1])
    adgang_id = adgang.adgange(db)[0]["id"]
    db.close()
    ejer("POST", "/redaktion/adgang", {"spaer": adgang_id})
    assert hanne("GET", "/")[1] == "/log-ind"
    assert Klient(port)("GET", sti)[0] == 403
