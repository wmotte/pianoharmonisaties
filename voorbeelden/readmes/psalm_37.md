# Psalm 37 – Gerrit Koele

- **YouTube-video:** [https://www.youtube.com/watch?v=b9ReiRKeBxg](https://www.youtube.com/watch?v=b9ReiRKeBxg)
- **Titel:** Psalm 37 | Christelijke pianomuziek van Gerrit Koele
- **Uploaddatum:** 19 januari 2026

## Bestanden in deze map

- Audio: `../mp3/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].mp3`
- Ongecorrigeerde partituur: `../ongecorrigeerd/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].musicxml`
- Formele harmoniecontrole (fouten in rood, vóór herzetting): `../controle/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].musicxml`
- Gecorrigeerde partituur: `../gecorrigeerd/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].musicxml`

## Secties en maatsoorten

Psalm 37 is een klassiek voorbeeld van een stuk waarin Gerrit Koele het **voorspel in een driekwartsmaat (3/4)** speelt en vervolgens voor het **koraal en naspel overgaat naar 4/4**.

### Maatwisseling: 3/4 Voorspel → 4/4 Koraal → 4/4 Naspel

Met de automatische sectiesplitsing (`--split-sections`) worden de stiltes rond 48.6s en 106.3s gedetecteerd:

1. **Voorspel (m1–m18):** 3/4, meditatief tempo ♩ = 66, **0 afwijkende maten**.
2. **Koraal (m19–m44):** 4/4, zangtempo ♩ = 112, **0 afwijkende maten**, syncopen 2%.
3. **Naspel (m45–m59):** 4/4, tempo ♩ = 108, **0 afwijkende maten**, syncopen 8%.

De samengevoegde partituur schakelt bij maat 19 automatisch over van 3/4 naar 4/4, bevat dubbele maatstrepen op de overgangen en draagt duidelijke repetitietekens (`[Voorspel]`, `[Koraal]`, `[Naspel]`).

### Toonsoort: 2 mollen (C-dorisch)

In het koraalboek van Gerrit Koele staat Psalm 37 genoteerd met **twee mollen** (B♭, E♭). De melodie van Psalm 37 stamt uit het Geneefse Psalter en staat in modus 1 (dorisch) getransponeerd naar C: C – D – E♭ – F – G – A♮ – B♭ – C.

De instelling `"key": "2b"` in `splits.json` legt de voortekening met twee mollen vast.
Het dorische profiel behoudt de A♮. Verhoogde leidtonen en tussendominanten krijgen een
spelling die aansluit bij hun harmonische functie.

### Harmonie-analyse

Bij de formele harmonie-analyse heeft de samengevoegde partituur 53 meldingen op 348 verticalen (15.2 per 100).
- In de controlepartituur (`../controle/`) zijn al deze 53 meldingen rood gemarkeerd met de bijbehorende regelcode (`LIG`, `H8`, `OV`, `S7`, etc.).
- In stap 5 (`../gecorrigeerd/`) zijn 11 binnenstemnoten (1,4%) herzet, waardoor het aantal fouten daalt van 53 naar 43. De formele controle omvat ook meldingen over de buitenstemmen en de wijde pianoligging.

## Hypercorrectie

De [hypercorrectie](../hypercorrectie/2026-01-19%20-%20Psalm%2037%20%EF%BD%9C%20Christelijke%20pianomuziek%20van%20Gerrit%20Koele%20%5Bb9ReiRKeBxg%5D.musicxml) behoudt de melodie en herzet ook de bas.
Aangehouden binnenstemmen kunnen gericht opnieuw worden aangeslagen om de stemvoering te verbeteren.
Het [rapport](../hypercorrectie/hypercorrectie.md) vermeldt het resultaat van de volledige
regelcontrole en de vergelijking van klankvariatie en harmonische verwantschap.
