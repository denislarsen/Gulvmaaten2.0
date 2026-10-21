from datetime import datetime

import pytest

from gulvmaatten.datoer import dansk_dato, klokken, tolk_dato


@pytest.mark.parametrize("tekst, forventet", [
    ("2026-08-04T09:55:54+00:00", datetime(2026, 8, 4, 9, 55, 54)),
    ("Mon, 08 Jan 2024 09:21:00 +0000", datetime(2024, 1, 8, 9, 21)),
    ("20.10.2026", datetime(2026, 10, 20)),
    ("3. november 2026 17:00 - 19:00", datetime(2026, 11, 3, 17, 0)),
    ("Torsdag d. 19. November 2026 kl. 19.00", datetime(2026, 11, 19, 19, 0)),
    ("", None),
    ("snart", None),
    ("31. februar 2026", None),
])
def test_tolk_dato(tekst, forventet):
    assert tolk_dato(tekst) == forventet


def test_dansk_dato_og_klokken():
    d = datetime(2026, 11, 19, 19, 0)
    assert dansk_dato(d) == "torsdag den 19. november 2026"
    assert dansk_dato(d, ugedag=False) == "19. november 2026"
    assert klokken(d) == "kl. 19.00"
    assert klokken(datetime(2026, 11, 19)) == ""
