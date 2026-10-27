# Datamodel

Alt gemmes i én SQLite-fil, `data/gulvmaatten.db`. Modellen er defineret i
`gulvmaatten/models.py`, databasen i `gulvmaatten/db.py`.

```
Source ──< RawItem ──< Event
                 └────< Article ──< Publication
```

## Source (kilde)

En hjemmeside eller et feed vi overvåger. Kommer fra `config/sources.yaml`.

| Felt | Betydning |
|---|---|
| id | Kort unikt navn, fx `glostrup-kommune-nyheder` |
| type | `rss`, `html` eller `sitemap` |
| tillid | 1–5. Officielle kilder er 5. Bruges i research-trinnet |
| frekvens_timer | Hvor ofte kilden bør hentes |
| verificeret | Om kildeprofilen er testet mod den rigtige side |
| html | CSS-selektorer, der udpeger opslag på en HTML-side |
| sitemap | For `sitemap`-kilder: `prefix` (kun URL'er der starter sådan) og `max` |
| prioritet | 1–3. 3 = særligt fokus (Folkely, havnen, Lynæs). Sænker redaktionens tærskel med 1 |
| billeder | Om kildens billeder må vises. Andre medier: altid nej |
| aktiv | Inaktive kilder hentes ikke (fx futsal, hvor URL mangler) |
| sidst_hentet | Sættes af crawleren |

## RawItem (råt opslag)

Et opslag præcis som det blev fundet hos kilden. Ingen fortolkning.
Nøglen er `(source_id, url)`, så samme opslag ikke gemmes to gange.

`billede_url` er kildens billede (kun adressen). `data` er strukturerede
felter som JSON, fx pris, areal og mægler for en bolig fra Boligsiden.
Ingen af dem indgår i fingeraftrykket.

`content_hash` er et fingeraftryk af titel, tekst og dato. Når crawleren
ser et opslag igen, sammenlignes fingeraftrykket. Er det ændret, opdateres
opslaget og markeres som *ændret*, så redaktionen kan reagere, fx på et
aflyst arrangement.

## Event (arrangement)

Et arrangement med start, slut, sted, pris, tilmelding og arrangør, udledt
af et eller flere RawItems. `aflyst` sættes, når kilden melder aflysning.

## Article (artikel)

Et artikeludkast. Ud over overskrift, resumé og brødtekst har den:

- `kilder`: de URL'er artiklen bygger på. En artikel uden kilder må ikke publiceres.
- `usikkerheder`: hvad agenten ikke kunne bekræfte. Vises for redaktøren.
- `risiko`: `low`, `medium` eller `high`. `high` kræver altid menneskelig godkendelse.
- `status`: se ReviewStatus.
- `billede_url` og `billede_kredit`: billedet og krediteringen, der altid vises sammen.
- `tags`: bl.a. `spisested:<id>` for "Ugens spisested" og `karakter:<1-6>` for anmeldelsens gulvmåtter.

## ReviewStatus

```
new → needs_review → approved → published → retracted
                  └→ rejected
```

I første fase går alt forbi `needs_review`. Automatisk godkendelse findes ikke.

## Publication (publicering)

Det, der ligger på hjemmesiden: hvilken artikel, under hvilken adresse
(`slug`), hvornår, og en eventuel synlig rettelsesnote.
