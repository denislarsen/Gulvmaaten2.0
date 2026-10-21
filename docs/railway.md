# Gulvmåtten på Railway

Hjemmesiden, redaktionsværktøjet og robotten kører som ét program:

```bash
python -m gulvmaatten serve
```

Det starter hjemmesiden og en robot, der hver time henter kilderne og skriver
nye artikler. Databasen er én fil, `gulvmaatten.db`.

## Første gang

1. Gå til [railway.com](https://railway.com) og log ind med din GitHub-konto.
2. Vælg **New Project** → **Deploy from GitHub repo** → `Gulvmaaten2.0`.
   Railway læser `railway.json` og ved derfor selv, hvordan programmet startes.
3. Giv programmet en fast disk, så databasen ikke forsvinder ved genstart:
   højreklik på tjenesten → **Attach volume** → mount path `/data`.
4. Under **Variables** tilføjer du:

   | Navn | Værdi |
   |---|---|
   | `GULVMAATTEN_DB` | `/data/gulvmaatten.db` |
   | `GULVMAATTEN_API_KEY` | Din API-nøgle fra Anthropic |
   | `GULVMAATTEN_ADMIN_PASSWORD` | Et langt kodeord til redaktionen |
   | `GULVMAATTEN_SECRET_KEY` | En lang tilfældig tekst (holder dig logget ind) |

5. Under **Settings** → **Networking** trykker du **Generate Domain**. Så får
   siden en midlertidig adresse, fx `gulvmaatten-production.up.railway.app`.
6. Redaktionen ligger på adressen efterfulgt af `/redaktion`.

Railway henter automatisk den nye version, hver gang en ændring bliver flettet
ind i `main` på GitHub.

## Valgfrie indstillinger

| Navn | Standard | Betydning |
|---|---|---|
| `GULVMAATTEN_ROBOT_INTERVAL` | `60` | Minutter mellem robottens runder |
| `GULVMAATTEN_ROBOT_LIMIT` | `10` | Højst så mange opslag vurderes pr. runde. Hvert koster et API-kald |

Opslag, der er dateret mere end 14 dage tilbage, springes over uden at koste
noget.

## Eget domæne

1. Køb domænet hos en domæneforhandler, fx Simply.com, One.com eller punktum dk.
2. I Railway: **Settings** → **Networking** → **Custom Domain**, og skriv
   domænet, fx `gulvmaatten.dk`.
3. Railway viser en DNS-indstilling (typisk en CNAME-post). Indsæt den hos
   domæneforhandleren under DNS.
4. Efter et stykke tid, som regel under en time, virker siden på domænet med
   sikker forbindelse (https).

## Sikkerhedskopi

Under **Sikkerhedskopi** i redaktionen kan du hente hele databasen som én fil.
Gem den et sikkert sted jævnligt.

## Flytte til en anden udbyder

Programmet bruger ikke noget, der kun findes hos Railway. For at flytte:

1. Hent en sikkerhedskopi af databasen i redaktionen.
2. Opret programmet hos den nye udbyder fra samme GitHub-projekt. Startkommandoen
   er `python -m gulvmaatten serve`, og programmet lytter på porten i `PORT`.
3. Læg databasefilen på udbyderens faste disk, og sæt de samme variabler som
   ovenfor, med `GULVMAATTEN_DB` pegende på filen.
4. Ret domænets DNS hos domæneforhandleren, så det peger på den nye udbyder.
