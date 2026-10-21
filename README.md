# Gulvmåtten 2.0

Et lokalt bymedie for Glostrup og Brøndby med en agentisk redaktion.

Systemet overvåger lokale kilder, registrerer nye eller ændrede oplysninger,
vurderer nyhedsværdi, skriver korte kildebelagte artikeludkast og lægger dem
til manuel godkendelse, før noget publiceres.

Navnet stammer fra den gratis lokalavis i Hundested, som mange brugte som
gulvmåtte.

## Status

Første fase. Det, der virker nu:

- Konfiguration af byer, nøgleord og kildeprofiler (`config/`)
- Datamodel og SQLite-database (`gulvmaatten/models.py`, `gulvmaatten/db.py`)
- Crawler, der henter RSS-feeds og HTML-sider og registrerer nye og ændrede
  opslag (`gulvmaatten/fetch.py`)
- Testdata og automatiske tests (`tests/`)

Det, der kommer senere, i den rækkefølge:

1. Vurderings- og research-workflow, der laver et artikeludkast med kilder
2. Manuel godkendelsesproces (review)
3. Hjemmeside med artikeloversigt, kategorier og enkeltsider
4. Opfølgning: opdatering af artikler og markering af aflyste arrangementer

## Sådan kører du det

Kræver Python 3.11 eller nyere.

```bash
pip install -r requirements.txt

# Opret databasen og registrér kilderne fra config/sources.yaml
python -m gulvmaatten init

# Hent alle kilder og registrér nye og ændrede opslag
python -m gulvmaatten fetch

# Vis hvad der er fundet
python -m gulvmaatten list

# Kør tests (bruger gemte eksempelfiler, kræver ikke internet)
python -m pytest
```

Databasen ligger i `data/gulvmaatten.db` og oprettes automatisk.

## Projektstruktur

```
config/
  gulvmaatten.yaml   Byer, nøgleord og kategorier
  sources.yaml       Kildeprofiler (navn, URL, type, tillid, frekvens ...)
gulvmaatten/
  models.py          Datamodel: Source, RawItem, Event, Article, ReviewStatus, Publication
  db.py              SQLite-lager
  fetch.py           Crawler for RSS og HTML
  __main__.py        Kommandolinje: init, fetch, list
docs/
  datamodel.md       Forklaring af datamodellen
  workflow.md        Den redaktionelle pipeline trin for trin
tests/
  fixtures/          Gemte eksempler på RSS og HTML
  test_*.py          Automatiske tests
data/                Database (oprettes automatisk, ikke i git)
```

## Redaktionelle principper

Se `docs/workflow.md`. Kort: korrekt før hurtigt, ingen opdigtede fakta,
tydelig kildeangivelse, og en redaktør godkender alt, før det publiceres.
