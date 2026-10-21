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
- Crawler, der henter RSS-feeds, HTML-sider og sitemaps og registrerer nye og
  ændrede opslag (`gulvmaatten/fetch.py`)
- Fem kilder verificeret mod de rigtige hjemmesider: Glostrup og Brøndby
  kommunes nyheder, begge bibliotekers arrangementer og Brøndby IF
- Testdata og automatiske tests (`tests/`)
- Agentisk redaktion, der vurderer opslag og skriver kildebelagte udkast (`gulvmaatten/agent.py`)
- Hjemmeside med forside (nyheder og arrangementer), byvalg, kategorier og
  artikelsider (`gulvmaatten/web.py`, `gulvmaatten/templates/`)
- Redaktionsværktøj bag kodeord: ret, publicér, afvis, træk tilbage, slå
  autogodkendelse til og fra, kør robotten, hent sikkerhedskopi
- Robot, der kører hver time inde i hjemmesiden (`gulvmaatten/robot.py`)
- Klar til Railway (`railway.json`, se `docs/railway.md`)

Det, der kommer senere:

1. Opfølgning: opdatering af artikler og markering af aflyste arrangementer

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

# Start hjemmesiden og robotten på http://localhost:8000
GULVMAATTEN_ADMIN_PASSWORD=vaelg-et-kodeord python -m gulvmaatten serve

# Kør tests (bruger gemte eksempelfiler, kræver ikke internet)
python -m pytest
```

Redaktionen ligger på `/redaktion`. Sådan lægges siden på nettet: `docs/railway.md`.

Databasen ligger i `data/gulvmaatten.db` og oprettes automatisk.

## Projektstruktur

```
config/
  gulvmaatten.yaml   Byer, nøgleord og kategorier
  sources.yaml       Kildeprofiler (navn, URL, type, tillid, frekvens ...)
gulvmaatten/
  models.py          Datamodel: Source, RawItem, Event, Article, ReviewStatus, Publication
  db.py              SQLite-lager
  fetch.py           Crawler for RSS, HTML og sitemap
  datoer.py          Tolkning af kildernes datoer
  agent.py           Den agentiske redaktion: vurdering, research, udkast
  publicering.py     Publicering, tilbagetrækning og autogodkendelse
  robot.py           Robotten, der kører hver time
  web.py             Hjemmesiden og redaktionsværktøjet
  templates/         Sidernes HTML
  static/            Udseende (style.css)
  __main__.py        Kommandolinje: init, fetch, redaktion, serve ...
docs/
  datamodel.md       Forklaring af datamodellen
  workflow.md        Den redaktionelle pipeline trin for trin
  railway.md         Sådan lægges siden på Railway, og sådan flytter man
tests/
  fixtures/          Gemte eksempler på RSS og HTML
  test_*.py          Automatiske tests
data/                Database (oprettes automatisk, ikke i git)
```

## Redaktionelle principper

Se `docs/workflow.md`. Kort: korrekt før hurtigt, ingen opdigtede fakta,
tydelig kildeangivelse. Artikler publiceres automatisk, så længe
autogodkendelse er slået til i redaktionen. Slås den fra, godkender en
redaktør alt, før det publiceres.
