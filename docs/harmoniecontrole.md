# Harmonie controleren

[Terug naar de README](../README.md) · [Begeleiding herzetten](herzetten.md)

Voer de commando's uit vanuit de hoofdmap, met de transcriptieomgeving in `.venv`.

## Gebruik

```bash
.venv/bin/python controleer_harmonie.py                      # alle stukken (~1 min); overslaan als uitvoer nieuwer is
.venv/bin/python controleer_harmonie.py --only "Psalm 85" --force
.venv/bin/python controleer_harmonie.py --omvang             # ook de zangomvang van S/A/T/B toetsen (OMV)
```

`controleer_harmonie.py` toetst de partituren in `midi/` aan de regels van de klassieke
vierstemmige koraalzetting. Het schrijft per stuk een gemarkeerde partituur en een tekstbestand.
In `midi_controle/<stem>.musicxml` staan de betreffende noten rood, met de regelcode eronder.
Open dit bestand in MuseScore om de meldingen te bekijken.

`midi_controle/<stem>.txt` geeft elke melding met maat, tel, code en betrokken noten, bijvoorbeeld:

```text
maat 12 tel 3 | P5 | T G3 | met S: D4-A4 -> E4-B4
```

Het verzamelrapport `harmonie_controle.md` telt de meldingen per code en per stuk.
Het vermeldt ook het aantal meldingen per honderd samenklanken.

## Hoe het programma de stemmen volgt

Bij elke nieuwe aanslag bekijkt het programma alle noten die op dat moment klinken,
inclusief aangehouden noten. Zo'n moment heet in de rapporten een *verticaal*.
Noten onder een 8va-lijn worden op hun klinkende hoogte beoordeeld.

Het programma deelt de noten van laag naar hoog in als bas (B), tenor (T), alt (A) en sopraan (S).
Zijn er meer dan vier noten, dan behandelt het de extra noten als verdubbelingen van de dichtstbijzijnde stem.
Tussen twee opeenvolgende samenklanken koppelt het sopraan aan sopraan en bas aan bas.
Voor alt en tenor kiest het de verbinding met de kleinste verplaatsing.
Het controleert geen verbindingen over een rust waarin alle stemmen zwijgen.

Het akkoordlabel komt uit `analyse_stijl.label_chord`. De voortekening bepaalt de toonsoort per maat.
Voor de modus gebruikt het programma een schatting volgens Krumhansl.

## Regelcodes in de partituur

De tabel geeft per code aan wat het programma meldt en welke noten het rood markeert.
Een *zachte* code is een waarschuwing over een stijlkeuze of een regel met uitzonderingen.

| Code | Wat wordt gemeld? | Welke noten worden rood? |
|---|---|---|
| `P5` `P8` `P1` | Twee bewegende stemmen vormen parallelle kwinten, octaven of priemen. | Beide aankomende noten. |
| `AP5` `AP8` | De kwint of het octaaf keert terug via tegenbeweging of een octaafwisseling. | Beide aankomende noten. |
| `H5` `H8` | Sopraan en bas bewegen dezelfde kant op naar een kwint of octaaf, terwijl de sopraan springt. | Sopraan en bas. |
| `HB5` `HB8` | Zacht: een bas gaat stapsgewijs naar een verborgen kwint of octaaf met een binnenstem die minstens een kwart springt. | De binnenstem. |
| `D5` | Zacht: een verminderde kwint wordt een reine kwint in hetzelfde stemmenpaar. Andersom mag wel. | Beide aankomende noten. |
| `KR` | Een rechterhandnoot ligt onder een klinkende linkerhandnoot, of een stem kruist een aangehouden noot op dezelfde balk. | De kruisende noot. |
| `OV` | Zacht: een stem gaat voorbij de vorige toonhoogte van de buurstem. | De overlappende noot. |
| `LT2` | De leidtoon klinkt verdubbeld. | Beide leidtonen. |
| `LT` | Bij V(7)/vii → I gaat een leidtoon in sopraan of bas niet stapsgewijs naar de tonica. | De leidtoon. |
| `S7` | De akkoordseptiem daalt niet en blijft ook niet liggen. Een septiemakkoord dat alleen ontstaat doordat de sopraan een doorgangsnoot inzet terwijl de andere stemmen liggen, telt niet mee. | De septiem. |
| `N9` | Zacht: de none van een add9-akkoord in een binnenstem of bas daalt niet en blijft ook niet liggen. | De none. |
| `A2` | Een binnenstem springt met een overmatig of verminderd interval, een septiem of meer dan een octaaf. Ook een verminderde kwint telt mee. | De tweede noot. |
| `T2` | Zacht: de terts is verdubbeld in een majeurdrieklank in grondligging of sextligging. | De tertsen. |
| `KAAL` | Zacht: boven de bas klinken alleen grondtoon en kwint. De controle geldt bij minstens twee nieuwe aanslagen en minstens drie klinkende noten. Een bas met een kwart (sus4) telt niet mee. | De inzettende noten. |
| `LIG` | Tussen sopraan en alt of tussen alt en tenor ligt meer dan een octaaf. | De te lage binnenstem. |
| `SPL` | Een dubbelvoorteken, twee spellingen van dezelfde toon in één samenklank, of een nootnaam die afwijkt van de akkoord- of kwintencirkelspelling. | De betreffende noot. |
| `OMV` | Een noot ligt buiten de zangomvang. Deze controle geldt alleen met `--omvang`. | De betreffende noot. |

