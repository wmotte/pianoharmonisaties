# Psalmharmonisatie: 3-5-8, sextakkoorden en speelbaarheid

[Harmoniecontrole](harmoniecontrole.md) beschrijft wat het programma daadwerkelijk toetst.
Deze aanwijzingen helpen bij het beoordelen van een bron en het kiezen van een stijl.
De onderstaande profielen zijn werkwijzen, geen reeds geïmplementeerde softwareopties.

## Eerst de stijl vaststellen

| Werkwijze | Harmonie | Wat vraagt afzonderlijke beoordeling? |
|---|---|---|
| Strikte 3-5-8-oefening | Drieklanken in grondligging als afgesproken uitgangspunt | Volledige methode, stemvoering en melodische versieringen |
| Modale koraalzetting | Drieklanken en eerste omkeringen, met de modus als uitgangspunt | Lokale verhogingen, slotwendingen en het gebruik van septiemen in de gekozen bron |
| Tonale of gekleurde pianobegeleiding | Ook septiemen, voorhoudingen, toevoegingen en tussendominanten | Oplossing van dissonanten, zelfstandige stemmen en speelbaarheid |

Een verbod op sextakkoorden of dominantseptiemen hoort bij een afgebakende oefening of stijlkeuze.
Het is geen algemene eis voor een psalm. Een stijlkenmerk van een selectie uit een koraalboek bewijst
evenmin dat het hele boek dezelfde beperking volgt. Een voortekening bepaalt de toonvoorraad, maar
niet zonder meer de modus of de plaats van de leidtoon.

## Wat 3, 5, 8 en 6 betekenen

Bij de becijfering van een melodie beschrijft 3, 5 of 8 de relatie tot de bas, met eventuele
octaafvergrotingen. In grondligging staat daarmee de terts, kwint of grondtoon van het akkoord in
de melodie. Het cijfer somt niet de tonen op die alle tegelijk boven de bas moeten staan.

| Akkoord | Bas | Melodie | Melodie-bas-interval | Omkering |
|---|---|---|---|---|
| D | D | F♯ | 3 | Grondligging |
| Bm/D | D | F♯ | 3 | Eerste omkering |
| C/E | E | C | 6 | Eerste omkering |

Een terts tussen melodie en bas kan dus zowel bij grondligging als bij een omkering horen.
De informele termen *harde 3* en *zachte 3* kunnen dit in de les verduidelijken, maar vervangen
de volledige akkoordnaam niet. Het akkoord en zijn bas bepalen de omkering.

De `6` van een sextakkoord hoort bij de basbecijfering van een eerste omkering. Hij zegt niet
welke akkoordtoon de melodie heeft. Ook een toegevoegd sextakkoord, zoals C6 = C–E–G–A,
is iets anders dan een eerste omkering, zoals C/E = E–G–C.

## Parallelle sexten en reeksen sextakkoorden

Parallelle tertsen of sexten zijn intervallen tussen twee bewegende stemmen. Zij vormen op zichzelf
geen verboden kwint- of octaafparallel. Een eventuele beperking van de lengte van zo'n reeks is
stijlgebonden. Pas haar niet toe als algemeen verbod op vierstemmige sextakkoorden.

Bij een reeks eerste omkeringen komt de moeilijkheid vaak uit de vierde stem en de verdubbeling.
Controleer alle zes stemmenparen in een SATB-zetting, inclusief de binnenstemmen, en volg dezelfde
stemmen bij unisono's. Verander de verdubbeling waar nodig en gebruik tegenbeweging. Een reeks met
twee of meer eerste omkeringen is geen fout zonder een concreet stemvoeringsprobleem.

Fauxbourdon is een bepaalde driestemmige zetwijze met veel 6/3-samenklanken. De bovenstemmen
vormen daarbij doorgaans parallelle kwarten boven een bas. Niet iedere driestemmige reeks
sextakkoorden is daarmee historisch fauxbourdon. Een vierde stem toevoegen vraagt nieuwe controle.

## Notatie, stemmen en handen

