# Gerrit Koele – van YouTube naar bladmuziek

Scripts die de publieke pianovideo's van [Gerrit Koele](https://www.youtube.com/@GerritKoeleMusicus/videos)
omzetten naar mp3 en vervolgens naar leesbare, speelbare bladmuziek (MusicXML voor MuseScore) plus MIDI.
Zie [stijlanalyse.md](stijlanalyse.md) voor een uitgebreide karakterisering van de muzikale stijl en signatuur van Gerrit Koele.

```
download_koele.sh      stap 0: YouTube -> mp3/
transcribe_midi.sh     stap 1+2: mp3/ -> midi_raw/ (ruwe transcriptie) -> midi/ (opgeschoonde partituur)
transcribe_piano.py    het eigenlijke werk; transcribe_midi.sh is alleen een wrapper
analyse_stijl.py       stap 3: stijlanalyse over alle stukken -> stijlanalyse.json / stijlanalyse.md
controleer_harmonie.py stap 4: formele controle van de zettingen -> midi_controle/ (foute noten rood)
corrigeer_harmonie.py  stap 5: binnenstemmen herzetten -> midi_gecorrigeerd/ (gewijzigd groen, rest rood)
hypercorrectie.py     stap 6: bas en binnenstemmen herzetten met vaste melodie -> midi_hypercorrectie/
```

## Installatie

