# Gulvmåtten på Railway

Gulvmåtten kører som én service på Railway. Hvorfor ikke Vercel? Vercel er
lavet til hjemmesider og korte funktioner. Gulvmåtten har brug for en
database på en disk, der bliver liggende, og for en kørsel hver time, der kan
tage mere end fem minutter. Det er ikke muligt på Vercels gratis plan.
Password-beskyttelse koster desuden ekstra der (Pro-planen plus et tillæg pr.
projekt). Railway kører programmet, som det er.

Det, der kører:

- Hjemmesiden vises på tjenestens adresse.
- Hver time hentes kilderne, redaktionen og kalenderen kører, og hjemmesiden
  bygges igen.
- Redaktøren godkender udkast på `/redaktion`.
- Siden er privat, indtil du slår den offentlig til. Man kommer ind med et
  personligt link eller redaktørens kode (se "Adgang" nedenfor).

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
   | `GULVMAATTEN_REDAKTOER_KODE` | Din egen kode til at logge ind. Brug mindst 16 tegn |
   `PORT` og `GULVMAATTEN_DATA` skal du ikke sætte: Railway sætter `PORT`,
   og `GULVMAATTEN_DATA=/data` står i Dockerfile.
4. **Offentlig adresse.** Under *Settings* → *Networking* → *Generate Domain*.
   Senere kan du tilføje dit eget domæne samme sted.
5. **Sundhedstjek (valgfrit).** Under *Settings* → *Deploy* kan du sætte
   healthcheck-stien til `/sundhed`.

Første gang tjenesten starter, er databasen tom. Efter cirka et minut kører
den første faste kørsel, og så kommer der kalender, boliger og de første udkast.
Følg med under tjenestens *Deploy Logs*.

## Adgang

Siden er privat som standard. Der er to måder at komme ind på:

- **Din kode.** Gå til `https://<din-adresse>/log-ind` og skriv
  `GULVMAATTEN_REDAKTOER_KODE`. Så er du redaktør.
- **Personlige links til andre.** I redaktionen: *Adgang* → skriv navnet,
  vælg *Læser* eller *Redaktør* → *Lav link*. Send linket, fx på sms. Når
  personen åbner det, er vedkommende logget ind i 30 dage i den browser. Linket
  kan bruges igen, fx på en ny telefon. Klik *Spær* for at lukke det; så er
  personen logget ud med det samme.

Sådan er det sikret:

- Et link er et tilfældigt "token" på 43 tegn. Det kan ikke gættes.
- Hverken links eller logins gemmes i klartekst, kun et fingeraftryk. En kopi
  af databasen giver ikke adgang.
- Login-cookien kan ikke læses af JavaScript (`HttpOnly`), sendes kun over
  https (`Secure`) og ikke med formularer fra andre sider (`SameSite`).
- Formularer fra andre sider afvises, og forkerte koder giver et sekunds pause.
- Søgemaskiner bliver bedt om at holde sig væk (`robots.txt` og `noindex`).
- Linkene skrives aldrig i loggen.

Mens siden er privat, vises udkast på forsiden, markeret UDKAST, så I kan se
strømmen af nyheder. Inde i et udkast står "Til redaktøren"-boksen med
usikkerheder, som læserne også kan se. Sæt `GULVMAATTEN_VIS_UDKAST=nej`, hvis
kun godkendte artikler skal vises.

Når siden skal være offentlig: sæt `GULVMAATTEN_ADGANG=offentlig`. Så kan alle
se forsiden, udkast vises ikke længere, og kun `/redaktion` kræver login.

## Daglig brug

- Gå til `https://<din-adresse>/redaktion` (log ind først, hvis du bliver bedt om det).
- Klik på et udkast, ret overskrift, resumé eller brødtekst, og tryk
  *Gem og godkend*. Artiklen ligger på forsiden med det samme.
- "Ugens spisested" kan først godkendes, når pladsholderen til redaktørens dom
  er skiftet ud med din egen tekst. Vælg samtidig antal gulvmåtter.
- Tips fra andre medier og Facebook-grupper kan ikke publiceres. De står der,
  så du kan finde en selvstændig kilde.

## Hvis noget går galt

| Symptom | Årsag |
|---|---|
| Log ind-siden har intet kodefelt | `GULVMAATTEN_REDAKTOER_KODE` er ikke sat |
| Et link siger "virker ikke" | Linket er spærret, eller det er kopieret forkert |
| Loggen siger "Ingen API-nøgle" | `GULVMAATTEN_API_KEY` er ikke sat |
| Alt er væk efter en opdatering | Disken er ikke monteret på `/data` |
| "Permission denied" i `/data` | Sæt `RAILWAY_RUN_UID=0` (Railways egen anbefaling) |

## Prøv det lokalt først

```bash
GULVMAATTEN_REDAKTOER_KODE=hemmelig python -m gulvmaatten server --port 8000 --hver 0
```

`--hver 0` slår de faste kørsler fra, så der ikke bruges API-kald, mens du
kigger. Åbn http://localhost:8000/log-ind og log ind med koden `hemmelig`.
