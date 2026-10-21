from pathlib import Path

import pytest

from gulvmaatten.db import Database
from gulvmaatten.models import Source, SourceType

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def html_source():
    return Source(
        id="test-kommune", navn="Test Kommune", url="https://www.eksempel.dk/nyheder",
        type=SourceType.HTML, kategori="kommune", by="Glostrup", tillid=5,
        html={"opslag": "article.news-item", "titel": "h2", "link": "a", "dato": "time", "resume": "p.teaser"},
    )


@pytest.fixture
def rss_source():
    return Source(
        id="test-bib", navn="Test Bibliotek", url="https://eksempelbib.dk/rss",
        type=SourceType.RSS, kategori="bibliotek", by="Brøndby", tillid=4,
    )


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