Vereisten: Python 3.10 of 3.11 en optioneel `ffmpeg` (voor audiosegmentatie) en `yt-dlp` (voor downloaden van video's).

### Met uv (aanbevolen)

Met [uv](https://docs.astral.sh/uv/) installeer je de afhankelijkheden snel in een virtuele omgeving:

```bash
# 1. Maak een virtuele omgeving aan en activeer deze
uv venv
source .venv/bin/activate

# 2. Installeer alle vereiste pakketten via requirements.txt
uv pip install -r requirements.txt
```

### Met standaard pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Externe tools (macOS)

```bash
brew install ffmpeg yt-dlp
```

## Secties, maatsoorten en toonsoorten

Met `--split-sections` verwerkt het script voorspel, koraal en naspel afzonderlijk. Elke sectie
krijgt een eigen tempo en maatsoort. De complete partituur heeft doorlopende maatnummers,
maatwissels, dubbele maatstrepen en sectieaanduidingen.

Stiltes van minstens één seconde vormen de automatische sectiegrenzen. Met `splits.json` of
`--splits` en `--meters` kun je snijpunten en maatsoorten instellen. `--save-parts` bewaart ook
de afzonderlijke audiofragmenten en partituren. Voor verzamelvideo's gebruik je
`splits_compilaties.py`, dat zelfstandige stukken op basis van langere stiltes onderscheidt.

Met `--key` of `splits.json` leg je de toonsoort of modus vast, bijvoorbeeld `C dorian` voor
Psalm 37. De spelling volgt het akkoord en de toonsoort, inclusief verhoogde leidtonen.
De log vermeldt `syncopen` en `maat_hint` als hulpmiddelen om ritmische notatie te beoordelen.

## Stap 0 – `download_koele.sh`

Haalt met `yt-dlp` alle video's van het kanaal op als mp3 (beste audiokwaliteit, `--audio-quality 0`).

- `--download-archive archive.txt`: een video die al binnen is wordt overgeslagen; het script kan dus gerust
  opnieuw gedraaid worden om nieuwe video's bij te halen.
- `--ignore-errors`: één mislukte video (privé, verwijderd, geo-blok) stopt de rest niet.
- `--sleep-interval 2 --max-sleep-interval 6`: kleine pauzes tussen downloads tussen opeenvolgende verzoeken.
- Bestandsnaam bevat uploaddatum, titel en video-id, zodat titels die vaker voorkomen niet botsen.
- Alles (ook de yt-dlp-uitvoer) gaat naar `download.log`; `videos.txt` krijgt per video een regel.

## Stap 1+2 – `transcribe_midi.sh` / `transcribe_piano.py`

```bash
./transcribe_midi.sh                         # alle mp3's; bestaande midi/*.musicxml worden overgeslagen
./transcribe_midi.sh --split-sections        # met automatische voorspel/koraal/naspel splitsing en maatwissels
./transcribe_midi.sh --reclean               # alleen stap 2 opnieuw (na een scriptwijziging), ruwe midi hergebruiken
./transcribe_midi.sh --force                 # alles opnieuw, ook de transcriptie
python transcribe_piano.py --reclean --split-sections --save-parts "mp3/…één stuk….mp3"
```

Opties (`--help` voor de volledige lijst):

| Optie | Standaard | Betekenis |
|---|---|---|
| `--model transkun\|bytedance` | transkun | transcriptiemodel (zie stap 1) |
| `--split-sections` | uit | splits automatisch op stiltes in voorspel/koraal/naspel en voeg samen met maatwissels |
| `--min-silence SEC` | 1.0 | minimale stilte in seconden voor een sectiegrens |
| `--silence-db DB` | 30.0 | stilte-drempel in dB onder audiopiek |
| `--splits T1,T2` | | handmatige snijpunten in seconden (bijv. `64.18,144.82`) |
| `--meters M1,M2,M3` | | handmatige maatsoorten per sectie (bijv. `4,6,4` voor 4/4 -> 3/2 -> 4/4) |
| `--save-parts` | uit | bewaar ook de losse mp3's in `mp3_delen/` en partituren in `midi_delen/` |
| `--grid 0\|2\|3\|4` | 0 (auto) | onderverdeling per tel: 2 = achtsten, 4 = zestienden, 3 = triolen |
| `--meter 0\|2\|3\|4\|6` | 0 (auto) | maatsoort forceren: 2/4, 3/4, 4/4 of 3/2 (6 tellen) |
| `--key KEY` | | toonsoort of aantal voortekens forceren (bijv. `'C dorian'`, `'g minor'`, `'2b'`, `'-2'`) |
| `--tempo-range MIN MAX` | 60 120 | toegestaan bereik voor het genoteerde tempo |
| `--split N` | 60 (C4) | basis-splitspunt tussen de handen |
| `--leap N` | 7 | max. halve tonen dat een hand buiten zijn eigen balk mag grijpen |
| `--no-repeats` | | geen coupletherkenning / herhalingstekens |
| `--pedal` | | pedaaltekens uit de transcriptie overnemen |
| `--reclean` / `--force` | | zie hierboven |


Elke mislukking wordt gelogd (`FOUT: …` + traceback) en de rest gaat door. De log-regel per stuk ziet er zo uit:

```
OK: noten=1708, R=1019, L=689, bpm=92, raster=1/8, maat=4/4, opmaat=0, fermates=8, afwijkende_maten=1, toonsoort=G major -> C major -> F major, couplet=-, 3s
```

### Stap 1 – ruwe transcriptie (audio → noten)

- **Transkun v2** (Yan & Duan 2024, standaard): neuraal piano-transcriptiemodel; wordt als CLI aangeroepen
  (`transkun --device mps in.mp3 out.mid`). Op een Mac draait het op de GPU (MPS), anders CPU.
- **ByteDance** "High-resolution piano transcription" (Kong et al. 2020) als alternatief via `--model bytedance`
  (checkpoint in `~/piano_transcription_inference_data/`).

Het resultaat is een MIDI met exacte begin-/eindtijden, aanslagsterkte (velocity) en pedaalgebruik. Deze schatting van de uitvoering is
nog niet geschikt als bladmuziek: geen maten, rubato, elke noot met zijn eigen lengte,
akkoorden die niet tegelijk beginnen, doorklinkende pedaalnoten. Stap 2 maakt daar notatie van.

### Stap 2 – opschonen (noten → partituur)

De ruwe noten worden losgelaten op een raster en stap voor stap "genormaliseerd" richting wat een uitgever zou
drukken. De referentie daarvoor is één vioolsleutel-balk voor rechts, één bassleutel-balk voor links, blokakkoorden, 
gewone maten met fermates waar het tempo wordt losgelaten, sleutelwissels en 8va waar een hand ver buiten zijn balk komt, dynamiek mf/mp/f.

#### 2a. Tijdraster

1. **Beat-tracking** (`librosa.beat.beat_track`) op de audio zelf, niet op de MIDI: geeft per tel een tijdstip,
   zodat rubato (vertragen/versnellen) wordt rechtgetrokken – de noten komen op vaste tellen te staan.
2. **Tempo-niveau**: de tracker kiest soms de halve of dubbele puls. Ligt het tempo buiten `--tempo-range`
   (60–120), dan wordt om de andere beat weggelaten (de fase waar de meeste aanslagen op vallen) of worden
   tussenbeats ingevoegd. Het raster wordt vóór de eerste en na de laatste beat doorgetrokken.
3. **Fasecorrectie**: de tracker loopt vaak systematisch iets voor of achter op de aanslagen. Het circulaire
   gemiddelde van de aanslagposities binnen de beat bepaalt de verschuiving van het hele raster.
4. **Rasterkeuze** (`--grid 0`): achtsten, tenzij minstens een kwart van de aanslagen duidelijk beter op
   zestienden of triolen valt. Bewust conservatief: fijnere rasters maken van timing-ruis zestienden.
5. Bij een zestienden-raster worden **geïsoleerde off-zestienden** (geen buuraanslag een zestiende verderop)
   alsnog naar de dichtstbijzijnde achtste gesnapt – dat zijn vrijwel altijd timingfouten, geen echte zestienden.

Noten met velocity < 15 worden weggegooid (modelruis).

#### 2b. Handverdeling

Het model weet niet welke hand wat speelt; dat moet uit de toonhoogtes worden afgeleid.

1. **Lokaal splitspunt** (`local_split`): per moment een 2-means-clustering op alle noten binnen ±8 tellen.
   Liggen de twee clusters ≥ 10 halve tonen uit elkaar, dan ligt het splitspunt ertussen (begrensd tot C3–C5).
   Zit alles in één register, dan gaat alles naar de hand waar dat register thuishoort. Zo volgt de verdeling
   het register: een laag voorspel schuift het splitspunt omlaag, een hoge passage omhoog.
2. **Per aanslagmoment** (`assign_hands`) worden alle noten die tegelijk beginnen bekeken en wordt het beste
   splitspunt gezocht bij het grootste toonhoogte-gat, met controles:
   - beide handen hoogstens een handspanning (14 halve tonen, een none) breed;
   - gat minstens 3 halve tonen;
   - het onderste cluster hoort bij links (gemiddelde niet ver boven het splitspunt) en andersom;
   - **reikwijdte** (`--leap`): links mag tot A3 + 7 = E4, rechts tot E4 − 7 = A3, tenzij het lokale splitspunt
     zelf verder ligt. Voorkomt dat een enkele hoge noot met drie hulplijnen in de linkerhand belandt terwijl
     die prima bij rechts past.
   - Lukt geen splitsing, dan gaat een compact akkoord (≤ handspanning) in zijn geheel naar één hand.
3. **Herverdeling** (`rebalance`): speelt een hand op een bepaald moment niets, dan verhuizen de onderste noten
   van een rechterhand-akkoord (≤ E4) naar links en de bovenste van links (≥ A3) naar rechts. Een losse
   doorklinkende noot verhuist alleen als er een nieuwe aanslag van dezelfde hand overheen komt.

#### 2c. Noten → leesbare groepen per hand (`build_groups`)

- **Spooknoten**: binnen een akkoord vervallen noten die veel zachter zijn dan de rest (< 30 % van de hardste,
  of velocity < 20) – dat zijn meestal boventonen of foutieve model-detecties.
- **Blokakkoord-notatie**: alle noten van één aanslag krijgen één lengte (mediaan), afgerond op halve tellen
  vanaf een halve tel en daarna op een noteerbare lengte (`NICE`: 1, 2, 3, 4, 6, 8, … rastereenheden).
- Een aanslag duurt tot de volgende aanslag van dezelfde hand: **overlappen** (pedaal) worden afgekapt,
  **gaatjes** korter dan een tel worden legato dichtgemaakt. Echte rusten van een tel of meer blijven staan.
- **Tweede stem**: één noot per hand mag doorklinken onder/boven volgende aanslagen – een losse basnoot in de
  linkerhand, een losse melodienoot (bovenstem) in de rechterhand – mits alle tussenliggende aanslagen er
  respectievelijk boven/onder liggen en de noot minstens een tel langer is dan het gat. Meer dan twee stemmen
  per balk komen dus nooit voor.

#### 2d. Maatsoort, maatstrepen, opmaat, fermates

1. **Accentsignaal** per tel (`detect_meter`): aantal aanslagen + nootlengtes + 2× de harmonische verandering
   (cosinusafstand tussen chroma-vectoren van opeenvolgende tellen). Akkoordwisselingen blijken de beste
   aanwijzing voor tel 1.
2. **Maatsoort**: autocorrelatie van dat signaal; is die op 3 + 6 tellen sterker dan op 4 + 8, dan 3/4, anders
   4/4 (`--meter` om te forceren). 2/4 en 3/2 worden niet automatisch gekozen – de autocorrelatie alleen is te
   zwak om die betrouwbaar te onderscheiden – maar zijn te forceren met `--meter 2` resp. `--meter 6`. De
   log-regel `maat_hint=3/2` verschijnt als het accentpatroon wel om de 6 maar niet om de 3 tellen terugkomt
   (bijv. een koraal in 3/2); dat is het signaal om `--meter 6` te proberen.
3. **Maatstrepen** via **Viterbi-tracking** (`track_bars`): normaal om de m tellen, maar één maat mag m + 1 of
   m − 1 tellen lang zijn tegen een straf (2,5). Zonder dit gooit één fermate of vertraging, waar de
   beat-tracker een tel te veel of te weinig telt, de rest van het stuk uit de maat.
4. **Opmaat**: wat vóór de eerste tel-1 ligt wordt een opmaat (maatsoort van de volle maat wordt al in de
   opmaat getoond).
5. **Fermates in plaats van afwijkende maten** (`normalise_bars`): is een te lange/korte maat aan het einde
   een aangehouden noot of rust (geen aanslagen in de staart), dan wordt de maat weer m tellen door die noot
   in te korten/te verlengen en krijgt hij een fermate – precies zoals een partituur "rit." + fermate noteert.
   Een maat waarin tot het einde wordt doorgespeeld blijft als tijdelijke maatsoort (bijv. 5/4) staan; dat
   aantal staat in de log als `afwijkende_maten` en is een goede indicator voor stukken die handmatige
   controle nodig hebben.

#### 2e. Coupletten (`find_verses`)

Per maat een chroma-vector (welke toonklassen hoe lang klinken). Wordt een blok van ≥ 8 maten ≥ 2× achter
elkaar bijna identiek herhaald (cosinus-gelijkenis ≥ 0,92), dan wordt het één keer genoteerd met
herhalingstekens (`|: :|`, met het aantal keren). `--no-repeats` zet dit uit; de MIDI bevat altijd alles
uitgeschreven.

#### 2f. Partituur (`build_score`, music21)

- Twee `PartStaff`s (viool- en bassleutel) in één `StaffGroup` met accolade: MuseScore toont één piano met
  twee balken (niet vier).
- **Toonsoort per deel** (`key_segments`): per maat een Krumhansl-Schmuckler-schatting over ±6 maten
  (toonklasse-histogram gewogen naar nootlengte, gecorreleerd met de 24 toonsoortprofielen). Runs korter dan
  16 maten worden bij de langste buur gevoegd, zodat alleen echte modulaties (bijv. een couplet in een andere
  toonsoort) een nieuwe voortekening opleveren; in de log staat dan `toonsoort=G major -> C major -> F major`.
  Zonder dit stond 'U zij de glorie' in C met 68 losse kruisen voor F#.
  De **spelling gebeurt per verticaal** (`spell_vertical`): eerst wordt geprobeerd het akkoord als stapeling van
  tertsen te spellen (B-D#-F#, niet B-Eb-F#), met de grondtoonspelling die zo weinig mogelijk voortekens kost en
  het dichtst bij de voortekening ligt; lukt dat niet, dan de toonsoortspelling, en bij een tweeklank de
  intervalspelling (een terts boven een sext: B-D# wint van Eb-B). In mineur worden de verhoogde 6e en 7e trap
  (harmonisch/melodisch mineur) als kruis gespeld, zodat de leidtoon D# heet en niet Eb. `makeAccidentals` zet de voortekens per maat.
- **Maatsoorten** bij elke verandering van maatlengte; tempo-aanduiding (♩ = bpm) op de eerste maat.
- **Stemmen**: `makeVoices`/`makeMeasures`/`makeTies`; een maat met maar één echte stem wordt weer platgeslagen.
  Elke stem wordt over de hele maat met rusten gevuld en die rusten worden op tel-grenzen gehakt (geen
  dubbelgepunteerde rusten). Onzichtbare rusten die de MusicXML-export invoegt worden verwijderd (die zag je in
  MuseScore als grijze balkjes).
- **Sleutelwissel**: telt per maat hoeveel hulplijnen elke sleutel zou kosten (≈ 1 per 3,5 halve toon buiten
  de balk); is de andere sleutel minstens 2 maten achter elkaar duidelijk goedkoper, dan wisselt de balk van
  sleutel (linkerhand naar vioolsleutel in een hoog voorspel, en terug).
- **8va**: maten in de rechterhand met een hoogste noot ≥ C6 waar een octaaf lager noteren duidelijk
  hulplijnen scheelt, krijgen een 8va-lijn; aaneengesloten maten één lijn. De noten staan in de MusicXML een
  octaaf lager met een `octave-shift`, zodat MuseScore ze goed toont én afspeelt.
- **Fermates** op de noot die door `normalise_bars` is gerekt/ingekort (bij bindingen op het laatste deel);
  het slotakkoord wordt tot het einde van de maat verlengd en krijgt altijd een fermate.
- **Dynamiek**: gemiddelde velocity per maat, vooruitkijkend gemiddeld over 4 maten, relatief ten opzichte van
  het stuk (mediaan = mf, 10 velocity per stap: pp p mp mf f ff). Een nieuw teken komt alleen bij een sprong
  van ≥ 2 stappen (na ≥ 2 maten) of ≥ 1 stap na ≥ 8 maten – geen geflikker van mf/f om de maat.
- **Pedaal** (`--pedal`): CC64-tijden uit de ruwe MIDI worden naar rastereenheden vertaald (incl. de
  verschuivingen van de fermate-normalisatie) en als pedaallijnen onder de linkerhand gezet. Standaard uit,
  omdat de lengtes afgekapte noten toch al "met pedaal" impliceren.

De `.mid` in `midi/` bevat dezelfde opgeschoonde noten als één track met het genormaliseerde tempo; MuseScore
verdeelt die zelf weer over twee balken, maar mist dan alle notatiekeuzes – gebruik dus de `.musicxml`.

## Stap 3 – `analyse_stijl.py` (stijlanalyse)

```bash
python analyse_stijl.py        # leest midi/*.musicxml + midi_raw/*.transkun.mid, schrijft stijlanalyse.json (~2 min)
```

Per stuk worden gemeten: toonsoort(en) per maat, akkoordlabel per tel (sjabloon-matching op 15 akkoordtypen,
Romeinse trap, ligging), vormdelen (voorspel / koraal / tussenspel / naspel op basis van melodische herhaling:
een couplet is een passage waarvan de intervalreeks ≥ 32 tellen verderop bijna letterlijk terugkomt), per
vormdeel textuur/register/dynamiek/akkoordstatistiek, cadensen op fermates, basbeweging, orgelpunten,
octaafverdubbelingen, en uit de ruwe MIDI pedaalgebruik, legato, gebroken akkoorden en het slot-ritenuto.
Titels uit verzamelvideo's doen niet mee aan de vorm-statistiek. De duiding staat in
`stijlanalyse.md`; §0 daarvan zegt welke cijfers betrouwbaar zijn en welke niet.

### De stijl van Gerrit Koele

De volledige muzikale duiding en statistische analyse van Koeles signatuur is vastgelegd in [stijlanalyse.md](stijlanalyse.md) (zie §0 aldaar voor de betrouwbaarheid per categorie). De voornaamste kenmerken:

- **Vaste vormarchitectuur**: Vrijwel elk stuk volgt de opbouw `Voorspel (~33%) → Koraal (couplet 1, ~21%) → Tussenspel (~9%) → Koraal (couplet 2) → Naspel (~20%)`. Een koraal wordt nooit zonder omlijsting gespeeld en sluit altijd af met een substantieel naspel.
- **Diatonische harmonie en sus4-kleur**: 65% van alle akkoorden zijn zuivere drieklanken; septiemakkoorden zijn schaars (<13%) en verminderde of jazz-akkoorden ontbreken geheel. Hét handelsmerk is het **sus4-akkoord** (10,6% van alle akkoorden; typisch `Vsus4 → I` en `Isus4 → I`). In mineur klinken veel modale wendingen (v, VII) met regelmatig een picardische terts op slotakkoorden.
- **Driestemmige pianozetting**: Het koraal is overwegend driestemmig gezet (melodie + 1 noot in de rechterhand, enkele basnoot in de linkerhand). De melodie ligt altijd in de bovenstem in natuurlijke zangligging. De bas is een wortelbas (74% grondligging), versterkt met linkerhandoctaven in het slotcouplet en naspel.
- **Rustig slot**: Het naspel is het rustigste en zachtste deel, kenmerkt zich door plagale wendingen (IV → I), en sluit af met een breed ritenuto naar een zacht, middelhoog, 3- tot 5-stemmig grondliggingsakkoord met aangehouden pedaal.
- **Pedaal en speelstijl**: Nagenoeg continu pedaalgebruik (~89% van de tijd, wisselend per akkoord), strikt legato (geen staccato) en een stabiel, gematigd tempo (mediaan 86 bpm).

Zie [stijlanalyse.md](stijlanalyse.md) voor de gedetailleerde analyse, frequentietabellen, modulatiepatronen en het altijd/regelmatig/zelden/nooit-overzicht.

## Stap 4 – `controleer_harmonie.py` (formele controle)

```bash
python controleer_harmonie.py                      # alle stukken (~1 min); overslaan als uitvoer nieuwer is
python controleer_harmonie.py --only "Psalm 85" --force
python controleer_harmonie.py --omvang             # ook de zangomvang van S/A/T/B toetsen (OMV)
```

Toetst elke zetting in `midi/` aan de regels van de klassieke vierstemmige koraalzetting en schrijft
`midi_controle/<stem>.musicxml` (open in MuseScore: foute noten rood, met de code(s) als tekst onder de noot),
`midi_controle/<stem>.txt` (`maat 12 tel 3 | P5 | T G3 | met S: D4-A4 -> E4-B4`) en samengevat
`harmonie_controle.md` (per code en per stuk, fouten per 100 verticalen).

De partituur wordt gelezen als een reeks verticalen: elk moment waarop een noot inzet, met alle klinkende noten (ook aangehouden), gesorteerd op hoogte. 8va-lijnen worden omgerekend naar klinkende hoogte. Stemmen worden op positie ingedeeld: B is de laagste noot, S de hoogste, en daartussen T en A. Bij meer dan vier noten koppelt het algoritme extra noten als verdubbeling aan de dichtstbijzijnde stem. Tussen opeenvolgende verticalen worden de stemmen gekoppeld (S↔S, B↔B, en binnenstemmen met minimale verplaatsing). Over een algemene rust heen wordt niets getoetst. Het akkoordlabel per verticaal komt uit `analyse_stijl.label_chord`, de toonsoort per maat uit de voortekening (modus via Krumhansl).

| Code | Regel | Rood |
|---|---|---|
| `P5` `P8` `P1` | open parallelle kwinten/octaven/priemen tussen twee stemmen die beide bewegen; `AP5`/`AP8` als het interval via tegenbeweging of octaafwissel terugkeert | beide aankomende noten |
| `H5` `H8` | verborgen kwint/octaaf in de buitenstemmen: S en B gelijkbewegend naar 5/8 terwijl S springt | S en B |
| `KR` | stemkruising: rechterhandnoot onder een klinkende linkerhandnoot, of een stem kruist een liggende noot in dezelfde balk | de kruisende noot |
| `OV` | overlap: een stem gaat voorbij de vorige toon van de buurstem | de overlappende noot |
| `LT2` | verdubbelde leidtoon | beide |
| `LT` | leidtoon in een buitenstem gaat bij V(7)/vii → I niet stapsgewijs naar de tonica | de leidtoon |
| `S7` | akkoordseptiem lost niet dalend (of liggend) op | de septiem |
| `A2` | overmatige secunde/kwart of sprong > octaaf in een binnenstem | de tweede noot |
| `LIG` | ligging: meer dan een octaaf tussen S–A of A–T | de te lage binnenstem |
| `SPL` | spelling: dubbelvoortekens, dezelfde toon tweemaal anders gespeld in één verticaal, of een spelling die afwijkt van de akkoordspelling (A-akkoord in C: cis, niet des) c.q. de kwintencirkelspelling (in mineur: verhoogde 6e/7e trap als kruis) | de noot |
| `OMV` | buiten de zangomvang (alleen met `--omvang`; voor- en naspel gaan bewust hoog en laag) | de noot |

Piano-uitzonderingen: de octaafverdubbeling van de bas in de linkerhand telt niet als `P8`, en één melding per
noot en code (een liggende noot wordt niet elke verticaal opnieuw gemeld).

Een deel van de meldingen ontstaat door transcriptie-artefacten (spooknoten, een gemiste stem) of door typische pianozettingen zoals octaven in de melodie en wijde liggingen. De controle toetst uitsluitend aan klassieke koraalregels.

### Resultaten controle over alle 49 stukken

Zie `harmonie_controle.md` en `harmonie_controle.json` voor de volledige tabellen per stuk.
Over alle 49 stukken en 58.928 verticalen gaf de controle 11.596 meldingen (gemiddeld 19,7 per 100 verticalen):

| Code | Aantal | Per 100 verticalen | Toelichting |
|---|---|---|---|
| `LIG` | 2289 | 3.9 | Wijde ligging (> octaaf tussen S-A of A-T), typerend voor pianozetting |
| `OV` | 1360 | 2.3 | Stemoverlap |
| `H5` / `H8` | 1982 | 3.4 | Verborgen kwinten (1116) en octaven (866) in buitenstemmen |
| `SPL` | 1016 | 1.7 | Afwijkende enharmonische spelling |
| `P8` / `P5` | 1672 | 2.8 | Parallelle octaven (940) en kwinten (732) |
| `S7` | 813 | 1.4 | Akkoordseptiem lost niet dalend of liggend op |
| `AP8` / `AP5` | 1215 | 2.1 | Antiparallellen via tegenbeweging |
| `LT2` / `LT` | 594 | 1.0 | Verdubbelde leidtoon (558) of onopgeloste leidtoon (36) |
| `A2` | 521 | 0.9 | Overmatige sprong in binnenstem |
| `KR` | 134 | 0.2 | Stemkruising tussen handen of stemmen |


## Stap 5 – `corrigeer_harmonie.py` (binnenstemmen herzetten)

```bash
python corrigeer_harmonie.py                       # alle stukken (rekentijd afhankelijk van de zetting)
python corrigeer_harmonie.py --only "Psalm 85" --beam 20 --force
python corrigeer_harmonie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/gecorrigeerd --force
```

Herzet de binnenstemmen met behoud van de toonhoogte en het ritme van melodie en bas.
Ook aangehouden noten die later een buitenstem vormen blijven vast. De handverdeling,
nootlengtes en rusten blijven behouden. De enharmonische spelling wordt voor alle stemmen gecontroleerd.

De zoektocht weegt harmonische regels af tegen de melodische lijn van de binnenstemmen.
Naast parallellen, stemkruisingen en septiemoplossingen beoordeelt het script de contour van
de oorspronkelijke lijn en stapsgewijs herstel na een sprong over drie opeenvolgende klanken.
Oorspronkelijke niet-akkoordtonen krijgen extra bescherming, zodat doorgangsnoten en
voorhoudingen niet zonder meer verdwijnen ten gunste van akkoordtonen.

`--beam` bepaalt hoeveel alternatieve zettingen de zoektocht bewaart, standaard 32.
Een grotere waarde vergroot de zoekruimte en de rekentijd. Het resultaat is deterministisch.
De methode gebruikt muzikale voorkeuren, maar beoordeelt geen volledige frasen of expressie.

Gewijzigde noten verschijnen groen met de oorspronkelijke noot als toelichting.
Resterende meldingen van de formele controle verschijnen rood. De uitvoer staat in
`midi_gecorrigeerd/`, met rapporten in `harmonie_correctie.md` en `harmonie_correctie.json`.
Bij een gewijzigd algoritme of andere bundelbreedte worden bestaande resultaten opnieuw berekend.
`--input-dir` en `--output-dir` selecteren andere partituurmappen. `--report-dir` bepaalt waar
de rapporten worden bewaard. Een gedeeltelijke berekening behoudt de rapportregels van andere stukken.
Een lege selectie stopt met een foutmelding en laat de bestaande rapporten intact.

De vier voorbeeldpartituren zijn met deze correctiemethode berekend. De overige regels in
het verzamelrapport betreffen de eerder opgeslagen berekeningen. Een lager aantal
regelmeldingen is op zichzelf geen maat voor muzikale kwaliteit. Meldingen kunnen ook na
correctie in binnenstemmen voorkomen, naast de ongewijzigde buitenstemmen.

## Hypercorrectie: vaste melodie, vrije bas en binnenstemmen

`hypercorrectie.py` zoekt een zetting zonder meldingen van de volledige standaardcontrole uit
`harmonie_regels.py`. De hoogste klinkende rechterhandnoot geldt als melodie. Die blijft vast,
inclusief spelling, duur en bindingen. Een linkerhandnoot die de melodie kruist, blijft bewerkbaar.

```bash
python hypercorrectie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/hypercorrectie --seconds 300
python hypercorrectie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/hypercorrectie --only "Psalm 85" --resume --seconds 300
```

De zoektocht gebruikt de bestaande regelcontrole rechtstreeks. Zij probeert andere basnoten,
omkeringen en liggingen, en kan meerdere noten gezamenlijk wijzigen. Bij een te grote afstand
onder de melodie mogen aangehouden binnenstemmen gericht opnieuw worden aangeslagen. De
klinkende stemdichtheid en totale tijdsdekking per hand blijven behouden. Er verdwijnen geen
stemmen of passages om aan de regels te voldoen.

De muzikale voorkeuren bewaken de oorspronkelijke toonklassen, akkoordidentiteit, bascontour en
harmonische wisselingen. Herhaalde aanslagen zijn beperkt tot aangehouden binnenstemmen bij
liggingsproblemen. De zoekfunctie gebruikt geen willekeurige versieringen. `--seed` bestuurt
alleen het verkennen van alternatieve oplossingen wanneer lokale wijzigingen vastlopen.

Na export wordt de MusicXML opnieuw ingelezen en gecontroleerd. De status `volledig` vereist
nul formele meldingen én geslaagde controles op melodie, tijdsdekking en variatie. Bij onvoldoende
zoekruimte, rekentijd of onverenigbare eisen wordt de status `onvolledig` en eindigt het script met
exitcode 2. De melodie wordt nooit vrijgegeven om toch een succesmelding te kunnen geven.
De optionele toets aan zangomvangen (`OMV`) valt buiten deze standaardcontrole van pianozettingen.

| Optie | Standaard | Betekenis |
|---|---:|---|
| `--seconds` | 300 | zoektijd per stuk, exclusief inlezen en exporteren |
| `--rounds` | 100 | maximaal aantal zoekrondes |
| `--radius` | 36 | maximale afwijking in halve tonen per bewerkbare noot |
| `--seed` | 0 | startwaarde voor het verkennen van alternatieven |
| `--resume` | uit | hervat de opgeslagen toonkeuzes bij exact dezelfde bron en voorbereiding |

Een ruim toonhoogtebereik maakt andere liggingen mogelijk. De muzikale kosten geven de voorkeur
aan kleinere wijzigingen. Hervatten controleert bron- en voorbereidingsvingerafdrukken en weigert
wijzigingen buiten de gekozen zoekruimte. Door de tijdslimiet kan het resultaat per machine verschillen.

De vier uitvoeringen staan in [`voorbeelden/hypercorrectie/`](voorbeelden/hypercorrectie/).
Het [hypercorrectierapport](voorbeelden/hypercorrectie/hypercorrectie.md) vermeldt de foutaantallen
en metingen van rijkheid en variatie. Het behoud van meetbare kenmerken garandeert niet dat iedere
muzikale keuze overtuigt. De partituren moeten ook op gehoor worden beoordeeld.

## Bekende beperkingen en oplossingen

- **Maatwisselingen binnen één stuk (bijv. 4/4 voorspel → 3/2 koraal → 4/4 naspel)**:
  Wanneer een stuk als één geheel wordt gedraaid, kiest het script één maatsoort voor het hele stuk.
  **Oplossing:** gebruik `--split-sections` (of configureer `splits.json`). Het script knipt het stuk automatisch op
  bij de stiltes, kent per sectie een eigen maatsoort en tempo toe, en plakt ze naadloos aan elkaar met maatwissels.
- **Verzamelvideo's (bijv. "8 Psalmen op Piano", kerstliederen, > 1000 maten)**:
  Bevatten meerdere stukken in verschillende tempi en maatsoorten.
  **Oplossing:** gebruik `splits_compilaties.py "mp3/<compilatie>.mp3" --split`. Dit splitst de opname direct
  op in genummerde losse mp3-tracks in `mp3/`, die vervolgens regulier (en optioneel met `--split-sections`) verwerkt worden.
- Het genoteerde tempo is het gespeelde tempo (uit beat-tracking), niet de metronoomaanduiding uit het boek.
- Akkoorden zijn blokakkoorden; een vierstemmige koraalzetting met liggende binnenstemmen wordt versimpeld
  tot maximaal twee stemmen per balk.
- Voortekens buiten de toonsoort, versieringen en triolen tegen een achtsten-raster blijven een bron van
  kleine fouten; zie `afwijkende_maten` en `raster` in `midi.log` om te zien welke stukken aandacht vragen.

## Controle en weergave

Partituren kunnen direct in **MuseScore 4** geopend worden, of via de command line worden gerenderd naar afbeeldingen om snel visueel te vergelijken:

```bash
# 1. Oorspronkelijke transcriptie (stap 2):
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" -o uit_origineel.png "midi/<stuk>.musicxml"

# 2. Harmonie-controle (stap 4, overtredingen in rood):
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" -o uit_controle.png "midi_controle/<stuk>.musicxml"

# 3. Gecorrigeerde versie (stap 5, gewijzigde noten groen, restfouten rood):
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" -o uit_gecorrigeerd.png "midi_gecorrigeerd/<stuk>.musicxml"
```

MuseScore print op stderr meldingen van de crash reporter; die kunnen genegeerd worden.

## Voorbeelden

In de map [`voorbeelden/`](voorbeelden/) staan vier uitgewerkte stukken:
- **Psalm 85** (inclusief automatische 4/4 → 3/2 → 4/4 sectiesplitsing)
- **Psalm 37** (met automatische 3/4 → 4/4 → 4/4 sectiesplitsing en maatwissels)
- **De Lofzang van Maria** (65 opgeloste parallelle octaven)
- **U zij de glorie** (toonsoortwisselingen en opgeloste leidtoonverdubbelingen)

Elk voorbeeld bevat:
- De gedownloade audio in `voorbeelden/mp3/`
- De ongecorrigeerde MusicXML-partituur in `voorbeelden/ongecorrigeerd/` (stap 2)
- De formele harmoniecontrole in `voorbeelden/controle/` (stap 4, fouten rood gemarkeerd met regelcode, nog vóór herzetting)
- De gecorrigeerde MusicXML-partituur in `voorbeelden/gecorrigeerd/` (stap 5, gewijzigde binnenstemmen groen)
- Een toelichting met de directe link naar de originele YouTube-uitvoering in [`voorbeelden/readmes/`](voorbeelden/readmes/)
