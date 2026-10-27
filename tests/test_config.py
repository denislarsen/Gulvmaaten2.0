from pathlib import Path

from gulvmaatten.config import load_settings, load_sources
from gulvmaatten.mad import load_spisesteder

ROOT = Path(__file__).parent.parent


def test_settings_kan_laeses():
    s = load_settings(ROOT / "config" / "gulvmaatten.yaml")
    assert [b["navn"] for b in s["byer"]] == ["Hundested"]
    assert "Frederiksværk" in [b["navn"] for b in s["udland"]]
    assert "udlandsstof" in s["kategorier"]
    assert s["mad"]["ugens_spisested_hver_dage"] == 7
    assert s["automatisk_publicering"] is False


def test_kilder_kan_laeses_og_har_unikke_id():
    sources = load_sources(ROOT / "config" / "sources.yaml")
    assert 5 <= len(sources) <= 20
    ids = [s.id for s in sources]
    assert len(ids) == len(set(ids))
    for s in sources:
        assert s.by in ("Hundested", "Halsnæs", "Frederiksværk")
        if s.type.value == "html":
            assert s.html.get("opslag") or s.html.get("hel_side"), f"{s.id} mangler html.opslag"
        if s.aktiv:
            assert s.verificeret, f"{s.id} er aktiv, men ikke verificeret"


def test_andre_mediers_billeder_bruges_aldrig():
    for s in load_sources(ROOT / "config" / "sources.yaml"):
        if s.kategori == "medie":
            assert s.billeder is False, f"{s.id} er et medie og må ikke give billeder"


def test_spisesteder_kan_laeses():
    steder = load_spisesteder(ROOT / "config" / "steder.yaml")
    assert len(steder) >= 5
    assert len({s.id for s in steder}) == len(steder)
    assert any(s.id == "lynaes-madbar" for s in steder)