Bij `SPL` gaat het bijvoorbeeld om cis in een A-akkoord in de toonsoort C.
Een des klinkt op de piano hetzelfde, maar past niet bij de spelling van dat akkoord.
In mineur schrijft de controle de verhoogde zesde en zevende trap met een kruis.
De sopraan valt buiten `N9`, omdat een add9-label daar meestal ontstaat door een doorgangsnoot.
`OMV` is optioneel omdat voorspel en naspel op de piano bewust buiten het bereik van zangstemmen kunnen komen.

De octaafverdubbeling van de bas in de linkerhand telt niet als parallel octaaf (`P8`).
Het programma geeft per noot en code maar één melding.
Een aangehouden noot wordt dus niet bij elke nieuwe samenklank opnieuw gemeld.

## Waarschuwingen en afkeuringen

De zachte codes staan in `harmonie_regels.ZACHT`: `T2`, `KAAL`, `HB5`, `HB8`, `N9`, `D5` en `OV`.
`koele/controleer.py` en `koele/maak_partituren.py` tonen ze als `LET OP` en keuren de zetting er niet op af.
De overige, harde codes leiden wel tot afkeuring en exitcode 1.

De bronnen maken op verschillende plaatsen ruimte voor uitzonderingen.
Aldwell & Schachter beschrijven in 6-18 dat Bach verborgen kwinten en octaven in de buitenstemmen
vermijdt, behalve wanneer de sopraan stapsgewijs gaat. Tussen een buitenstem en een binnenstem
laten zij en Jeppesen zulke verbindingen toe. De waarschuwing `HB5`/`HB8` volgt Hooning 3g.

Een verminderde kwint die een reine kwint wordt (`D5`) vraagt aandacht.
De omgekeerde verbinding mag wel, volgens Aldwell & Schachter 6-16 en Hooning 3f.
Stemoverlap (`OV`) geldt in klaviermuziek niet als fout, volgens Aldwell & Schachter 6-12 en
Hooning 3h. De zetter in `zetter.py` sluit overlap bij het maken van een zetting wel uit.

Hooning 3c geeft bij verdubbeling de voorkeur aan de grondtoon.
Volgens 6c is een verdubbelde terts in een sextakkoord uitzonderlijk, behalve als de sopraan de terts heeft.
Daarom is `T2` een waarschuwing. Ook `KAAL` hangt af van de stijl: volgens Aldwell & Schachter 6-4
mag de kwint ontbreken, maar de terts niet. Bij Jeppesen past een slotakkoord zonder terts juist
in de zestiende-eeuwse stijl.

De sprongcontrole `A2` combineert Jeppesens verbod op overmatige en verminderde melodische intervallen
met het verbod op septiemsprongen en sprongen groter dan een octaaf bij Aldwell & Schachter en Hooning.
De controle op het dalen van de none (`N9`) volgt Schouten, hoofdstuk 22.

## Bronnen van de regels en de 3-5-8-regel

De 3-5-8-regel is hier een geheugensteun voor een vierstemmige drieklank in grondligging: de grondtoon
ligt in de bas, met daarboven een terts (3), kwint (5) en octaaf (8). Een voorbeeld is C–E–G–C.
De C klinkt daarin tweemaal. Dat heet verdubbelen. Gewoonlijk verdubbel je de grondtoon.
De terts moet aanwezig zijn, want die bepaalt of het akkoord majeur of mineur is.

Bij het verbinden van akkoorden gelden ook regels voor de afzonderlijke stemmen. Twee stemmen mogen
bijvoorbeeld niet samen van de ene reine kwint naar de volgende bewegen. Hetzelfde geldt voor octaven
en priemen. Ook tegenbeweging of een octaafwisseling kan een verboden verbinding opleveren.
Voor de buitenstemmen, sopraan en bas, geldt bovendien: als ze in dezelfde richting naar een reine kwint
of octaaf bewegen, moet de sopraan stapsgewijs gaan. Springt de sopraan, dan heet dat een verborgen
kwint of octaaf.

