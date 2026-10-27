"""Madsektionen med en falsk Claude-klient."""

from datetime import datetime, timedelta

from conftest import fixture_text
from test_agent import FakeClient

from gulvmaatten.mad import (
    KOERSEL_UGENS, Spisested, SpisestedUdkast, er_forfalden, karakter, lav_ugens_spisested,
    nye_spisesteder, parse_havnens_spisesteder, vaelg_spisested,
)
from gulvmaatten.models import Article, ReviewStatus, RiskLevel

STEDER = [
    Spisested(id="bryghus", navn="Halsnæs Bryghus", web="https://halsbryg.dk/"),
    Spisested(id="kamelens-kys", navn="Kamelens Kys"),
    Spisested(id="fjordens", navn="Fjordens Café og Ishus"),
]


def test_havnens_liste_kun_spisesteder():
    navne = parse_havnens_spisesteder(fixture_text("havn_spisesteder.html"))
    assert navne == ["Halsnæs Bryghus", "Kamelens Kys", "Fjordens Cafe og ishus - minigolf", "Nyt Fiskehus"]


def test_nye_spisesteder_genkender_kendte_trods_stavemaade():
    navne = parse_havnens_spisesteder(fixture_text("havn_spisesteder.html"))
    assert nye_spisesteder(navne, STEDER) == ["Nyt Fiskehus"]


def _omtal(db, sted_id, dage_siden):
    a = Article(overskrift=f"Ugens spisested: {sted_id}", resume="", broedtekst="", kategori="mad",
                by="Hundested", tags=[f"spisested:{sted_id}"], kilder=["https://x.dk"],
                oprettet=datetime.now() - timedelta(days=dage_siden))
    db.save_article(a)


def test_vaelg_tager_aldrig_omtalte_foerst(db):
    _omtal(db, "bryghus", 400)
    assert vaelg_spisested(db, STEDER, 180).id == "kamelens-kys"


def test_vaelg_springer_nyligt_omtalte_over(db):
    for s, dage in (("bryghus", 10), ("kamelens-kys", 300), ("fjordens", 200)):
        _omtal(db, s, dage)
    assert vaelg_spisested(db, STEDER, 180).id == "kamelens-kys"
    assert vaelg_spisested(db, STEDER, 365) is None


def test_ugens_spisested_er_udkast_med_hoej_risiko(db):
    client = FakeClient([SpisestedUdkast(
        overskrift="Ugens spisested: Halsnæs Bryghus", resume="Bryghus på havnen.",
        broedtekst="Bryghuset brygger øl på havnen.", praktisk="Nordre Beddingsvej 35.",
        tjekliste=["Smag husets pilsner", "Spørg til åbningstider om vinteren"],
        kilder=["https://halsbryg.dk/"], usikkerheder="Åbningstider ikke oplyst.")])
    artikel_id = lav_ugens_spisested(db, client, steder=STEDER[:1], hent_tekst=lambda u: "Vi brygger øl.",
                                     hent_billede=lambda u: "https://halsbryg.dk/foto.jpg")
    a = db.get_article(artikel_id)
    assert a.status == ReviewStatus.NEEDS_REVIEW
    assert a.risiko == RiskLevel.HIGH
    assert a.kategori == "mad" and "spisested:bryghus" in a.tags
    assert "[Udfyldes efter besøg" in a.broedtekst
    assert "Smag husets pilsner" in a.redaktoer_note
    assert a.billede_kredit == "Foto: Halsnæs Bryghus"
    # Agenten får besked på ikke at vurdere maden
    prompt = client.messages.kald[0]["messages"][0]["content"]
    assert "kan ikke smage maden" in prompt and "Vi brygger øl." in prompt
    assert not er_forfalden(db, KOERSEL_UGENS, 7)


def test_karakter_fra_tag():
    a = Article(overskrift="x", resume="", broedtekst="", kategori="mad", by="", tags=["karakter:5"])
    assert karakter(a) == 5
    a.tags = []
    assert karakter(a) is None
