# Gulvmåtten på Railway

Gulvmåtten kører som én service på Railway:

- Hjemmesiden vises på tjenestens adresse.
- Hver time hentes kilderne, redaktionen og kalenderen kører, og hjemmesiden
  bygges igen.
- Redaktøren godkender udkast på `/redaktion` med en adgangskode.

Database og hjemmeside ligger på en vedvarende disk (et "volume"), så de
overlever, når tjenesten genstartes eller opdateres.

## Det skal du bruge

- En Railway-konto, der er forbundet med din GitHub-konto. Til drift døgnet
  rundt kræver Railway et betalt abonnement. Tjek den aktuelle pris på
  railway.com/pricing.
- Din Anthropic API-nøgle.
- En adgangskode til redaktørsiden, som du selv finder på.

## Opsætning, trin for trin

1. **Ny tjeneste fra GitHub.** I Railway: *New Project* → *Deploy from GitHub
   repo* → vælg `denislarsen/Gulvmaaten2.0`, gren `main`. Railway finder
   `Dockerfile` og bygger ud fra den.
2. **Disk.** Højreklik på projektets lærred (eller tryk ⌘K) → opret et
   volume → vælg Gulvmåtten-tjenesten → sæt *mount path* til `/data`.
3. **Variabler.** Under tjenestens *Variables*:
   | Navn | Værdi |
   |---|---|
   | `GULVMAATTEN_API_KEY` | Din Anthropic API-nøgle |
   | `GULVMAATTEN_REDAKTOER_KODE` | Adgangskoden til `/redaktion` |
   `PORT` og `GULVMAATTEN_DATA` skal du ikke sætte: Railway sætter `PORT`,
   og `GULVMAATTEN_DATA=/data` står i Dockerfile.
4. **Offentlig adresse.** Under *Settings* → *Networking* → *Generate Domain*.
   Senere kan du tilføje dit eget domæne samme sted.
5. **Sundhedstjek (valgfrit).** Under *Settings* → *Deploy* kan du sætte
   healthcheck-stien til `/sundhed`.

Første gang tjenesten starter, er databasen tom. Efter cirka et minut kører
den første faste kørsel, og så kommer der kalender, boliger og de første udkast.
Følg med under tjenestens *Deploy Logs*.

## Daglig brug

- Gå til `https://<din-adresse>/redaktion`. Brugernavnet er ligegyldigt;
  adgangskoden er `GULVMAATTEN_REDAKTOER_KODE`.
- Klik på et udkast, ret overskrift, resumé eller brødtekst, og tryk
  *Gem og godkend*. Artiklen ligger på forsiden med det samme.
- "Ugens spisested" kan først godkendes, når pladsholderen til redaktørens dom
  er skiftet ud med din egen tekst. Vælg samtidig antal gulvmåtter.
- Tips fra andre medier og Facebook-grupper kan ikke publiceres. De står der,
  så du kan finde en selvstændig kilde.

## Hvis noget går galt

| Symptom | Årsag |
|---|---|
| `/redaktion` siger "slået fra" | `GULVMAATTEN_REDAKTOER_KODE` er ikke sat |
| Loggen siger "Ingen API-nøgle" | `GULVMAATTEN_API_KEY` er ikke sat |
| Alt er væk efter en opdatering | Disken er ikke monteret på `/data` |
| "Permission denied" i `/data` | Sæt `RAILWAY_RUN_UID=0` (Railways egen anbefaling) |

## Prøv det lokalt først

```bash
GULVMAATTEN_REDAKTOER_KODE=hemmelig python -m gulvmaatten server --port 8000 --hver 0
```

`--hver 0` slår de faste kørsler fra, så der ikke bruges API-kald, mens du
kigger. Åbn http://localhost:8000 og http://localhost:8000/redaktion.
