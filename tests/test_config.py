from pathlib import Path

from gulvmaatten.config import load_settings, load_sources

ROOT = Path(__file__).parent.parent


def test_settings_kan_laeses():
    s = load_settings(ROOT / "config" / "gulvmaatten.yaml")
    assert [b["navn"] for b in s["byer"]] == ["Glostrup", "Brøndby"]
    assert s["automatisk_publicering"] is True


def test_kilder_kan_laeses_og_har_unikke_id():
    sources = load_sources(ROOT / "config" / "sources.yaml")
    assert 3 <= len(sources) <= 10
    ids = [s.id for s in sources]
    assert len(ids) == len(set(ids))
    for s in sources:
        assert s.by in ("Glostrup", "Brøndby")
        if s.type.value == "html":
            assert s.html.get("opslag"), f"{s.id} mangler html.opslag"
