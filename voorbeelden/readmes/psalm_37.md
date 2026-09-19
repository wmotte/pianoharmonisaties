# Psalm 37 – Gerrit Koele

- **YouTube-video:** [https://www.youtube.com/watch?v=b9ReiRKeBxg](https://www.youtube.com/watch?v=b9ReiRKeBxg)
- **Titel:** Psalm 37 | Christelijke pianomuziek van Gerrit Koele
- **Uploaddatum:** 19 januari 2026

## Bestanden in deze map

- Audio: `../mp3/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].mp3`
- Ongecorrigeerde partituur: `../ongecorrigeerd/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].musicxml`
- Formele harmoniecontrole (fouten in rood, vóór herzetting): `../controle/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].musicxml`
- Gecorrigeerde partituur: `../gecorrigeerd/2026-01-19 - Psalm 37 ｜ Christelijke pianomuziek van Gerrit Koele [b9ReiRKeBxg].musicxml`

## Toelichting & Sectiesplitsing (v3)

Psalm 37 is een klassiek voorbeeld van een stuk waarin Gerrit Koele het **voorspel in een driekwartsmaat (3/4)** speelt en vervolgens voor het **koraal en naspel overgaat naar 4/4**.

### Maatwisseling: 3/4 Voorspel → 4/4 Koraal → 4/4 Naspel

In de eerdere transcriptie zonder sectiesplitsing werd het hele stuk geforceerd in 4/4 met een gemiddeld tempo van 108 bpm. Hierdoor werd het meditatieve 3/4-voorspel in een 4/4-keurslijf gewrongen, wat leidde tot afwijkende maten en onrustige notatie.

Met de automatische sectiesplitsing (`--split-sections`) worden de stiltes rond 48.6s en 106.3s feilloos gedetecteerd:
1. **Voorspel (m1–m18):** 3/4, meditatief tempo ♩ = 66, **0 afwijkende maten**.
2. **Koraal (m19–m44):** 4/4, zangtempo ♩ = 112, **0 afwijkende maten**, syncopen slechts 2%.
3. **Naspel (m45–m59):** 4/4, tempo ♩ = 108, **0 afwijkende maten**, syncopen 8%.

De samengevoegde partituur schakelt bij maat 19 automatisch over van 3/4 naar 4/4, bevat dubbele maatstrepen op de overgangen en draagt duidelijke repetitietekens (`[Voorspel]`, `[Koraal]`, `[Naspel]`).

### Toonsoort: 2 mollen (C-dorisch / gouden standaard Gerrit Koele)

In het koraalboek van Gerrit Koele staat Psalm 37 genoteerd met **twee mollen** (B♭, E♭). De melodie van Psalm 37 stamt uit het Geneefse Psalter en staat in modus 1 (dorisch) getransponeerd naar C: C – D – E♭ – F – G – A♮ – B♭ – C.

De eerdere automatische sleutelschatting koos 3 mollen (C-mineur / Es-majeur), waardoor elke A♮ in de melodie en harmonie een herstellingsteken nodig had. Door de toonsoort expliciet op 2 mollen (`"key": "2b"` in `splits.json`) te zetten en de transcriptiepijplijn uit te breiden met dorische profielen en leidtoon-/tussendominantspelling (A♮, F♯, B♮ als kruis of hersteld), volgt de partituur exact Koele's notatie met 2 mollen. Dit levert een aanzienlijk rustiger en natuurlijker notenbeeld op zonder overbodige herstellingstekens.

### Harmonie-analyse

Bij de formele harmonie-analyse heeft de samengevoegde partituur 53 meldingen op 348 verticalen (15.2 per 100).
- In de controlepartituur (`../controle/`) zijn al deze 53 meldingen rood gemarkeerd met de bijbehorende regelcode (`LIG`, `H8`, `OV`, `S7`, etc.).
- In stap 5 (`../gecorrigeerd/`) zijn 13 binnenstemnoten (1.6%) herzet, waardoor het aantal fouten daalt van 53 naar 37 (-30%). De resterende meldingen bestaan uitsluitend uit stemvoering tussen de ongewijzigde melodie- en baslijn en wijde ligging (`LIG`) inherent aan de pianozetting.
