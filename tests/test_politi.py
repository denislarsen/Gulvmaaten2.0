"""Politiets døgnrapport: kun lokale hændelser gemmes."""

from conftest import fixture_text

from gulvmaatten.fetch import fetch_source, parse_politi_liste, parse_politi_rapport
from gulvmaatten.models import Source, SourceType

RAPPORT = ("https://politi.dk/nordsjaellands-politi/doegnrapporter/"
           "nordsjaellands-politi-uddrag-af-doegnrapporten-22-23-oktober-2026/2026/10/23")


def politi_kilde():
    return Source(id="politi", navn="Nordsjællands Politi", url="https://politi.dk/doegnrapporter",
                  type=SourceType.POLITI, kategori="politi", by="Halsnæs", billeder=False)


def test_listen_laeses_fra_sidens_data():
    rapporter = parse_politi_liste(fixture_text("politi_liste.html"))
    assert len(rapporter) == 3
    assert all(r["Link"].startswith("https://politi.dk/nordsjaellands-politi/doegnrapporter/") for r in rapporter)


def test_kun_hundested_haendelser_gemmes():
    items = parse_politi_rapport(politi_kilde(), RAPPORT, fixture_text("politi_rapport.html"), dato="2026-10-23")
    assert [i.titel for i in items] == ["To løse køer på vejbane, Hundested"]
    assert "Galgebjerggårdsvej" in items[0].tekst
    assert "Gentofte" not in items[0].tekst, "teksten stopper ved næste hændelse"
    assert items[0].url.startswith(RAPPORT + "#")


def test_rapporter_hentes_kun_en_gang(db):
    src = politi_kilde()
    db.upsert_source(src)
    hentet = []

    def fetcher(url):
        hentet.append(url)
        return fixture_text("politi_rapport.html")

    liste = fixture_text("politi_liste.html")
    r1 = fetch_source(db, src, content=liste, fetcher=fetcher)
    assert len(hentet) == 3 and r1.nye >= 1
    fetch_source(db, src, content=liste, fetcher=fetcher)
    assert len(hentet) == 3, "kendte rapporter hentes ikke igen"
