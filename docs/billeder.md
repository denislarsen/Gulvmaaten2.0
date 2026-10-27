# Billeder og rettigheder

Billeder på Gulvmåtten kommer i første omgang fra de kilder, vi overvåger.
Det er en midlertidig løsning. Et billede på en hjemmeside er beskyttet af
ophavsret, også når det er frit tilgængeligt.

## Sådan gør systemet nu

- Crawleren gemmer billedets adresse (`billede_url`), ikke selve billedet.
  Hjemmesiden linker direkte til kildens billede.
- Hver kilde har `billeder: ja` eller `billeder: nej` i `config/sources.yaml`.
  Ved `nej` gemmes intet billede overhovedet.
- Andre medier (Frederiksborg Amts Avis, Halsnæs Avis) har altid `billeder: nej`.
  En test sørger for, at det ikke ændres ved en fejl.
- Alle billeder vises med kreditering: "Foto: <kildens navn>". For boliger er
  det mæglerens navn.
- Stockfotos fra Colourbox (kendes på filnavnet) frasorteres, fordi kommunens
  licens ikke dækker os.
- Billeder til "Ugens spisested" kommer fra stedets egen hjemmeside. Udkastet
  får en note til redaktøren om at spørge om lov eller selv tage et billede.

## Risikovurdering pr. kilde

| Kilde | Vurdering |
|---|---|
| Halsnæs Kommune | Lav. Pressebilleder til omtale. Nogle er stockfotos (Colourbox), som kommunen har licens til, men vi har ikke. |
| Hundested Havn, Lynæs Surfcenter, sejlklubben, Folkely | Lav til middel. Arrangører vil som regel gerne omtales med deres egne billeder. Bed om en skriftlig tilladelse. |
| Folkelys pressefeed | Middel. Billederne er ofte miniaturer af andre mediers artikler. |
| Boligsiden / mæglere | Middel. Mæglerens billede vises sammen med link til salgsopstillingen. |
| Andre aviser | Høj. Bruges aldrig. |

## Næste skridt

1. Send en kort mail til de faste kilder (havnen, surfcentret, Folkely,
   sejlklubben) og bed om lov til at bruge deres billeder med kreditering.
   Notér svaret i `regler` i kildeprofilen.
2. Kopiér billeder til vores egen server, når der er tilladelse, så de ikke
   forsvinder, når kilden skifter dem ud.
3. Egne billeder: en lokal fotograf eller læserbilleder med tydelig
   tilladelse.
4. Andre stockbureauer end Colourbox skal måske også frasorteres. Hold øje
   med filnavnene.
