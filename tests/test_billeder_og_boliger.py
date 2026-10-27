"""Billeder fra kilderne og boligsiden-kilden."""

from conftest import fixture_text

from gulvmaatten.fetch import fetch_source, parse_boligsiden, parse_html, parse_rss, parse_sitemap
from gulvmaatten.models import Source, SourceType


def surf_source(**kw):
    return Source(
        id="surf", navn="Lynæs Surfcenter", url="https://surfcenter.dk/", type=SourceType.HTML,
        kategori="kultur", by="Hundested",
        html={"opslag": 'a.card_inner[href*="/vare/"]', "titel": "h5", "resume": ".card_content p",
              "billede": "img", "url_uden_query": True}, **kw,
    )


def test_html_finder_lazy_billede_og_fjerner_query():
    items = parse_html(surf_source(), fixture_text("surfcenter.html"))
    assert [i.titel for i in items] == ["Saunagus", "Poul Krebs – 7. august"]
    assert items[0].url == "https://surfcenter.dk/vare/saunagus/"
    # Det rigtige billede, ikke den tomme data:-pladsholder
    assert items[0].billede_url == "https://surfcenter.dk/wp-content/uploads/2024/03/saunagus-640x360.jpg"


def test_samme_opslag_med_ny_dato_i_url_er_ikke_nyt(db):
    src = surf_source()
    db.upsert_source(src)
    html = fixture_text("surfcenter.html")
    assert fetch_source(db, src, content=html).nye == 2
    r = fetch_source(db, src, content=html.replace("2026-10-27", "2026-10-28"))
    assert r.nye == 0 and r.uaendrede == 2


def test_rss_enclosure_giver_billede():
    src = Source(id="folkely", navn="Folkely", url="https://www.folkely.dk/blog-feed.xml",
                 type=SourceType.RSS, kategori="kultur", by="Hundested")
    items = parse_rss(src, fixture_text("folkely_feed.xml"))
    assert len(items) == 2
    assert all(i.billede_url.startswith("https://static.wixstatic.com/") for i in items)


def test_kilde_uden_billedtilladelse_gemmer_ingen_billeder(db):
    src = surf_source(billeder=False)
    db.upsert_source(src)
    fetch_source(db, src, content=fixture_text("surfcenter.html"))
    assert all(i.billede_url == "" for i in db.get_raw_items(source_id="surf"))


def test_sitemap_moenster_udelukker_oversigtssider():
    src = Source(id="hk", navn="Halsnæs", url="https://halsnaes.dk/sitemap.xml", type=SourceType.SITEMAP,
                 kategori="kommune", by="Halsnæs",
                 sitemap={"prefix": "https://halsnaes.dk/nyheder/",
                          "moenster": r"^https://halsnaes\.dk/nyheder/\d{4}/[^/]+/[^/]+$"})
    xml = """<urlset>
      <url><loc>https://halsnaes.dk/nyheder/2026</loc><lastmod>2026-10-01</lastmod></url>
      <url><loc>https://halsnaes.dk/nyheder/2024/nov</loc><lastmod>2026-10-02</lastmod></url>
      <url><loc>https://halsnaes.dk/nyheder/2026/sep/kom-til-borgermoede</loc><lastmod>2026-09-14</lastmod></url>
    </urlset>"""
    assert [u for u, _ in parse_sitemap(src, xml)] == ["https://halsnaes.dk/nyheder/2026/sep/kom-til-borgermoede"]


def test_hel_side_bliver_et_opslag():
    src = Source(id="fl", navn="Folkely", url="https://www.folkely.dk/", type=SourceType.HTML,
                 kategori="kultur", by="Hundested", html={"hel_side": True, "resume": "main"})
    html = ('<html><head><title>Folkely Festival</title><meta property="og:image" content="/plakat.jpg"></head>'
            '<body><nav>Menu</nav><main>Dizzy Mizz Lizzy torsdag</main></body></html>')
    [item] = parse_html(src, html)
    assert item.url == "https://www.folkely.dk/"
    assert item.titel == "Folkely Festival"
    assert item.tekst == "Dizzy Mizz Lizzy torsdag"
    assert item.billede_url == "https://www.folkely.dk/plakat.jpg"


def test_parse_boligsiden():
    src = Source(id="boliger", navn="Boliger", url="https://api.boligsiden.dk/x", type=SourceType.BOLIGSIDEN,
                 kategori="bolig", by="Hundested")
    items = parse_boligsiden(src, fixture_text("boligsiden.json"))
    assert len(items) == 2
    b = items[0]
    assert b.titel == "Peder Olsensvej 18, Hundested"
    assert b.url.startswith("https://")
    assert b.data["pris"] == 3495000 and b.data["type"] == "Villa"
    assert b.data["maegler"] == "home Hundested"
    assert "3.495.000 kr." in b.tekst
    assert b.billede_url.startswith("https://images.boligsiden.dk/")


def test_bolig_data_gemmes_og_laeses(db):
    src = Source(id="boliger", navn="Boliger", url="https://api.boligsiden.dk/x", type=SourceType.BOLIGSIDEN,
                 kategori="bolig", by="Hundested")
    db.upsert_source(src)
    assert fetch_source(db, src, content=fixture_text("boligsiden.json")).nye == 2
    gemt = db.get_raw_items(source_id="boliger")
    assert {b.data["adresse"] for b in gemt} == {"Peder Olsensvej 18", "Pilealle 3A"}


def test_stockfotos_frasorteres(db):
    src = surf_source()
    db.upsert_source(src)
    html = fixture_text("surfcenter.html").replace("saunagus-640x360.jpg", "colourbox55694453.jpg")
    fetch_source(db, src, content=html)
    sauna = db.get_raw_item("surf", "https://surfcenter.dk/vare/saunagus/")
    assert sauna.billede_url == ""
