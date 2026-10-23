# Thematische omlijsting en tegenstemmen

De compositielaag maakt een voorspel en naspel bij een bestaande melodie en zetting.
Een optionele dwarsfluitpartij of piano-bovenstem krijgt een eigen ritme en frasering.
De zangmelodie blijft behouden. Drie kandidaten dienen als materiaal voor vergelijking
en bewerking. Automatische controles vormen geen luisterbeoordeling.

## Automatische harmoniser

Maak bijvoorbeeld `arrangement.json` met:

```json
{
  "seed": 0,
  "candidates": 3,
  "countervoice": "flute",
  "sections": {
    "intro": {"bars": 24},
    "outro": {"bars": 16}
  }
}
```

```sh
.venv-harmonisatie/bin/python harmonisatie/harmoniseer.py \
  harmonisatie/voorbeelden/psalm_49.melodie.json \
  --output harmonisatie/uitvoer/psalm_49_thematisch \
  --complete --arrangement-config arrangement.json
```

De oorspronkelijke koraaluitvoer blijft beschikbaar. Onder `arrangements/` verschijnen
drie MusicXML-partituren, structurele en expressieve MIDI, de gespeelde gebeurtenissen
en een rapport. `countervoice` accepteert `flute`, `piano` en `none`.
Zonder `--arrangement-config` werkt de bestaande opdracht zoals voorheen.
De oudere ingang `python -m harmonizer.cli` gebruikt dezelfde compositielaag.

De standaardlengtes zijn 24 en 16 maten. Secties kunnen een eigen `meter`, bijvoorbeeld
`"3/4"`, en `tempo` krijgen. Expliciete lengtes blijven leidend.
`terminal_quality` in `outro` accepteert `major` of `minor`. Zonder die instelling
volgt het slot een bestaande tonische majeur- of mineurafsluiting van het koraal.
Vóór de zang staan een fermate en caesuur. De expressieve MIDI verlengt het slotakkoord
van het voorspel tot 150% zonder de structurele nootduur te veranderen.

Een optionele `soundfont` verwijst naar een lokale SF2/SF3 voor WAV-uitvoer via
FluidSynth. `--musescore` voegt controle na MuseScore-import en PDF-export toe.

## Muziekgroepbronnen

```sh
.venv/bin/python koele/componeer.py muziekgroep_25_oct/bron/psalm_62.py \
  --config muziekgroep_25_oct/tmp/arrangement.json \
  --output muziekgroep_25_oct/tmp/compositie/psalm_62
```

Voeg `--musescore /pad/naar/mscore` toe voor een volledige zangpartituur in
MSCZ en PDF, met `koele/stijl.mss`.

De uitvoermap moet leeg zijn en binnen dezelfde privé-liedmap liggen. De oorspronkelijke
bron blijft behouden. Naast de arrangementuitvoer verschijnen zelfstandige
Python-bestanden met `STUK`. Ze behouden zangtekst, zangnotatie en herhalingsgegevens.
De bronakkoorden bepalen de harmonie, ook wanneer automatische akkoordherkenning
een onvolledige sus-samenklank anders zou benoemen.

`compositie_vast` houdt de uitgeschreven pianostemmen intact bij opnieuw laden.
De akkoordgegevens blijven beschikbaar voor gitaarakkoorden boven de pianobalk.
`handverdeling` bewaart de gecontroleerde verdeling over de handen. De zangmelodie
kan onder een hoge piano-bovenstem naar de linkerhand wanneer ze daar past.
Iedere hand blijft binnen een octaaf. Controleer en render een nieuwe variant met
de bestaande muziekgroepgereedschappen voordat je hem voor de uitvoering kiest.

## Compositie en controle

Motieven komen uit cellen van 3–5 noten binnen een zangfrase. Iedere cel bewaart alle
nootduren, tussenliggende rusten, octaven, alteraties en bronposities. Karakteristiek
ritme, frasebegin en niet-overlappende herhalingen tellen mee bij de selectie.
Transpositie en inversie gebruiken gehele diatonische posities. Modulo 7 zou de
octaafligging verliezen. Diminutie vermenigvuldigt de duur met bijvoorbeeld 0,5.
Kreeftgang keert volledige nootgebeurtenissen om, inclusief duur en afstand.

