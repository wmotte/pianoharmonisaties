# De begeleiding herzetten

[Terug naar de README](../README.md) · [Regelcodes en bronnen](harmoniecontrole.md)

Voer de commando's uit vanuit de hoofdmap, met de transcriptieomgeving in `.venv`.

## Binnenstemmen herzetten met `corrigeer_harmonie.py`

```bash
.venv/bin/python corrigeer_harmonie.py                       # alle stukken (rekentijd afhankelijk van de zetting)
.venv/bin/python corrigeer_harmonie.py --only "Psalm 85" --beam 20 --force
.venv/bin/python corrigeer_harmonie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/gecorrigeerd --force
```

`corrigeer_harmonie.py` schrijft de binnenstemmen opnieuw en houdt melodie en bas vast,
zowel in toonhoogte als ritme. Ook een aangehouden noot die later de hoogste of laagste stem wordt,
blijft vast. De verdeling over de handen, nootlengtes en rusten veranderen niet.
Het script controleert wel bij alle stemmen de spelling van nootnamen en voortekens.

Bij het kiezen van nieuwe noten weegt het script de harmonieregels af tegen het verloop van de
oorspronkelijke binnenstemmen. Het beoordeelt parallellen, stemkruisingen en de oplossing van septiemen.
Over drie opeenvolgende samenklanken kijkt het ook of een stem na een sprong stapsgewijs herstelt.
Doorgangsnoten en voorhoudingen krijgen extra bescherming. Zo verdwijnen ze niet zomaar
omdat een akkoordtoon minder regelmeldingen zou geven.

### Zoeken en uitvoer bewaren

Met `--beam` bepaal je hoeveel alternatieve zettingen het script tijdens het zoeken bewaart.
De standaard is 32. Een grotere waarde geeft meer mogelijkheden, maar kost meer rekentijd.
Bij dezelfde invoer en instellingen geeft deze methode hetzelfde resultaat.
Ze beoordeelt lokale verbindingen en muzikale voorkeuren, geen volledige frasen of expressie.

Gewijzigde noten worden groen, met de oorspronkelijke noot als toelichting.
Noten waarvoor de harmoniecontrole nog een melding geeft, worden rood.
De partituren komen in `midi_gecorrigeerd/` en de rapporten in
`harmonie_correctie.md` en `harmonie_correctie.json`. Het rapport telt per stuk de gewijzigde en
hergespelde noten en de meldingen per code vóór en na de herzetting.

Met `--input-dir` en `--output-dir` kies je andere mappen voor de partituren.
`--report-dir` bepaalt waar de rapporten komen. Verander je het algoritme of het aantal
bewaarde alternatieven (`--beam`), dan berekent het script bestaande resultaten opnieuw.
Verwerk je alleen een selectie, dan blijven de rapportregels van andere stukken bewaard.
Levert je selectie geen stukken op, dan stopt het script met een foutmelding en blijven de rapporten intact.

De vier voorbeeldpartituren in `voorbeelden/gecorrigeerd/` zijn met deze methode berekend.
Het bijbehorende rapport is [voorbeelden/harmonie_correctie.md](../voorbeelden/harmonie_correctie.md).
Ook na correctie kunnen er meldingen zijn, zowel in de gewijzigde binnenstemmen als in de vaste buitenstemmen.
Het totaal kan zelfs gelijk blijven of licht stijgen: de zoektocht weegt de regels af tegen het behoud van
de oorspronkelijke binnenstemmen, en zachte waarschuwingen kunnen daarbij toenemen.
Minder meldingen betekent op zichzelf nog niet dat de muziek beter klinkt.

## Hypercorrectie: vaste melodie, vrije bas en binnenstemmen

`hypercorrectie.py` mag naast de binnenstemmen ook de bas aanpassen.
Het zoekt naar een zetting zonder meldingen van de volledige standaardcontrole uit `harmonie_regels.py`.
De melodie blijft vast, inclusief nootnamen, voortekens, duur en bindingen.

Als melodie geldt steeds de hoogste klinkende noot van de rechterhand.
Het script bepaalt dat ook opnieuw als een hogere noot eindigt en een lagere noot blijft doorklinken.
Een linkerhandnoot die boven de melodie uitkomt, blijft onderdeel van de bewerkbare begeleiding.

```bash
.venv/bin/python hypercorrectie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/hypercorrectie --seconds 300
.venv/bin/python hypercorrectie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/hypercorrectie --only "Psalm 85" --resume --seconds 300
```

### Wat het script kan veranderen

