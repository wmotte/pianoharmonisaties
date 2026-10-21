# Opnamen omzetten naar bladmuziek

[Terug naar de README](../README.md) · [Installatie](../README.md#opnamen-omzetten)

Voer de commando's uit vanuit de hoofdmap van de repository, met de transcriptieomgeving in `.venv`.
Hier staan de opties, de berekeningen achter de notatie en oplossingen voor veelvoorkomende problemen.

## Stap 0 – `download_koele.sh`

Dit script downloadt met `yt-dlp` alle video's van het kanaal als mp3.
Het gebruikt de beste audiokwaliteit (`--audio-quality 0`).

Je kunt het opnieuw uitvoeren om nieuwe video's op te halen. Met `--download-archive archive.txt`
houdt het bij welke video's al binnen zijn en slaat het die over.
Een privévideo, verwijderde video of geografische blokkade stopt de overige downloads niet
(`--ignore-errors`). Tussen de verzoeken wacht het script twee tot zes seconden
(`--sleep-interval 2 --max-sleep-interval 6`).

Elke bestandsnaam bevat de uploaddatum, titel en video-id. Zo blijven video's met dezelfde titel
van elkaar te onderscheiden. De uitvoer, inclusief die van `yt-dlp`, staat in `download.log`.
In `videos.txt` staat één regel per video.

## Secties, maatsoorten en toonsoorten

Een voorspel kan een ander tempo of een andere maatsoort hebben dan het koraal dat erop volgt.
Gebruik dan `--split-sections`. Het script verwerkt elk deel afzonderlijk en voegt de delen
samen tot één partituur, met doorlopende maatnummers, maatwissels, dubbele maatstrepen en namen van de delen.

Het script zoekt de grenzen tussen de delen bij stiltes van minstens één seconde.
Je kunt de snijpunten en maatsoorten ook zelf opgeven in `splits.json` of met `--splits` en `--meters`.
Met `--save-parts` bewaar je naast de complete partituur ook de losse audiofragmenten en partituren.
Voor een video met meerdere zelfstandige stukken gebruik je `splits_compilaties.py`.
Dat script zoekt naar langere stiltes om de stukken te scheiden.

Met `--key` of `splits.json` geef je de toonsoort of modus op, bijvoorbeeld `C dorian` voor Psalm 37.
Het programma kiest de nootnamen en voortekens op basis van het akkoord en de toonsoort.
Daarbij houdt het rekening met verhoogde leidtonen.
De velden `syncopen` en `maat_hint` in het logbestand helpen je beoordelen of de ritmische notatie klopt.

## Stap 1+2 – `transcribe_midi.sh` / `transcribe_piano.py`

Dit script verwerkt de mp3-bestanden in twee stappen. Eerst herkent het de gespeelde noten.
Daarna maakt het daar een partituur van met maten, nootwaarden en een verdeling over beide handen.

```bash
./transcribe_midi.sh                         # alle mp3's; bestaande midi/*.musicxml worden overgeslagen
./transcribe_midi.sh --split-sections        # met automatische voorspel/koraal/naspel splitsing en maatwissels
./transcribe_midi.sh --reclean               # alleen stap 2 opnieuw (na een scriptwijziging), ruwe midi hergebruiken
./transcribe_midi.sh --force                 # alles opnieuw, ook de transcriptie
.venv/bin/python transcribe_piano.py --reclean --split-sections --save-parts "mp3/…één stuk….mp3"
```

Met deze opties stuur je de verwerking. De volledige lijst krijg je met `--help`.

| Optie | Standaard | Betekenis |
|---|---|---|
| `--model transkun\|bytedance` | transkun | Kies het model dat de noten herkent (zie stap 1). |
| `--split-sections` | uit | Zoek de delen van het stuk bij stiltes en voeg ze samen met de juiste maatwissels. |
| `--min-silence SEC` | 1.0 | Minimale stilte in seconden om een nieuw deel te beginnen. |
| `--silence-db DB` | 30.0 | Grens voor stilte, in dB onder het hoogste geluidsniveau van de opname. |
| `--splits T1,T2` | | Geef zelf de snijpunten in seconden op, bijvoorbeeld `64.18,144.82`. |
| `--meters M1,M2,M3` | | Geef de maatsoort per deel op, bijvoorbeeld `4,6,4` voor 4/4 → 3/2 → 4/4. |
| `--save-parts` | uit | Bewaar losse mp3's in `mp3_delen/` en losse partituren in `midi_delen/`. |
| `--grid 0\|2\|3\|4` | 0 (auto) | Kies de onderverdeling per tel: 2 voor achtsten, 4 voor zestienden, 3 voor triolen. |
| `--meter 0\|2\|3\|4\|6` | 0 (auto) | Leg de maatsoort vast: 2/4, 3/4, 4/4 of 3/2. Gebruik voor 3/2 de waarde 6. |
| `--key KEY` | | Leg de toonsoort of het aantal voortekens vast, bijvoorbeeld `'C dorian'`, `'g minor'`, `'2b'` of `'-2'`. |
| `--tempo-range MIN MAX` | 60 120 | Geef het toegestane bereik voor het genoteerde tempo op. |
| `--split N` | 60 (C4) | Kies de toonhoogte die als uitgangspunt dient voor de verdeling over de handen. |
| `--leap N` | 7 | Bepaal hoeveel halve tonen een hand buiten zijn eigen register mag komen. |
| `--no-repeats` | | Schakel coupletherkenning en herhalingstekens uit. |
| `--pedal` | | Neem pedaaltekens over uit de herkende uitvoering. |
| `--reclean` / `--force` | | Herhaal alleen het uitschrijven van de partituur, of voer beide stappen opnieuw uit. |

Als een stuk mislukt, schrijft het script `FOUT: …` en de technische foutinformatie (traceback)
naar het logbestand. Daarna gaat het verder met het volgende stuk.
Bij een geslaagd stuk ziet de logregel er bijvoorbeeld zo uit:

```
OK: noten=1708, R=1019, L=689, bpm=92, raster=1/8, maat=4/4, opmaat=0, fermates=8, afwijkende_maten=1, toonsoort=G major -> C major -> F major, couplet=-, 3s
```

### Stap 1 – ruwe transcriptie (audio → noten)

Standaard gebruikt het script Transkun v2 (Yan & Duan 2024), een neuraal model dat pianonoten
in audio herkent. Het roept dat model aan met `transkun --device mps in.mp3 out.mid`.
Op een Mac gebruikt het de grafische processor via MPS, anders de gewone processor.

Met `--model bytedance` kies je het alternatief van ByteDance,
"High-resolution piano transcription" (Kong et al. 2020).
Dit pakket zit niet in `requirements.txt`. Installeer het eerst in de transcriptieomgeving:

```bash
uv pip install --python .venv/bin/python piano_transcription_inference
```

Heb je de omgeving met standaard `venv` en `pip` gemaakt, gebruik dan:

```bash
.venv/bin/python -m pip install piano_transcription_inference
```

Daarna verwerk je de opnamen met `./transcribe_midi.sh --model bytedance`.
De modelgegevens staan in `~/piano_transcription_inference_data/`.

Het resultaat is een MIDI-bestand met per noot een begin- en eindtijd, aanslagsterkte (velocity)
en informatie over het pedaal. Dit is een schatting van wat er gespeeld wordt.
Er staan nog geen maten in. Vertragingen, kleine verschillen tussen gelijktijdig bedoelde
aanslagen en doorklinkende pedaalnoten zijn nog onderdeel van de timing.
Stap 2 zet die uitvoering om naar leesbare notatie.

### Stap 2 – opschonen (noten → partituur)

Het script plaatst de herkende noten op vaste tellen en kiest passende nootwaarden.
Het schrijft de rechterhand op een balk met vioolsleutel en de linkerhand op een balk met bassleutel.
Gelijktijdige aanslagen worden blokakkoorden. Waar de speler een toon langer aanhoudt,
kan een fermate komen. Sleutelwissels, octaaflijnen (8va) en dynamiektekens maken de partituur verder leesbaar.

Hieronder staat hoe het script die keuzes maakt, met de bijbehorende instellingen en grenswaarden.

#### 2a. Tijdraster

Eerst zoekt `librosa.beat.beat_track` de tellen in de audio. Het script gebruikt die tijdstippen
om ook bij vertragingen en versnellingen de noten op een regelmatig notatieraster te plaatsen.

Soms herkent de teller de halve of dubbele puls. Valt het gevonden tempo buiten `--tempo-range`
(standaard 60–120), dan laat het script om de andere tel weg of voegt het tussentellen in.
Bij het weglaten kiest het de reeks tellen waarop de meeste aanslagen vallen.
Het trekt het raster ook door tot vóór de eerste en na de laatste gevonden tel.

Als de gevonden tellen steeds iets voor of achter de aanslagen liggen, verschuift het hele raster.
De berekening gebruikt daarvoor het circulaire gemiddelde van de aanslagposities binnen een tel.

Bij automatische rasterkeuze (`--grid 0`) gebruikt het script achtsten.
Het kiest pas zestienden of triolen als minstens een kwart van de aanslagen daar duidelijk beter op past.
Zo worden kleine timingverschillen niet meteen als korte nootwaarden uitgeschreven.
Bij een raster met zestienden schuiven losse aanslagen zonder buuraanslag een zestiende verderop
alsnog naar de dichtstbijzijnde achtste. Het script behandelt die als timingfouten.

Noten met een aanslagsterkte onder 15 laat het script weg als vermoedelijke herkenningsruis.

#### 2b. Handverdeling

Het model herkent toonhoogtes, maar weet niet welke hand de noten speelt.
Het script verdeelt ze daarom op basis van hun hoogte en de omliggende passage.

`local_split` zoekt eerst een grens tussen het lage en hoge register.
Daarvoor groepeert het de noten van acht tellen vóór tot acht tellen na het moment in twee groepen
(2-means-clustering). Liggen de groepen minstens tien halve tonen uit elkaar, dan komt de grens ertussen,
binnen het bereik C3–C5. Liggen alle noten in één register, dan gaan ze naar de hand die daarbij past.
Zo kan de grens meeschuiven met een laag voorspel of een hoge passage.

Vervolgens verdeelt `assign_hands` de noten die tegelijk beginnen.
Het zoekt de grootste opening tussen de toonhoogtes en controleert of de verdeling speelbaar is:

- Elke hand krijgt hoogstens veertien halve tonen om te overbruggen, ongeveer een none.
- De opening tussen de groepen is minstens drie halve tonen.
- De lage groep moet qua gemiddelde toonhoogte bij de linkerhand passen en de hoge bij de rechterhand.
- De handen mogen binnen de ingestelde reikwijdte (`--leap`) over de grens komen.
  Bij de standaardwaarde 7 reikt links van A3 tot E4 en rechts van E4 tot A3.
  Als de lokale grens verder ligt, volgt de reikwijdte die grens.

Past een compact akkoord binnen één handspanning maar is er geen geschikte splitsing,
dan gaat het hele akkoord naar één hand.

Tot slot kijkt `rebalance` of een hand onnodig stil blijft.
Lage noten van een rechterhandakkoord, tot en met E4, kunnen dan naar links verhuizen.
Hoge noten van links, vanaf A3, kunnen naar rechts.
Een losse aangehouden noot verhuist alleen als dezelfde hand daaroverheen een nieuwe aanslag speelt.

#### 2c. Noten → leesbare groepen per hand (`build_groups`)

Het script verwijdert eerst vermoedelijke spooknoten binnen akkoorden.
Dat zijn noten met minder dan 30% van de aanslagsterkte van de hardste noot, of met een
aanslagsterkte onder 20. Vaak heeft het model daar een boventoon als aparte noot herkend.

Noten van één aanslag krijgen dezelfde duur, op basis van de middelste waarde van hun lengtes
(de mediaan). Vanaf een halve tel rondt het script af op halve tellen. Daarna kiest het een
noteerbare lengte uit de reeks `NICE`: 1, 2, 3, 4, 6, 8, … rastereenheden.

Een aanslag loopt in principe door tot de volgende aanslag van dezelfde hand.
Het script kort overlappende pedaalnoten in en sluit gaten korter dan een tel,
zodat de notatie legato wordt. Rusten van een tel of meer blijven staan.

Per hand mag één noot langer doorklinken: een bas onder de linkerhand of een melodienoot boven
de rechterhand. Alle tussenliggende aanslagen moeten boven die bas of onder die melodienoot liggen.
De aangehouden noot moet bovendien minstens een tel langer duren dan het gat tot de volgende aanslag.
Zo ontstaan maximaal twee stemmen per balk.

#### 2d. Maatsoort, maatstrepen, opmaat, fermates

`detect_meter` zoekt de sterke tellen aan de hand van het aantal aanslagen, de nootlengtes en
akkoordwisselingen. Die wisselingen wegen dubbel, omdat ze een goede aanwijzing voor de eerste tel zijn.
Technisch meet het script de harmonische verandering als de cosinusafstand tussen chroma-vectoren:
overzichten van de aanwezige toonklassen op opeenvolgende tellen.

Daarna zoekt het naar een terugkerend accentpatroon met autocorrelatie.
Is de herhaling na drie en zes tellen sterker dan na vier en acht, dan kiest het 3/4.
Anders kiest het 4/4. Het kiest 2/4 en 3/2 niet automatisch, omdat die zo niet betrouwbaar te
onderscheiden zijn. Gebruik daarvoor `--meter 2` of `--meter 6`.
Verschijnt `maat_hint=3/2` in de log, dan keert het patroon wel na zes maar niet na drie tellen terug.
Dat is een reden om `--meter 6` te proberen.

`track_bars` plaatst vervolgens de maatstrepen met Viterbi-tracking.
Normaal bevat een maat het aantal tellen van de gekozen maatsoort, hier *m* genoemd.
Een maat mag bij de berekening ook *m* + 1 of *m* − 1 tellen krijgen, met een strafwaarde van 2,5.
Zo verschuift niet de rest van het stuk als de teller bij een fermate één tel te veel of te weinig vindt.
Noten vóór de eerste volledige maat komen in een opmaat, waarin de maatsoort al wordt getoond.

`normalise_bars` beoordeelt de afwijkende maten.
Eindigt zo'n maat met alleen een aangehouden noot of rust, dan past het script de duur aan
tot de gewone maatlengte. De aangehouden noot krijgt een fermate.
Wordt er tot het einde doorgespeeld, dan blijft de afwijkende maatsoort, bijvoorbeeld 5/4, staan.
Het veld `afwijkende_maten` in de log telt die gevallen. Daarmee vind je stukken die je zelf moet nalopen.

#### 2e. Coupletten (`find_verses`)

`find_verses` vergelijkt per maat welke toonklassen klinken en hoe lang ze duren.
Komt een blok van minstens acht maten twee of meer keer achter elkaar vrijwel gelijk terug,
dan schrijft het programma het één keer uit met herhalingstekens (`|: :|`) en het aantal herhalingen.
De grens voor overeenkomst is een cosinus-gelijkenis van minstens 0,92.

Met `--no-repeats` schakel je deze herkenning uit. In de MIDI staan alle herhalingen altijd uitgeschreven.

#### 2f. Partituur (`build_score`, music21)

`build_score` maakt met de bibliotheek music21 één pianopartituur met twee balken en een accolade.
In de code zijn dat twee `PartStaff`s in één `StaffGroup`.
De eerste maat krijgt een tempo-aanduiding (♩ = bpm). Bij elke verandering van maatlengte
komt de bijbehorende maatsoort te staan.

**Toonsoort en voortekens.** `key_segments` schat de toonsoort per maat op basis van de zes maten
ervoor en erna. Het gebruikt de Krumhansl-Schmuckler-methode: het telt hoe lang elke toonklasse klinkt
en vergelijkt die verdeling met 24 toonsoortprofielen. Een gevonden toonsoort die minder dan
zestien maten aanhoudt, wordt bij het langste aangrenzende deel gevoegd.
Dit voorkomt dat korte afwijkingen meteen een nieuwe voortekening krijgen.
Een reeks toonsoorten staat in de log als `toonsoort=G major -> C major -> F major`.
Deze aanpak voorkomt bijvoorbeeld dat 'U zij de glorie' in C wordt genoteerd met 68 losse kruisen voor F#.

`spell_vertical` kiest daarna per samenklank de nootnamen.
Het probeert eerst een akkoord als stapeling van tertsen te schrijven, bijvoorbeeld B-D#-F#.
De grondtoon krijgt de spelling die zo min mogelijk voortekens nodig heeft en het dichtst bij de
geldende voortekening ligt. Lukt die akkoordspelling niet, dan volgt het de toonsoort.
Bij twee noten kijkt het naar het interval en geeft het een terts voorrang boven een sext,
bijvoorbeeld B-D# boven Eb-B. In mineur schrijft het de verhoogde zesde en zevende trap
met een kruis, zoals D# voor een leidtoon. `makeAccidentals` zet de voortekens per maat.

**Stemmen en rusten.** `makeVoices`, `makeMeasures` en `makeTies` verdelen de muziek in stemmen
en maten en plaatsen bindingen. Heeft een maat maar één stem, dan vervalt de aparte stemindeling.
Waar nodig vult het script een stem met rusten aan tot een volledige maat.
Het splitst rusten op de telgrenzen en vermijdt dubbelgepunteerde rusten.
Onzichtbare rusten uit de MusicXML-export verwijdert het, zodat ze niet als grijze balkjes in MuseScore verschijnen.

**Sleutels en octaaflijnen.** Het script telt per maat hoeveel hulplijnen elke sleutel nodig zou hebben,
ongeveer één per 3,5 halve toon buiten de balk. Heeft de andere sleutel minstens twee maten achter
elkaar duidelijk minder hulplijnen nodig, dan wisselt het van sleutel.
Zo kan de linkerhand in een hoog voorspel tijdelijk een vioolsleutel krijgen.

Voor de rechterhand kiest het script een 8va-lijn als de hoogste noot minstens C6 is en een octaaf
lager noteren duidelijk hulplijnen bespaart. Aangrenzende maten delen één lijn.
In MusicXML staan de noten een octaaf lager met een `octave-shift`, zodat MuseScore ze op de juiste hoogte afspeelt.

**Fermates.** De noot waarvan `normalise_bars` de duur heeft aangepast, krijgt een fermate.
Bij gebonden noten staat die op het laatste deel. Het slotakkoord wordt verlengd tot het einde
van de maat en krijgt altijd een fermate.

**Dynamiek.** Het script leidt de dynamiek af uit de gemiddelde aanslagsterkte per maat.
Het middelt die over vier maten vooruit, zodat niet elke kleine verandering een nieuw teken geeft.
De middelste aanslagsterkte van het stuk geldt als mf. Elke tien punten verschil geeft één stap
in de reeks pp, p, mp, mf, f, ff. Een nieuw teken verschijnt bij minstens twee stappen verschil
na minstens twee maten, of bij één stap verschil na minstens acht maten.

**Pedaal.** Met `--pedal` neemt het script de pedaalinformatie (CC64) uit de ruwe MIDI over
als lijnen onder de linkerhand. Het past de tijdstippen aan het raster en de gewijzigde fermateduren aan.
Deze optie staat standaard uit. De genoteerde noten zijn al ingekort, ook waar de opname ze met pedaal laat doorklinken.

Open voor de bladmuziek het `.musicxml`-bestand in `midi/`.
Het `.mid`-bestand bevat dezelfde opgeschoonde noten in één spoor, met het aangepaste tempo.
MuseScore kan die opnieuw over twee balken verdelen, maar de hierboven beschreven notatiekeuzes
staan alleen in MusicXML.

## Stap 3 – `analyse_stijl.py` (stijlanalyse)

```bash
.venv/bin/python analyse_stijl.py        # leest midi/*.musicxml + midi_raw/*.transkun.mid, schrijft stijlanalyse.json (~2 min)
```

`analyse_stijl.py` onderzoekt de harmonie, vorm en speelwijze van de stukken.
Het bepaalt per maat de toonsoort en zoekt per tel het best passende akkoord uit vijftien akkoordtypen.
Daarbij noteert het ook de harmonische trap in Romeinse cijfers en de ligging van het akkoord.

Het script onderscheidt voorspel, koraal, tussenspel en naspel aan de hand van terugkerende melodieën.
Een passage geldt als couplet als haar reeks melodische intervallen minstens 32 tellen later
bijna letterlijk terugkomt. Per deel verzamelt het gegevens over de opbouw van de begeleiding,
de toonhoogte, dynamiek en akkoorden. Ook slotwendingen bij fermates, basbewegingen,
orgelpunten en octaafverdubbelingen worden gemeten.

Uit de ruwe MIDI haalt het daarnaast informatie over pedaalgebruik, legato, gebroken akkoorden
en vertraging aan het slot. Stukken uit verzamelvideo's tellen niet mee in de statistiek over de vorm.
De uitleg van de resultaten staat in [stijlanalyse.md](../stijlanalyse.md).
Paragraaf 0 van dat bestand beschrijft welke metingen betrouwbaar zijn en waar voorzichtigheid nodig is.

## De stijlanalyse lezen

De [stijlanalyse](../stijlanalyse.md) bevat een actualisatie over de beperkingen van de oude metingen.
De vormpercentages zijn historische beschrijvingen en zijn niet volledig reproduceerbaar uit
de huidige conversies. Ook zegt het aantal noten in één aanslag niet hoeveel stemmen er klinken:
een eerder aangeslagen noot kan nog doorklinken. Gebruik de oude cijfers daarom niet als vaste
regels voor een nieuwe begeleiding.

## Bekende beperkingen en oplossingen

### Een stuk met verschillende maatsoorten

Verwerk je een stuk als één geheel, dan kiest het script één maatsoort.
Bij een opbouw als 4/4-voorspel, 3/2-koraal en 4/4-naspel gaat dat mis.
Gebruik `--split-sections` of stel de delen in via `splits.json`.
Het script bepaalt dan per deel het tempo en de maatsoort en voegt de delen samen met maatwissels.

### Een video met meerdere stukken

Verzamelvideo's zoals "8 Psalmen op Piano" en verzamelingen kerstliederen bevatten meerdere stukken,
vaak met verschillende tempi en maatsoorten. Als één partituur kunnen ze meer dan duizend maten beslaan.
Splits zo'n opname eerst met `splits_compilaties.py "mp3/<compilatie>.mp3" --split`.
Dat schrijft genummerde mp3-bestanden naar `mp3/`.
Daarna verwerk je elk bestand op de gewone manier, eventueel met `--split-sections`.

### Notatie die je zelf moet nalopen

Het genoteerde tempo komt uit de uitvoering. Het hoeft dus niet overeen te komen met
de metronoomaanduiding in een liedboek.

Het script schrijft akkoorden als blokakkoorden en gebruikt maximaal twee stemmen per balk.
Een vierstemmige koraalzetting met afzonderlijk aangehouden binnenstemmen kan daardoor worden vereenvoudigd.
Voortekens buiten de toonsoort en versieringen kunnen kleine fouten opleveren.
Hetzelfde geldt voor triolen als het gekozen raster alleen achtsten bevat.
Bekijk de velden `afwijkende_maten` en `raster` in `midi.log` om stukken te vinden die aandacht nodig hebben.

## Controle en weergave

Open de MusicXML-bestanden in MuseScore 4 om ze te bekijken en af te spelen.
Je kunt met de onderstaande commando's ook afbeeldingen maken.
Zo vergelijk je de oorspronkelijke partituur met de controle en de gecorrigeerde versie:

```bash
# 1. Oorspronkelijke transcriptie (stap 2):
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" -o uit_origineel.png "midi/<stuk>.musicxml"

# 2. Harmonie-controle (stap 4, overtredingen in rood):
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" -o uit_controle.png "midi_controle/<stuk>.musicxml"

# 3. Gecorrigeerde versie (stap 5, gewijzigde noten groen, restfouten rood):
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" -o uit_gecorrigeerd.png "midi_gecorrigeerd/<stuk>.musicxml"
```

MuseScore kan hierbij meldingen van de crash reporter naar de foutuitvoer (`stderr`) schrijven.
Die meldingen kun je negeren.

## Installatie met standaard pip

De [README](../README.md#opnamen-omzetten) gebruikt uv. Met een geïnstalleerde Python 3.12
kun je de transcriptieomgeving ook zo maken:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

`transcribe_midi.sh` gebruikt altijd de Python in `.venv`. De harmoniser uit de README
heeft een aparte omgeving, `.venv-harmonisatie`.
