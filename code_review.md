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

## Hypercorrectie

De aanvullende review controleert dat de zoektocht dezelfde regelcontrole gebruikt als de
exportvalidatie, inclusief spelling en liggende noten. Het nieuwe `include_ids`-argument voegt
alleen nootidentificaties toe en wijzigt de bestaande meldingen niet.

Gerichte tests behandelen een linkerhand boven de melodie, een aangehouden melodienoot,
een onoplosbare verdubbelde leidtoon in vaste melodienoten, proefwijzigingen zonder blijvende
mutaties, herarticulatie zonder gaten, enharmonische octaafgrenzen en behoud van toonklasdichtheid.
Ook de gecoördineerde herzetting rond een liggende basnoot moet haar proefwijzigingen volledig
terugdraaien voordat een voorstel wordt geaccepteerd.

De exporttest leest alle vier hypercorrecties opnieuw in, vereist nul meldingen en vergelijkt
iedere oorspronkelijke melodienoot op toonhoogte, spelling, inzet en einde. De bronpartituren
en gewone correcties worden niet door hypercorrectie overschreven. Hervatten vereist dezelfde
bron en dezelfde voorbereide notenstructuur.

De zoektocht is begrensd en heuristisch. Een onvolledig resultaat blijft herkenbaar als
`onvolledig`, ook wanneer alleen een behoudscriterium faalt. De acceptatiecriteria beoordelen
meetbare kenmerken van rijkheid en variatie. Een luisterbeoordeling blijft afzonderlijk nodig.

## Adversariële hercontrole van hypercorrectie

Zes falende regressietests reproduceerden de volgende fouten. De reparaties laten de
standaardregels van de formele harmoniecontrole ongewijzigd.

| Ernst | Bevinding | Herstel |
|---|---|---|
| Hoog | De melodiebescherming keek alleen naar inzetten. Een aangehouden binnennoot die na het einde van een hogere noot de melodie werd, bleef bewerkbaar. | Bescherming en bovengrenzen gebruiken nu alle inzet- en eindmomenten. |
| Hoog | De exportcontrole accepteerde een ongewijzigde melodienoot, ook wanneer een gewijzigde binnenstem erboven uitkwam. | De hoogste rechterhandtoon wordt gedurende elk klankinterval afzonderlijk vergeleken. |
| Middel | Verlies van toonklasdichtheid tussen twee inzetten kon onopgemerkt blijven. | Zoekfunctie en exportcontrole toetsen dit ook bij het eindigen van noten. |
| Hoog | Het bestaande uitvoerbestand werd al overschreven vóór het opnieuw inlezen. Een exportfout liet daardoor beschadigde uitvoer achter. | Export en validatie vinden plaats in een tijdelijke map. Een gesimuleerde parsefout laat de bestaande partituur intact. |
| Hoog | De directe Python-functie kon de bron als uitvoer accepteren, hoewel de CLI dat weigerde. | Ook de functie weigert dezelfde bron en uitvoer, inclusief aliassen naar hetzelfde bestand. |

### Hoge begeleidingsnoten op de bovenste balk

De balkwissel gebruikt het MusicXML-element `staff` en behoudt stemidentiteit, toonhoogte, duur,
akkoordverband en bindingen. Dat volgt de standaardnotatie voor akkoorden over twee balken.
Zie het [MusicXML-voorbeeld voor staff](https://www.w3.org/2021/06/musicxml40/musicxml-reference/examples/staff-element/).
Een octaaflijn verandert de weergave ten opzichte van de opgeslagen toonhoogte en vraagt hier
geen transpositie van de nootdata. Zie de [definitie van octave-shift](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/octave-shift/).

De nootidentificatie `hc-cross-left-…` bewaart de oorspronkelijke linkerhandindeling. De lezer
zet uitsluitend deze balkkeuze voor de analyse terug, zonder toonhoogtes of tijden te veranderen.
Dit voorkomt dat een visuele balkwissel wordt aangezien voor een andere muzikale stemverdeling.
Tests controleren de werkelijk opgeslagen balknummers, het akkoordverband, bindingen en de
ongewijzigde klankgegevens.

Alle vier voorbeelden zijn opnieuw gecontroleerd met de aangescherpte melodie- en dichtheidscriteria.
Ze hebben nul formele meldingen. In totaal staan 99 verplaatste nootkoppen op de bovenste balk.
De weergegeven partituur van Psalm 85 is ook visueel gecontroleerd in een MuseScore-rendering.

Een aanvullende MuseScore-test toonde dat oorspronkelijke stemnummers op beide balken konden
botsen na de balkwissel. Daardoor kon MuseScore noten samenvoegen of verkeerd plaatsen in de tijd.
De export geeft de linkerhand nu een eigen, per maat consistente reeks stemnummers. Hoge en
lage noten uit hetzelfde akkoord worden op hetzelfde tijdstip over aparte notatiestemmen verdeeld,
zodat MuseScore niet de hele lage bas mee naar boven verplaatst. Een
MusicXML-metadataveld bewaart de oorspronkelijke nummers voor de analyse. Een regressietest
controleert expliciet dat gelijke bronnummers niet op beide balken in dezelfde stem terechtkomen.

De 37 automatische tests slagen. Voor alle vier voorbeelden zijn daarnaast twee MIDI-bestanden
met MuseScore gemaakt: met dezelfde gecorrigeerde stemnummering vóór en na de balkwissel.
De multiverzamelingen van toonhoogte, begintijd, eindtijd en aanslagsterkte zijn identiek.
MuseScore beëindigde sommige exportprocessen met code -6 na het schrijven van de bestanden.
De geproduceerde MIDI-bestanden zijn ingelezen en gecontroleerd, de afsluitcode is dus geen
bewijs van een stabiele MuseScore-installatie.

De gerichte aanpassing van Psalm 85, maat 46, is reproduceerbaar vastgelegd in
`hypercorrectie_voorkeuren.json`. Een exporttest vereist het G-orgelpunt en de lijn D3–D4–E4–D4,
naast behoud van de melodie en nul formele meldingen. Voorkeuren mogen geen melodienoten wijzigen.