Een stem naar een andere balk verplaatsen kan de muziek volledig behouden. Een octaaf verplaatsen,
een toon vervangen of een andere verdubbeling kiezen verandert de stemvoering. Controleer zo'n
versie opnieuw. Een slot met vijf klinkende tonen is evenmin automatisch een vijfstemmige compositie:
bepaal welke tonen zelfstandige stemmen en welke verdubbelingen zijn.

Bij twee expliciete stemmen per balk kan `Score(path, voice_identity=True)` de genoteerde
stemidentiteit volgen. De gewone controle sorteert op toonhoogte en kan zelfstandige stemmen bij
een unisono samenvoegen. Drie stemmen rechts of een cantus firmus in alt of tenor vragen daarom
extra aandacht. Ook de veronderstelling dat de twee laagste linkerhandnoten één bas met een
octaafverdubbeling zijn, is zonder stemidentiteit niet waterdicht.

Voor een leerling is links alleen de bas en rechts de overige stemmen een zinvol uitgangspunt.
Toets tegelijk de maximale handspanne, opeenvolgende verplaatsingen en overbindingen. Een kleine
greep kan door grote verplaatsingen toch onprettig spelen. Bij bronbeoordeling rapporteer je dit
naast de harmonie. Bij reductie blijft de oorspronkelijke bas behouden, ook in eerste omkering.

## Bronnen en hun reikwijdte

- Bert Matter en Peter Molenaar, *In goede harmonie. Werkboek voor het maken en spelen van
  koraalzettingen*, oorspronkelijk 1985, uitgave Boeijenga 2009, BE1071, ISBN 90-71317-01-3.
  In de [uitgeverspreview](https://www.boeijengamusic.com/wp-content/uploads/2023/11/BE1071-Preview.pdf),
  gedrukte pp. 5 en 7–8, staan de keuze om zonder sextakkoorden te werken, de melodiebecijfering en
  de beginverdeling met drie stemmen rechts en bas links. Matters historische duiding is zijn
  uitgangspunt, geen hier zelfstandig bewezen uitspraak over alle zettingen van Goudimel.
- Historische koor- en koraalboeken zijn primaire muziekbronnen. Noteer editie, harmonisator,
  psalm, pagina en eventuele transpositie. De koorbundel van 1938 en het koraalboek dat volgens
  zijn voorwoord tien jaar later verscheen, zijn verschillende uitgaven.
- Aldwell & Schachter, *Harmony and Voice Leading*, unit 6, en Martijn Hooning, *Harmonieleer*,
  hoofdstukken 3 en 6, behandelen stemvoering en eerste omkeringen. Zie de afzonderlijke
  verwijzingen en uitzonderingen in [Harmoniecontrole](harmoniecontrole.md).
- Jeppesen, *Counterpoint*, behandelt een afgebakende zestiende-eeuwse vocale stijl. Maak van
  zijn melodische en stilistische regels geen algemene voorschriften voor moderne piano.

## Scans naar MuseScore

Gebruik een bestaand MuseScore- of MusicXML-bestand waar dat beschikbaar is. Een scan-PDF bevat
afbeeldingen en vereist muziekherkenning of handmatige invoer. Een digitaal gemaakte PDF met
herkenbare muziekletters bevat nog geen volledige notatiegegevens over stemmen, tijd en overbindingen.

Een bruikbare route is scan → Audiveris → MusicXML → MuseScore. Audiveris documenteert de
[MusicXML-export](https://audiveris.github.io/audiveris/_pages/tutorials/quick/export/) en de
[opdrachtregel](https://audiveris.github.io/audiveris/_pages/guides/advanced/cli/).
Bewaar ook het `.omr`-bestand voor correcties. Controleer de eerste proef op noten, sleutels,
voortekens, maatduur, stemverdeling en overbindingen voordat een hele bundel wordt verwerkt.

Vergelijk kleur, grijswaarden en zwart-wit op dezelfde pagina met dezelfde instellingen. Leesbaarheid
voor een mens bewijst geen correcte herkenning. Zwart-wit kan details verliezen die de herkenner
nodig heeft, zoals zwakke sleutels en de aansluiting van bogen of nootstokken. Een geslaagde import
in MuseScore bewijst evenmin dat de bron correct is omgezet.