Het script probeert andere basnoten, omkeringen en akkoordliggingen.
Het kan meerdere noten tegelijk wijzigen en gebruikt de bestaande harmoniecontrole om elke oplossing te toetsen.
Is de afstand tot de melodie te groot, dan mag het een aangehouden binnenstem opnieuw laten aanslaan.
Het behoudt hoeveel stemmen er tegelijk klinken en de totale tijd waarin elke hand klinkt.
Het schrapt dus geen stemmen of passages om de controle te laten slagen.

Bij het zoeken geeft het programma de voorkeur aan behoud van de oorspronkelijke toonklassen,
akkoorden, basbeweging en akkoordwisselingen. Het voegt geen willekeurige versieringen toe.
Opnieuw aanslaan mag alleen bij aangehouden binnenstemmen met een liggingsprobleem.
Met `--seed` stuur je het verkennen van alternatieven als plaatselijke wijzigingen geen oplossing meer geven.

### Verdeling over de notenbalken

Gewijzigde begeleidingsnoten zijn groen. Vanaf C4 worden die op de bovenste balk gezet,
zodat ze minder hulplijnen nodig hebben. Ze blijven tot hun eigen begeleidingsstem behoren,
met dezelfde toonhoogte en duur. De harmoniecontrole gebruikt die stemindeling, ook als een noot
op een andere balk wordt weergegeven.

Bij de export krijgen linker- en rechterhand verschillende stemnummers.
Zo voegt MuseScore een verplaatste noot niet samen met een andere stem.
Bevat een akkoord zowel lage als hoge noten, dan krijgen de verplaatste hoge noten een aparte
notatiestem op hetzelfde tijdstip. De lage bas blijft op de onderste balk.

### Wanneer de uitvoer volledig is

Het script schrijft de MusicXML eerst naar een tijdelijk bestand en leest dat opnieuw in voor controle.
Pas daarna vervangt het de bestaande uitvoer. Bron en uitvoer moeten verschillende bestanden zijn,
ook als je de Python-functie rechtstreeks aanroept.

De status `volledig` betekent dat er geen formele meldingen over zijn en dat ook de controles
op melodie, klinkende duur en variatie zijn geslaagd. Is er te weinig rekentijd of zoekruimte,
of zijn de eisen niet te verenigen, dan wordt de status `onvolledig` en stopt het script met exitcode 2.
De melodie blijft ook dan vast. De optionele controle op zangomvang (`OMV`) hoort niet bij deze
standaardcontrole van pianozettingen.

### Zoektijd en hervatten

| Optie | Standaard | Betekenis |
|---|---:|---|
| `--seconds` | 300 | Zoektijd in seconden per stuk. Inlezen en exporteren tellen niet mee. |
| `--rounds` | 100 | Maximaal aantal zoekrondes. |
| `--radius` | 36 | Maximale afwijking in halve tonen ten opzichte van elke bewerkbare brontoon. |
| `--seed` | 0 | Startwaarde voor het verkennen van alternatieven. |
| `--resume` | uit | Ga verder met opgeslagen toonkeuzes bij dezelfde bron en voorbereiding. |

Een grotere `--radius` maakt meer akkoordliggingen mogelijk.
De muzikale beoordeling geeft wel de voorkeur aan kleinere wijzigingen.
Met `--resume` kun je een eerdere zoektocht voortzetten.
Het script vergelijkt daarvoor de opgeslagen bestandskenmerken van de bron en de voorbereiding
en weigert wijzigingen buiten de gekozen zoekruimte.
Door de tijdslimiet kan een snellere machine een andere oplossing bereiken dan een langzamere.

### Eigen muzikale voorkeuren

In `hypercorrectie_voorkeuren.json` kun je gerichte muzikale keuzes vastleggen.
Het script leest dat bestand standaard. Met `--preferences` kun je een ander bestand kiezen.
Elke keuze verwijst naar een maat, tel, hand en oorspronkelijke toon.
De melodie blijft vast en alle formele en muzikale controles blijven gelden.

Voor Psalm 85 bewaart maat 46 bijvoorbeeld een aangehouden G als orgelpunt,
met daarboven de tegenlijn D3–D4–E4–D4. De voorafgaande basnoot A2 verbindt deze ligging
zonder parallelle octaven.

De vier uitgewerkte versies staan in [`voorbeelden/hypercorrectie/`](../voorbeelden/hypercorrectie/).
Het [hypercorrectierapport](../voorbeelden/hypercorrectie/hypercorrectie.md) geeft de aantallen
regelmeldingen en metingen van rijkheid en variatie. Die metingen zeggen niet of elke muzikale
keuze overtuigt. Beoordeel de partituren daarom ook op gehoor.
