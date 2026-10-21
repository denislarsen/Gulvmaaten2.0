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
| type | `rss` eller `html` |
| tillid | 1–5. Officielle kilder er 5. Bruges i research-trinnet |
| frekvens_timer | Hvor ofte kilden bør hentes |
| verificeret | Om kildeprofilen er testet mod den rigtige side |
| html | CSS-selektorer, der udpeger opslag på en HTML-side |
| sidst_hentet | Sættes af crawleren |

## RawItem (råt opslag)

Et opslag præcis som det blev fundet hos kilden. Ingen fortolkning.
Nøglen er `(source_id, url)`, så samme opslag ikke gemmes to gange.

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

## ReviewStatus

```
new → needs_review → approved → published → retracted
                  └→ rejected
```

I første fase går alt forbi `needs_review`. Automatisk godkendelse findes ikke.

## Publication (publicering)

Det, der ligger på hjemmesiden: hvilken artikel, under hvilken adresse
(`slug`), hvornår, og en eventuel synlig rettelsesnote.
