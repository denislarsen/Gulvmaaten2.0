# Gulvmåtten 2.0

Et lokalt bymedie for Hundested med en agentisk redaktion.

Navnet stammer fra den gratis lokalavis i Hundested, som mange brugte som
gulvmåtte. Resten af Halsnæs Kommune er ikke vores stofområde. Frederiksværk
optræder kun en gang imellem, under kategorien "udlandsstof".

Systemet overvåger lokale kilder, registrerer nye eller ændrede oplysninger,
vurderer nyhedsværdi, skriver korte kildebelagte artikeludkast og lægger dem
til manuel godkendelse, før noget publiceres. Godkendte artikler bliver til
en statisk hjemmeside i avisstil.

## Status

Det, der virker nu:

- Konfiguration af by, nøgleord, kategorier og kildeprofiler (`config/`)
- Datamodel og SQLite-database (`gulvmaatten/models.py`, `gulvmaatten/db.py`)
- Crawler for RSS, HTML, sitemaps og Boligsiden, inklusive billeder
  (`gulvmaatten/fetch.py`)
- Otte kilder verificeret mod de rigtige hjemmesider: Halsnæs Kommune,
  Hundested Havn, Lynæs Surfcenter og Madbaren, Lynæs Sejl- og Kajakklub,
  Folkely (pressefeed og forside), Frederiksborg Amts Avis' Halsnæs-side og
  Boligsiden for 3390
- Redaktion med Claude: vurdering, research og udkast (`gulvmaatten/agent.py`)
- Madsektion med "Ugens spisested" og fast kørselsplan (`gulvmaatten/mad.py`)
- Hjemmeside i avisstil med sektioner for havnen og kulturen, Folkely, sport,
  mad, boliger til salg og udlandsstof. Tre kolonner på store skærme, én på
  telefoner (`gulvmaatten/site.py`, `gulvmaatten/style.css`)
- Testdata og automatiske tests (`tests/`)

Det mangler:

- Futsal: Hundested IK's egen side er ikke fundet. Kilden står i
  `sources.yaml` som inaktiv, indtil vi har en adresse
- Halsnæs Bibliotekerne og Halsnæs Avis' egen side (sn.dk dækker begge aviser)
- Sociale medier hentes ikke automatisk (se nedenfor)
- Opfølgning: opdatering af artikler og markering af aflyste arrangementer

## Sådan kører du det

Kræver Python 3.11 eller nyere. Redaktionen kræver en API-nøgle i
`GULVMAATTEN_API_KEY` (eller `ANTHROPIC_API_KEY`).

```bash
pip install -r requirements.txt

python -m gulvmaatten init            # Opret databasen og registrér kilderne
python -m gulvmaatten fetch           # Hent alle kilder
python -m gulvmaatten redaktion       # Vurdér nye opslag og skriv udkast
python -m gulvmaatten udkast          # Se udkast, der venter på en redaktør
python -m gulvmaatten vis 3           # Læs udkast nr. 3
python -m gulvmaatten godkend 3       # Godkend det
python -m gulvmaatten site            # Publicér godkendte artikler og byg site/

python -m gulvmaatten site --forhaandsvisning   # Se forsiden med udkast (markeret UDKAST)

python -m gulvmaatten spisesteder find    # Er der nye spisesteder på havnen?
python -m gulvmaatten spisesteder ugens   # Udkast til "Ugens spisested"
python -m gulvmaatten godkend 7 --karakter 5  # Godkend anmeldelse med 5 af 6 gulvmåtter

python -m pytest                      # Tests (kræver ikke internet)
```

### Kørselsplan

`python -m gulvmaatten planlagt` kører alt, der er forfaldent: kilder efter
deres `frekvens`, redaktionen, "Ugens spisested" hver 7. dag og tjek for nye
spisesteder hver 30. dag. Frekvenserne står under `mad:` i
`config/gulvmaatten.yaml`. Kør den fx hver time fra cron:

```
0 * * * * cd /sti/til/gulvmaaten2.0 && python -m gulvmaatten planlagt >> data/planlagt.log 2>&1
```

## Madsektionen

"Ugens spisested" tager spisestederne i `config/steder.yaml` på skift. Steder,
der aldrig har været med, kommer først, og intet sted kommer igen inden for
180 dage.

Agenten kan ikke smage maden. Udkastet indeholder derfor kun, hvad stedet selv
oplyser, plus en tjekliste til redaktøren. Brødteksten slutter med en
pladsholder til redaktørens dom, og artiklen kan ikke godkendes, før den er
udfyldt. Karakteren gives i gulvmåtter (1-6) med `godkend --karakter`.

## Sociale medier

Facebook og Instagram kan ikke hentes automatisk uden at bryde deres vilkår,
og siderne kræver login. Profilerne for havnen, Oplev Hundested, Folkely og
spisestederne står i `config/steder.yaml`, så de kan tjekkes manuelt.
Mulige løsninger senere: få sideejerne til at give adgang via Meta Graph API,
eller bed arrangørerne sende pressemeddelelser til en fast mailadresse, som
systemet læser.

## Billeder

Billeder kommer indtil videre fra kilderne selv og vises altid med
kreditering. Andre mediers billeder bruges aldrig. Se `docs/billeder.md` for
rettighedsspørgsmålet og næste skridt.

## Projektstruktur

```
config/
  gulvmaatten.yaml   By, nøgleord, kategorier, madplan, annoncer
  sources.yaml       Kildeprofiler (navn, URL, type, tillid, frekvens, billeder ...)
  steder.yaml        Spisesteder, kultursteder og foreninger med links til sociale medier
gulvmaatten/
  models.py          Datamodel: Source, RawItem, Event, Article, ReviewStatus, Publication
  db.py              SQLite-lager
  fetch.py           Crawler for RSS, HTML, sitemap og Boligsiden
  agent.py           Redaktion: vurdering, research og udkast
  mad.py             Ugens spisested og nye spisesteder
  site.py            Statisk hjemmeside
  style.css          Hjemmesidens layout
  __main__.py        Kommandolinje
docs/
  datamodel.md       Forklaring af datamodellen
  workflow.md        Den redaktionelle pipeline trin for trin
  billeder.md        Billeder og rettigheder
tests/
  fixtures/          Gemte eksempler fra de rigtige kilder
  test_*.py          Automatiske tests
data/                Database (oprettes automatisk, ikke i git)
site/                Den byggede hjemmeside (ikke i git)
```

## Redaktionelle principper

Se `docs/workflow.md`. Kort: korrekt før hurtigt, ingen opdigtede fakta,
tydelig kildeangivelse, andre medier er tips og ikke kilder, og en redaktør
godkender alt, før det publiceres.
