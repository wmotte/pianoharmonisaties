# Adversariële review van de harmoniecorrectie

De review betreft de bundelzoektocht, stembehoud, rapportage en MusicXML-uitvoer van
`corrigeer_harmonie.py`. Drie fouten zijn met falende regressietests gereproduceerd en hersteld.

| Ernst | Bevinding | Herstel en verificatie |
|---|---|---|
| Hoog | Een aangehouden binnennoot kreeg alleen bij de inzet een bovengrens. Bij een later dalende melodie kon deze noot de nieuwe hoogste toon worden, ondanks behoud van de oorspronkelijke melodienoot. | Kandidaten worden begrensd door de buitenstemmen gedurende de gehele klinkende duur. Een test lokt expliciet een overschrijding uit. |
| Middel | De overgangsfunctie ontving alleen de inzet-ID's van bewerkbare binnenstemmen. Nieuw aangeslagen buitenstemmen telden daardoor als liggende noten en konden onterechte kruisingskosten veroorzaken. | Alle nieuwe inzetten worden doorgegeven, onafhankelijk van hun bewerkbaarheid. Een regressietest controleert dit bij iedere beoordeelde overgang. |
| Hoog | Zonder invoerbestanden werd het Markdown-rapport leeggeschreven. Bij een gedeeltelijke bronverzameling verdwenen bovendien andere stukken uit het verzamelde rapport. | Een lege selectie stopt vóór het schrijven. Bestaande rapportregels buiten de selectie blijven behouden. De lege-invoertest controleert foutcode en behoud van het rapport. |

Daarnaast zijn afzonderlijke invoer-, uitvoer- en rapportmappen toegevoegd voor reproduceerbare
voorbeeldberekeningen. Dezelfde bron- en uitvoermap wordt geweigerd. Een lege partituur veroorzaakt
geen deling door nul in de voortgangsweergave. Kandidaatcombinaties worden niet meer vooraf als
volledige lijst opgeslagen.

## Resterende beperkingen

- **Rekentijd en geheugen bij dichte akkoorden:** `revoice` doorloopt nog steeds het cartesische
  product van de kandidaten per nieuwe binnennoot. Acht kandidaten voor acht binnenstemnoten
  geven maximaal 16.777.216 combinaties per toestand. Ook `new_states` kan vóór het terugbrengen
  naar de bundelbreedte sterk groeien. De vier voorbeelden vormen geen stresstest voor deze situatie.
- **Geen optimaliteitsgarantie:** de bundelzoektocht kan betere paden vroeg afsnijden. De
  kostenfunctie en de onafhankelijke regelcontrole gebruiken bovendien verschillende
  stemkoppelingen bij uitgebreide akkoorden. Minder zoekkosten betekent daarom niet noodzakelijk
  minder regelmeldingen.
- **Muzikale beoordeling:** contour en sprongherstel zijn lokale voorkeuren. De tests beoordelen
  geen frasering, interpretatie of overtuigingskracht van de muziek.

## Validatie

Negen tests slagen, waaronder het opnieuw inlezen van alle vier overschreven MusicXML-bestanden.
De exporttest controleert behoud van handverdeling en noottijden, de laagste en hoogste toon
per inzetmoment en de overeenkomst tussen de onafhankelijke controle en het JSON-rapport.

| Voorbeeld | Gewijzigde noten | Meldingen in de bron | Meldingen na correctie |
|---|---:|---:|---:|
| De Lofzang van Maria | 32 | 185 | 99 |
| Psalm 37 | 11 | 53 | 43 |
| U zij de glorie | 42 | 192 | 129 |
| Psalm 85 | 3 | 33 | 33 |

De overige stukken in het verzamelrapport zijn niet opnieuw berekend. Hun bronpartituren
staan niet in deze werkomgeving.

Uitvoeren:

```bash
python -m unittest discover -s tests -v
python corrigeer_harmonie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/gecorrigeerd --force
```
