from conftest import fixture_text

from gulvmaatten.fetch import fetch_source, parse_article_page, parse_sitemap
from gulvmaatten.models import Source, SourceType


def sitemap_source(max_items=20):
    return Source(
        id="test-sitemap", navn="Test", url="https://www.eksempel.dk/sitemap.xml",
        type=SourceType.SITEMAP, kategori="kommune", by="Hundested",
        sitemap={"prefix": "https://www.eksempel.dk/nyheder/", "max": max_items},
        html={"titel": "h1"},
    )


def test_parse_sitemap_filtrerer_og_sorterer():
    found = parse_sitemap(sitemap_source(), fixture_text("sitemap.xml"))
    urls = [u for u, _ in found]
    assert urls == [
        "https://www.eksempel.dk/nyheder/ny-legeplads",
        "https://www.eksempel.dk/nyheder/hoering-lokalplan-42",
        "https://www.eksempel.dk/nyheder/svindel-sms",
    ]
    assert found[0][1] == "2026-10-20T07:30:00+00:00"


def test_parse_sitemap_respekterer_max():
    assert len(parse_sitemap(sitemap_source(max_items=2), fixture_text("sitemap.xml"))) == 2


def test_parse_article_page_bruger_h1_og_meta_description():
    item = parse_article_page(sitemap_source(), "https://www.eksempel.dk/nyheder/ny-legeplads",
                              fixture_text("artikel.html"), dato_tekst="2026-10-20")
    assert item.titel == "Ny legeplads i Byparken"
    assert "2,4 mio" in item.tekst
    assert item.dato_tekst == "2026-10-20"


def test_fetch_sitemap_henter_kun_nye_sider(db):
    src = sitemap_source()
    db.upsert_source(src)
    hentede: list[str] = []

    def fetcher(url: str) -> str:
        hentede.append(url)
        return fixture_text("artikel.html")

    r1 = fetch_source(db, src, content=fixture_text("sitemap.xml"), fetcher=fetcher)
    assert r1.ok and r1.nye == 3
    assert len(hentede) == 3

    hentede.clear()
    r2 = fetch_source(db, src, content=fixture_text("sitemap.xml"), fetcher=fetcher)
    assert r2.uaendrede == 3
    assert hentede == [], "sider med uændret lastmod må ikke hentes igen"

    # Ændret lastmod på én side udløser én ny hentning og markeres som ændret
    nyt = fixture_text("sitemap.xml").replace("2026-10-18T09:00:00+00:00", "2026-10-21T10:00:00+00:00")
    r3 = fetch_source(db, src, content=nyt, fetcher=fetcher)
    assert hentede == ["https://www.eksempel.dk/nyheder/hoering-lokalplan-42"]
    assert r3.aendrede == 1 and r3.uaendrede == 2
