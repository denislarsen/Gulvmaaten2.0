from conftest import fixture_text

from gulvmaatten.fetch import fetch_source, parse_html, parse_rss


def test_parse_html_finder_alle_opslag(html_source):
    items = parse_html(html_source, fixture_text("kommune_nyheder.html"))
    assert len(items) == 3
    assert items[0].titel == "Ny legeplads i Byparken åbner til foråret"
    assert items[0].dato_tekst == "20. oktober 2026"
    assert "2,4 mio" in items[0].tekst


def test_parse_html_goer_relative_links_absolutte(html_source):
    items = parse_html(html_source, fixture_text("kommune_nyheder.html"))
    assert items[0].url == "https://www.eksempel.dk/nyheder/ny-legeplads-i-byparken"
    assert items[2].url == "https://www.eksempel.dk/nyheder/vejarbejde-hovedvejen"


def test_parse_rss(rss_source):
    items = parse_rss(rss_source, fixture_text("bibliotek_arrangementer.xml"))
    assert len(items) == 2
    assert items[0].titel == "Foredrag: Vestegnens historie"
    assert "<p>" not in items[0].tekst
    assert "tilmelding" in items[0].tekst
    assert items[0].dato_tekst.startswith("Mon, 20 Oct 2026")


def test_fetch_registrerer_nye_og_aendrede(db, html_source):
    db.upsert_source(html_source)
    html = fixture_text("kommune_nyheder.html")

    r1 = fetch_source(db, html_source, content=html)
    assert r1.ok and r1.nye == 3 and r1.aendrede == 0

    r2 = fetch_source(db, html_source, content=html)
    assert r2.nye == 0 and r2.uaendrede == 3

    aendret = html.replace("Byggeriet starter i januar.", "Byggeriet er udskudt til marts.")
    r3 = fetch_source(db, html_source, content=aendret)
    assert r3.aendrede == 1 and r3.uaendrede == 2

    assert db.get_sources()[0].sidst_hentet is not None


def test_fetch_rapporterer_fejl_uden_at_vaelte(db, html_source):
    html_source.html = {}
    db.upsert_source(html_source)
    r = fetch_source(db, html_source, content="<html></html>")
    assert not r.ok
    assert "mangler html.opslag" in r.fejl
