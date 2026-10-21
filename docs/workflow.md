# Den redaktionelle pipeline

Hvert trin kan køres for sig, og alt går gennem databasen, så man altid kan
se, hvor en sag står.

| Trin | Hvad sker der | Status |
|---|---|---|
| 1. Overvågning | Crawleren henter kilderne efter deres frekvens | Bygget |
| 2. Registrering | Nye og ændrede opslag gemmes som RawItems | Bygget |
| 3. Filtrering | Agent vurderer lokal nyhedsværdi og frasorterer støj | Næste |
| 4. Research | Agent sammenholder kilder og tjekker dato, sted, pris m.m. | Næste |
| 5. Udkast | Agent skriver kort artikel med kildeangivelse | Næste |
| 6. Kvalitetssikring | Automatisk tjek for manglende kilder, dubletter, persondata, risiko | Senere |
| 7. Review | Redaktør godkender eller afviser | Senere |
| 8. Publicering | Godkendte artikler lægges på hjemmesiden | Senere |
| 9. Opfølgning | Ændrede RawItems udløser opdatering af artikel/arrangement | Senere |

## Regler agenten skal overholde

Disse skrives ind i agentens instruktioner, når trin 3–5 bygges.

1. **Ingen opdigtede fakta.** Alle tal, navne, datoer, steder og citater skal
   kunne findes i et RawItem, agenten har fået. Kan noget ikke bekræftes,
   skrives det i `usikkerheder`, ikke i artiklen.
2. **Kilde på alt.** Hver artikel har mindst én URL i `kilder`.
3. **Korrekt før hurtigt.** Modstridende oplysninger giver ikke en artikel,
   men en note til redaktøren.
4. **Høj risiko kræver menneske.** Politik, kriminalitet, sundhed, navngivne
   privatpersoner og kontroversielle sager får `risiko = high`.
5. **Ingen private persondata.** Kun navne, der optræder i en offentlig
   kilde med redaktionel relevans (fx en borgmester eller en foredragsholder).
6. **Rettelser er synlige.** Fejl rettes med en rettelsesnote på artiklen.

## Agentens arbejdsgang (trin 3–5, planlagt)

For hvert nyt eller ændret RawItem:

1. **Vurdér** – Er det relevant for borgere i Glostrup eller Brøndby? Giv en
   score 0–10 og en kategori. Under en tærskel: arkivér uden videre.
2. **Research** – Find andre RawItems om samme sag (samme dato, sted eller
   titel). Sammenhold oplysningerne. Udpeg hvad der er bekræftet, og hvad
   der kun står ét sted.
3. **Skriv** – Lav overskrift, 1–2 sætningers resumé, 3–6 sætningers
   brødtekst, praktiske detaljer (hvornår, hvor, pris, tilmelding) og kilder.
4. **Tjek** – Marker risiko. Find dubletter blandt eksisterende artikler.
5. **Aflever** – Gem som Article med status `needs_review`.