Het voorspel begint bij voorkeur met een cel uit de opening van de zangmelodie.
Vier maten vormen een vraag en antwoord met een voorbereide cadens. Een sequens
verkleint het motief doelgericht. Een cel wordt afgerond binnen haar plaats in de
frase, zodat een motief van bijvoorbeeld 4½ tel niet onbedoeld over alle volgende
maatstrepen verschuift. De octaafligging sluit aan op de vorige frase.

De middenstemmen en bas blijven doorgaans twee tellen liggen terwijl de bovenstem
beweegt. Ze worden niet bij iedere melodienoot opnieuw gezet. Na de korte opening
vult de begeleiding aan. De majeur- of mineurterts blijft aanwezig. Een sus4 in de
cadens lost op in dezelfde dominant. Korte doorgangen en wisselnoten worden pas
toegevoegd als de hele frase, de samenklanken en de handverdeling dat toelaten.

Het naspel neemt ook materiaal uit de staart van de melodie over en sluit met zijn
eerste register aan op het einde van de zangsectie. Het krijgt een eigen tonisch
slot. Het rapport vermeldt welke bedoelde motiefnoten behouden zijn gebleven.
Dit beschrijft de constructie en vormt geen automatische muzikale goedkeuring.

De fluit gebruikt C4–D5, springt hoogstens een terts en mag onder de zang komen. De piano-bovenstem gebruikt
D5–G5 en behoudt de melodie. Zo nodig vervalt een binnenstem.
Rusten geven ademruimte. Korte verbindingen worden op doorgang en oplossing getoetst.
Tegenbeweging is een voorkeur en geen verplichting.

Een lange oorspronkelijke binnenstem kan onder de bewegende piano-bovenstem
plaatselijk wegvallen. De zoekstap probeert dan kortere akkoordtonen, bij voorkeur
de terts, binnen dezelfde regels en hetzelfde handbereik.

De controle omvat de tegenstem tegen alle pianostemmen en de zangmelodie, inclusief
noten die bij een akkoordwisseling blijven liggen. Ze onderscheidt akkoordtonen,
doorgangen, wisselnoten en voorbereide voorhoudingen. Lokale omkeringen en
akkoordwijzigingen staan in het rapport. Bij uitgeputte zoekruimte volgt een fout
met de betrokken positie. Een ongeldige lijn krijgt geen stilzwijgende vervanging.

De STUK-controle volgt vaste stemnummers. Daardoor worden rustende stemmen niet
op basis van toonhoogte aan een andere melodielijn gekoppeld. Voor transcripties
zonder vaste stemnummers blijft de bestaande schatting beschikbaar.

## Koeles opnamen onderzoeken

De lokale inventaris omvat 49 opnamen: 40 losse opnamen en 9 compilaties.
Er zijn expliciete sectiegrenzen voor Psalm 37 en Psalm 85. Het onderzoeksrapport
herberekent ook vormvoorstellen voor Psalm 73, ‘Mijn Jezus, ik hou van U’ en
‘I need Thee every hour’. Dat laatste lied blijft validatiemateriaal en levert
geen trainingssecties.

```sh
.venv/bin/python -m harmonizer.section_research \
  --manifest private_data/harmonizer/corpus/manifest.json \
  --scores private_data/midi --splits splits.json \
  --previous private_data/stijlanalyse.json \
  --output private_data/harmonizer/nieuw_compositieonderzoek.json
```

Het rapport bewaart bronhashes, sectiegrenzen, bekende audiovensters,
motiefvoorstellen per notatiestem en verschillen met de oudere analyse.
Automatische voorstellen krijgen geen keurmerk `reviewed`. Geef het rapport
optioneel op als `style_analysis`. Ongecontroleerde secties zijn uitsluitend
met `allow_draft: true` beschikbaar voor experimenten.

De huidige transcriptie van Psalm 85 telt 22 maten voorspel en 10 maten naspel.
Het oude rapport gaf een andere vormindeling. De boekfoto's tonen bovendien een
fermate vóór het koraal. Boekversie, uitvoering en transcriptie vragen daarom een
afzonderlijke beoordeling. Terugkerende korte cellen en afwisseling van beweging
tussen de handen leveren bruikbare voorbeelden voor de compositieplanning.

De overdraagbare regressietests draaien met:

```sh
.venv/bin/python -m unittest discover -s tests -v
```
