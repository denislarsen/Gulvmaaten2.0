"""Tester redaktionens logik med en falsk Claude-klient, så testene er gratis
og ikke kræver internet."""

from types import SimpleNamespace

from datetime import datetime

from gulvmaatten.agent import Udkast, Vurdering, behandl_item, find_relaterede, noegleord
from gulvmaatten.models import RawItem, ReviewStatus, RiskLevel
from gulvmaatten.publicering import saet_autogodkend


class FakeMessages:
    def __init__(self, svar: list):
        self.svar = list(svar)
        self.kald = []

    def parse(self, **kwargs):
        self.kald.append(kwargs)
        return SimpleNamespace(parsed_output=self.svar.pop(0))


class FakeClient:
    def __init__(self, svar: list):
        self.messages = FakeMessages(svar)


def _item(db, source, titel, tekst="", url=None, dato_tekst=""):
    it = RawItem(source_id=source.id, url=url or f"https://www.eksempel.dk/nyheder/{len(titel)}-{titel[:8]}",
                 titel=titel, tekst=tekst, dato_tekst=dato_tekst)
    db.record_raw_item(it)
    return it


def test_noegleord_fjerner_stopord():
    assert noegleord("Ny legeplads i Byparken åbner til foråret") == {"legeplads", "byparken", "åbner", "foråret"}


def test_find_relaterede(db, html_source):
    db.upsert_source(html_source)
    a = _item(db, html_source, "Ny legeplads i Byparken åbner til foråret")
    b = _item(db, html_source, "Byparken får ny legeplads", url="https://x.dk/b")
    _item(db, html_source, "Vejarbejde på Hovedvejen", url="https://x.dk/c")
    rel = find_relaterede(db, a)
    assert [r.id for r in rel] == [b.id]


def test_lav_score_giver_ingen_artikel(db, html_source):
    db.upsert_source(html_source)
    item = _item(db, html_source, "Landzonetilladelse til skur på Nybovej 11")
    client = FakeClient([Vurdering(score=1, kategori="kommune", by="Brøndby", risiko="low",
                                   er_arrangement=False, begrundelse="Rutine.")])
    r = behandl_item(db, client, item, {html_source.id: html_source}, hent_tekst=lambda u: "")
    assert r.artikel_id is None
    assert "under tærskel" in r.sprunget_over
    assert len(client.messages.kald) == 1
    assert db.get_articles() == []
    # Opslaget er nu vurderet og kommer ikke igen
    assert db.get_unassessed_raw_items() == []


def test_hoej_score_giver_udkast_til_review(db, html_source):
    db.upsert_source(html_source)
    saet_autogodkend(db, False)
    item = _item(db, html_source, "Ny legeplads i Byparken åbner til foråret",
                 tekst="Kommunalbestyrelsen har afsat 2,4 mio. kr.")
    client = FakeClient([
        Vurdering(score=7, kategori="byudvikling", by="Glostrup", risiko="low",
                  er_arrangement=False, begrundelse="Bred interesse."),
        Udkast(overskrift="Byparken får ny legeplads til foråret", resume="2,4 mio. kr. er afsat.",
               broedtekst="Kommunalbestyrelsen har afsat 2,4 mio. kr. til en ny legeplads.",
               praktisk="Byggeriet starter i januar.", tags=["legeplads", "byparken"],
               kilder=["https://www.eksempel.dk/nyheder/legeplads"], usikkerheder="",
               risiko="medium"),
    ])
    hentede = []

    def hent_tekst(url):
        hentede.append(url)
        return "Fuld tekst fra siden."

    r = behandl_item(db, client, item, {html_source.id: html_source}, hent_tekst=hent_tekst)
    assert r.artikel_id is not None
    assert hentede == [item.url]
    assert len(client.messages.kald) == 2
    # Fuld tekst og regler nåede frem til skrivetrinnet
    skriv_prompt = client.messages.kald[1]["messages"][0]["content"]
    assert "Fuld tekst fra siden." in skriv_prompt
    assert "Ingen opdigtede fakta" in client.messages.kald[1]["system"]

    a = db.get_article(r.artikel_id)
    assert a.status == ReviewStatus.NEEDS_REVIEW
    assert a.overskrift == "Byparken får ny legeplads til foråret"
    assert a.praktisk == "Byggeriet starter i januar."
    assert "Praktisk" not in a.broedtekst
    assert db.get_publication(a.id) is None, "intet publiceres, når autogodkendelse er slået fra"
    assert a.kilder[0] == item.url and "https://www.eksempel.dk/nyheder/legeplads" in a.kilder
    assert a.risiko == RiskLevel.MEDIUM, "højeste risiko af vurdering og udkast skal vinde"
    assert a.raw_item_ids == [item.id]


