"""Hjemmesiden bygges uden internet ud fra en database i hukommelsen."""

from datetime import datetime

from gulvmaatten.models import Article, RawItem, ReviewStatus, Source, SourceType
from gulvmaatten.site import byg_site, sektion, slugify, ugedato

NU = datetime(2026, 10, 27, 12, 0)


def _artikel(db, overskrift, kategori="kultur", status=ReviewStatus.APPROVED, billede=""):
    a = Article(overskrift=overskrift, resume=f"Resumé af {overskrift}.", broedtekst="Tekst.\n\nPraktisk: Gratis.",
                kategori=kategori, by="Hundested", kilder=["https://kilde.dk/1"], status=status,
                billede_url=billede, billede_kredit="Foto: Kilden" if billede else "")
    db.save_article(a)
    return a


def test_slugify_og_dato():
    assert slugify("Ny sauna på Lynæs Havn åbner") == "ny-sauna-paa-lynaes-havn-aabner"
    assert ugedato(NU) == "Uge 44 | Oktober 2026"


def test_folkely_og_udland_faar_egne_sektioner():
    a = Article(overskrift="x", resume="", broedtekst="", kategori="kultur", by="", tags=["Folkely"])
    assert sektion(a) == "folkely"
    a = Article(overskrift="x", resume="", broedtekst="", kategori="udlandsstof", by="Frederiksværk")
    assert sektion(a) == "udland"


def test_byg_site_publicerer_godkendte_og_skjuler_udkast(db, tmp_path):
    godkendt = _artikel(db, "Sandskulpturer på havnen", billede="https://kilde.dk/foto.jpg")
    _artikel(db, "Hemmeligt udkast", status=ReviewStatus.NEEDS_REVIEW)
    _artikel(db, "Udlandsstof: Kanalen er tør", kategori="udlandsstof")
    byg_site(db, tmp_path, nu=NU)

    forside = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Gulvmåtten" in forside and "Uge 44" in forside
    assert "Sandskulpturer på havnen" in forside
    assert "Foto: Kilden" in forside, "billeder skal altid vises med kreditering"
    assert "Hemmeligt udkast" not in forside
    assert "Udlandsstof" in forside and "Kanalen er tør" in forside
    assert db.get_article(godkendt.id).status == ReviewStatus.PUBLISHED

    artikel = (tmp_path / "artikel" / "sandskulpturer-paa-havnen.html").read_text(encoding="utf-8")
    assert 'class="praktisk"' in artikel and "https://kilde.dk/1" in artikel


def test_forhaandsvisning_viser_udkast_markeret(db, tmp_path):
    _artikel(db, "Hemmeligt udkast", status=ReviewStatus.NEEDS_REVIEW)
    byg_site(db, tmp_path, forhaandsvisning=True, nu=NU)
    forside = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Hemmeligt udkast" in forside and 'class="udkast"' in forside
    assert db.get_articles(ReviewStatus.PUBLISHED) == []


def test_boliger_vises_med_pris_og_maegler(db, tmp_path):
    db.upsert_source(Source(id="boliger-til-salg", navn="Boliger", url="https://x", type=SourceType.BOLIGSIDEN,
                            kategori="bolig", by="Hundested"))
    for i, dage in enumerate([30, 2, 9]):
        db.record_raw_item(RawItem(source_id="boliger-til-salg", url=f"https://maegler.dk/{i}", titel=f"Vej {i}",
                                   data={"adresse": f"Vej {i}", "pris": 2500000 + i, "type": "Villa",
                                         "maegler": "home Hundested", "dage_til_salg": dage}))
    byg_site(db, tmp_path, nu=NU)
    forside = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Nye boliger til salg" in forside
    # De to nyeste på markedet, ikke den der har været til salg i 30 dage
    assert "Vej 1" in forside and "Vej 2" in forside and "Vej 0" not in forside
    assert "2.500.001 kr." in forside
