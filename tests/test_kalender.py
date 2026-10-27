"""Kalender og servicehistorier, uden internet og med en falsk Claude-klient."""

from datetime import datetime

from test_agent import FakeClient

from gulvmaatten.kalender import (
    Arrangement, Udtraek, behandl_kalender_item, fremhaevede, kalender_for, ryd_dubletter,
)
from gulvmaatten.models import Event, RawItem, ReviewStatus, Source, SourceType
from gulvmaatten.service import boligmarkedet, det_sker_i_ugen

NU = datetime(2026, 10, 27, 9, 0)


def _arr(titel, start, **kw):
    d = dict(titel=titel, start=start, slut="", sted="Halsnæs Bryghus", by="Hundested", pris="", tilmelding="",
             arrangoer="Bryghuset", beskrivelse="", url="", aflyst=False)
    d.update(kw)
    return Arrangement(**d)


def _kilde(db):
    src = Source(id="bryg", navn="Halsnæs Bryghus", url="https://bryg.dk/kalender", type=SourceType.HTML,
                 kategori="spisested", by="Hundested", kalender=True, kun_kalender=True,
                 html={"hel_side": True})
    db.upsert_source(src)
    item = RawItem(source_id="bryg", url=src.url, titel="Kalender", tekst="Banko torsdag " * 60)
    db.record_raw_item(item)
    return src, item


def test_udtraek_gemmer_kommende_og_springer_overstaaede_over(db):
    src, item = _kilde(db)
    client = FakeClient([Udtraek(arrangementer=[
        _arr("Banko", "2026-10-29T19:30", pris="20 kr."),
        _arr("Gammel koncert", "2026-08-01T20:00"),
        _arr("Uden dato", "snart"),
    ])])
    r = behandl_kalender_item(db, client, item, src, nu=NU)
    assert r.antal == 1
    [e] = db.kommende_events(NU)
    assert e.titel == "Banko" and e.url == src.url and e.source_id == "bryg"
    assert "Gæt aldrig et klokkeslæt" in client.messages.kald[0]["messages"][0]["content"]
    # Opslaget er gennemgået og kommer ikke igen
    assert db.opslag_til_kalender() == []


def test_aendret_side_erstatter_arrangementer(db):
    src, item = _kilde(db)
    behandl_kalender_item(db, FakeClient([Udtraek(arrangementer=[_arr("Banko", "2026-10-29T19:30")])]),
                          item, src, nu=NU)
    behandl_kalender_item(db, FakeClient([Udtraek(arrangementer=[_arr("Quiz", "2026-10-30T19:00")])]),
                          item, src, nu=NU)
    assert [e.titel for e in db.kommende_events(NU)] == ["Quiz"]


def test_dubletter_beholder_versionen_med_flest_oplysninger():
    a = Event(titel="En søgen efter eventyr", start=datetime(2026, 11, 3))
    b = Event(titel="En Søgen Efter Eventyr med Emil", start=datetime(2026, 11, 3, 18, 30), sted="Biblioteket")
    assert ryd_dubletter([a, b]) == [b]


def test_kalender_kun_hundested_og_hele_dage(db):
    for titel, by, start in (("Lynæs-marked", "Hundested", datetime(2026, 11, 3, 18, 30)),
                             ("Koncert i Frederiksværk", "Frederiksværk", datetime(2026, 10, 28, 20))):
        db.save_event(Event(titel=titel, start=start, by=by))
    # Arrangementet sidst på dag 7 kommer med, selv om klokken nu er 9
    assert [e.titel for e in kalender_for(db, NU, dage=7)] == ["Lynæs-marked"]


def test_fremhaevede_springer_tilbagevendende_over():
    ev = [Event(titel="Fredagsøl", start=datetime(2026, 10, 30, 15)),
          Event(titel="ABBA Tribute", start=datetime(2026, 10, 30, 20)),
          Event(titel="Fredagsøl", start=datetime(2026, 11, 6, 15))]
    assert [e.titel for e in fremhaevede(ev)] == ["ABBA Tribute"]


def test_det_sker_i_ugen(db):
    for i in range(4):
        db.save_event(Event(titel=f"Arrangement {i}", start=datetime(2026, 10, 28 + i, 19), by="Hundested",
                            sted="Hundested Bibliotek", url=f"https://bib.dk/{i}"))
    a = db.get_article(det_sker_i_ugen(db, NU))
    assert a.overskrift == "Det sker i Hundested i uge 44"
    assert a.status == ReviewStatus.NEEDS_REVIEW
    assert "Onsdag 28. oktober kl. 19.00: Arrangement 0" in a.broedtekst
    assert a.kilder[0] == "https://bib.dk/0"


def test_boligmarkedet(db):
    db.upsert_source(Source(id="boliger-til-salg", navn="Boliger", url="https://x", type=SourceType.BOLIGSIDEN,
                            kategori="bolig", by="Hundested"))
    for i, (pris, areal, dage) in enumerate([(1_000_000, 100, 3), (2_000_000, 100, 20), (3_000_000, 150, 40),
                                             (4_000_000, 200, 2), (5_000_000, 100, 90)]):
        db.record_raw_item(RawItem(source_id="boliger-til-salg", url=f"https://m.dk/{i}", titel=f"Vej {i}",
                                   data={"adresse": f"Vej {i}", "pris": pris, "boligareal": areal,
                                         "type": "Villa", "dage_til_salg": dage}))
    a = db.get_article(boligmarkedet(db, NU))
    assert a.overskrift == "5 boliger til salg i Hundested"
    assert "5 villaer" in a.broedtekst and "3.000.000 kr." in a.broedtekst
    assert "Billigst er Vej 0" in a.broedtekst and "kr.." not in a.broedtekst
    assert a.resume.startswith("2 nye på markedet")