De codes bij deze controles staan in de tabel hierboven. De leerboeken hieronder gebruiken de naam
*3-5-8-regel* niet. Ze behandelen wel de opbouw van akkoorden en de regels voor stemvoering waarop
de controles in `harmonie_regels.py` en de zettingen in `koele/zetter.py` zijn gebaseerd.
Daarbij zijn er verschillen tussen de boeken en het programma.

### Aldwell & Schachter: de basis voor vierstemmige harmonie

Unit 6 van *Harmony and Voice Leading* behandelt welke tonen een akkoord moet bevatten, welke je mag
verdubbelen en hoe ver de stemmen uit elkaar mogen liggen. Ook stemkruising, overlap, melodische
sprongen, parallellen en verborgen parallellen komen daar aan bod.

Voor de zangomvang noemt het boek c'–g'' voor sopraan, g–c'' voor alt, c–g' voor tenor en E–c' voor bas,
met uitbreidingen. De optionele omvangcontrole (`OMV`) laat bij sopraan en alt iets meer ruimte toe.

### Martijn Hooning: afstand tussen stemmen en uitzonderingen bij het slot

Van Hoonings *Harmonieleer* (martijnhooning.nl) zijn hoofdstukken 3b–3h, 5e, 6c en 7e gebruikt.
Hooning houdt de afstand tussen alt en tenor gewoonlijk binnen een sext. Een septiem of octaaf is bij
hem een uitzondering. Het programma volgt hier de ruimere grens van Aldwell & Schachter: `LIG` meldt
pas een afstand groter dan een octaaf.

Bij een slotwending staat Hooning in een binnenstem twee uitzonderingen toe: de leidtoon mag
afspringen en de akkoordseptiem mag stijgen. De controles volgen dat gedeeltelijk. De controle op
de leidtoon (`LT`) geldt alleen voor sopraan en bas. De controle op de septiem (`S7`) geldt voor
alle stemmen en maakt dus geen uitzondering voor zo'n slotwending.

### Knud Jeppesen: melodische regels uit het zestiende-eeuwse contrapunt

*Counterpoint* beschrijft de zestiende-eeuwse vocale stijl waartoe ook Goudimels zettingen behoren.
De samenvatting achterin verbiedt melodische sprongen met een overmatig of verminderd interval.
Ook septiemsprongen en sprongen groter dan een octaaf zijn verboden. De grote sext wordt vermeden,
de kleine sext mag alleen stijgend worden gebruikt.

Leidtonen mogen bij Jeppesen nooit worden verdubbeld. Dat geldt ook voor verhoogde leidtonen in
modale muziek, zoals cis in dorisch en fis in mixolydisch. Het slotakkoord heeft een grote terts
of laat de terts weg.

Het programma controleert niet al deze voorschriften. Het toetst niet op grote sextsprongen,
dalende kleine sextsprongen of reeksen van meer dan vier parallelle tertsen of sexten.

### Hennie Schouten: intervallen en hun oplossing

Hoofdstukken 8, 11, 19 en 22 van *Eenvoudige muziekleer* geven de indeling van intervallen:
prime, kwart, kwint en octaaf zijn volkomen consonanten, terts en sext onvolkomen consonanten.
Secunde, septiem en alle overmatige en verminderde intervallen zijn dissonanten.

Schouten beschrijft ook hoe intervallen oplossen. Bij een overmatig interval bewegen de stemmen
uit elkaar, bij een verminderd interval naar elkaar toe. Septiem en none dalen. Een leidtoon gaat
verplicht naar de dichtstbijzijnde toon waarnaar hij leidt.

## Wat de controle niet ziet

Het programma deelt de stemmen bij elke samenklank opnieuw in op toonhoogte. Daardoor herkent het
wel een kruising tussen de handen of met een aangehouden noot. Als twee bewegende stemmen binnen
één akkoord van plaats wisselen, herkent het die kruising niet.

Ook parallellen met een tussenliggende noot, de zogeheten accent- en naslaande parallellen, vallen
buiten de controle. Het programma toetst evenmin de richting van een stem na een grote sprong.
Van de dissonanten controleert het alleen de oplossing van septiem en none.

## Meldingen beoordelen

De controle gebruikt de regels van de klassieke koraalzetting. Een pianobegeleiding kan daar bewust
van afwijken, bijvoorbeeld met octaven in de melodie of grote afstanden tussen de stemmen.
Bij de transcripties in `midi/` kunnen meldingen ook ontstaan doordat het transcriptiemodel een noot
mist of een extra noot meent te horen. Bekijk daarom de partituur voordat je een gemelde noot corrigeert.

## Opgeslagen rapporten

De [volledige controle](../harmonie_controle.md) geeft de aantallen meldingen per code en per stuk.
Dezelfde gegevens staan in [JSON](../harmonie_controle.json).
Deze rapporten horen bij de opgeslagen berekeningen. De README houdt geen aparte kopie van de tellingen bij.
Na een wijziging aan de regelcontrole kun je de stukken opnieuw controleren met `--force`.