def test_aendret_opslag_vurderes_igen(db, html_source):
    db.upsert_source(html_source)
    item = _item(db, html_source, "Koncert i kulturhuset", tekst="Lørdag kl. 20")
    db.save_assessment(item.id, 6, "kultur", "low", "ok")
    assert db.get_unassessed_raw_items() == []
    aendret = RawItem(source_id=item.source_id, url=item.url, titel=item.titel, tekst="AFLYST")
    assert db.record_raw_item(aendret) == "aendret"
    assert [i.id for i in db.get_unassessed_raw_items()] == [item.id]


def _arrangement_svar():
    return [
        Vurdering(score=6, kategori="kultur", by="Glostrup", risiko="low",
                  er_arrangement=True, begrundelse="Åbent arrangement."),
        Udkast(overskrift="Forfatteraften i Sognegården", resume="En forfatter kommer til Glostrup.",
               broedtekst="Han fortæller om sin nye roman.", praktisk="Hvor: Glostrup Sognegård\nPris: Gratis",
               tags=["kultur"], kilder=[], usikkerheder="", risiko="low"),
    ]


def test_autogodkendelse_publicerer_med_dato_fra_kilden(db, html_source):
    db.upsert_source(html_source)
    saet_autogodkend(db, True)
    item = _item(db, html_source, "Forfatteraften med Jens Christian Grøndahl",
                 dato_tekst="19. november 2026 19:00 - 21:00")
    r = behandl_item(db, FakeClient(_arrangement_svar()), item, {html_source.id: html_source},
                     hent_tekst=lambda u: "", nu=datetime(2026, 10, 21))
    assert r.publiceret
    a = db.get_article(r.artikel_id)
    assert a.status == ReviewStatus.PUBLISHED
    assert a.er_arrangement and a.arrangement_start == datetime(2026, 11, 19, 19, 0)
    assert db.get_publication(a.id).slug == "forfatteraften-i-sognegaarden"


def test_gamle_opslag_springes_over_uden_api_kald(db, html_source):
    db.upsert_source(html_source)
    item = _item(db, html_source, "Gammel nyhed", dato_tekst="Mon, 08 Jan 2024 09:21:00 +0000")
    client = FakeClient([])
    r = behandl_item(db, client, item, {html_source.id: html_source}, nu=datetime(2026, 10, 21))
    assert client.messages.kald == []
    assert r.artikel_id is None and "For gammelt" in r.sprunget_over
    assert db.get_unassessed_raw_items() == [], "gamle opslag skal ikke vurderes igen næste gang"


def test_vurderingen_kender_dagens_dato(db, html_source):
    db.upsert_source(html_source)
    item = _item(db, html_source, "Koncert", dato_tekst="20.10.2026")
    client = FakeClient([Vurdering(score=1, kategori="kultur", by="Brøndby", risiko="low",
                                   er_arrangement=True, begrundelse="Har fundet sted.")])
    behandl_item(db, client, item, {html_source.id: html_source}, nu=datetime(2026, 10, 21))
    assert "21. oktober 2026" in client.messages.kald[0]["messages"][0]["content"]
