"""Tester redaktionens logik med en falsk Claude-klient, så testene er gratis
og ikke kræver internet."""

from types import SimpleNamespace

from gulvmaatten.agent import Udkast, Vurdering, behandl_item, find_relaterede, noegleord
from gulvmaatten.models import RawItem, ReviewStatus, RiskLevel


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


def _item(db, source, titel, tekst="", url=None):
    it = RawItem(source_id=source.id, url=url or f"https://www.eksempel.dk/nyheder/{len(titel)}-{titel[:8]}",
                 titel=titel, tekst=tekst)
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
    assert "Praktisk: Byggeriet starter i januar." in a.broedtekst
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
