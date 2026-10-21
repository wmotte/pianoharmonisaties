# De signatuur van Gerrit Koele: voorspel, koraal, tussenspel en naspel

Deze beschrijving karakteriseert het ontwerp en de harmonisatie van Gerrit Koeles pianobewerkingen.
Ze is gebaseerd op een automatische analyse van de 49 openbare YouTube-opnamen (40 losse liederen en
psalmen en 9 compilaties, samen ruim 5 uur muziek) met `analyse_stijl.py`. De kwalitatieve duiding is
gecontroleerd aan de hand van MuseScore-weergaven van onder meer Psalm 85, Psalm 73,
‘Mijn Jezus, ik hou van U’, ‘I need Thee every hour’ en ‘U zij de glorie’.

De cijfers beschrijven een transcriptie van een uitvoering, niet een gedrukte uitgave. Ze geven aan
wat in dit spel gebruikelijk is en wat zeldzaam; ze zijn geen voorschrift voor een nieuwe begeleiding.
[Paragraaf 0](#0-methode-en-betrouwbaarheid) geeft aan welke metingen betrouwbaar zijn en waar
voorzichtigheid past.

## 0. Methode en betrouwbaarheid

| Vraag | Middel |
|---|---|
| Akkoorden, trappen, liggingen, cadensen, modulaties | music21: chordify per tel, sjabloonherkenning op 15 akkoordtypen, Romeinse trappen ten opzichte van de per maat bepaalde toonsoort |
| Vormdelen (voorspel, koraal, tussenspel, naspel) | expliciete sectiegrenzen uit `splits.json` waar die zijn opgegeven; anders melodische herhaling: een couplet is een passage waarvan de melodische intervalreeks minstens 32 tellen verderop vrijwel letterlijk terugkomt, en wat niet herhaalt is voor-, tussen- of naspel |
| Pedaal, legato, gebroken akkoorden, aanslagsterkte | pretty_midi op de ruwe Transkun-MIDI met pedaalinformatie (CC64), vóór alle opschoning |
| Ritenuto aan het slot | de tijd tussen de laatste zes aanslagen, vergeleken met de mediaan van het stuk |
| Controle van beweringen | MuseScore 4-weergaven van uitgekozen maten |

Gespecialiseerde harmonische analyseprogramma’s (DCML/ms3, Melisma, Humdrum) zouden de trapaanduidingen
iets consistenter maken, maar voegen op dit materiaal weinig toe. De harmonie is overwegend diatonisch en
drieklankgebaseerd; de grootste foutbron is de audiotranscriptie zelf, niet de labeling.

**Wat betrouwbaar is en wat niet**

- *Zeer betrouwbaar*: de globale akkoordvocabulaire, de trapverdeling, ligging, basbeweging, pedaalgebruik,
  toonsoortkeuze, begin- en slotgedrag en de modulaties (met de hand gecontroleerd in weergaven).
- *Redelijk betrouwbaar*: de vormdelen. De automatische indeling is voor 18 van de 40 losse stukken
  schoon (voorspel, één tot drie coupletten met tussenspelen, naspel). Deze 18 vormen de basis voor de
  uitspraken per vormdeel. Bij de overige stukken is de vorm gefragmenteerd, vaak omdat het koraal er
  vrij wordt bespeeld of omdat de transcriptie de melodie in dichte akkoorden niet consequent bovenaan zet.
  Voor Psalm 37 en Psalm 85 zijn de grenzen met de hand vastgelegd; voor de overige stukken zijn
  de gevonden grenzen schattingen.
- *Met een korrel zout*: de categorie `aug` (3,5% van alle akkoorden) is grotendeels een artefact van
  doorgangsnoten op akkoordwissels; het aandeel `sus2` en `add9` is eerder een onder- dan een
  overschatting, omdat deze kleuren soms in de opschoning verdwijnen; melodiecitaten in het voorspel worden
  onderschat omdat de bovenstem daar versierd is.
- *Aantal stemmen*: de metingen tellen noten per aanslag. Een aanslag met drie noten bewijst geen
  driestemmige zetting, want een eerder aangeslagen stem kan nog doorklinken. Uitspraken over
  ‘dunne’ of ‘volle’ zetting gaan over aanslagen, niet over het aantal zelfstandige stemmen.
- *Tempo en maatsoort*: de getallen in paragraaf 1 zijn per stuk gemeten op het begin van de opname.
  Binnen een stuk kunnen voorspel, koraal en naspel een eigen tempo en maatsoort hebben; zie paragraaf 2.

## 1. Globaal profiel

| Kenmerk | Bevinding |
|---|---|
| Lengte los stuk | mediaan 98 maten, ongeveer 4 minuten (2:18 tot 13:30) |
| Begintempo | mediaan 86 kwartnoten per minuut; sectietempo’s binnen een stuk kunnen afwijken |
| Beginmaatsoort | 4/4 (33 keer), 3/4 (16 keer); binnen stukken komen ook 3/2 en maatwisselingen voor |
| Toonsoort | C, D, G, F, g, e, d, Bes, A, c, a: nooit meer dan 3 voortekens, driekwart van de tijd 0 tot 2 |
| Modus | 80% majeur, 20% mineur (Geneefse psalmen: modaal, aeolisch) |
| Modulatie | de helft van de losse stukken moduleert minstens één keer (zie paragraaf 7) |
| Aanslag | gemiddeld ongeveer 70 (MIDI-velocity) met kleine spreiding (σ ≈ 14): een gelijkmatige, niet-virtuoze mf |
| Pedaal | 89% van de tijd ingedrukt, ongeveer 30 wissels per minuut, dus ongeveer één wissel per akkoordwissel |
| Gebroken akkoorden | 9% van de akkoorden wordt gebroken (arpeggio); nooit het slotakkoord |
| Fermates | mediaan 3,6 per 100 maten, vrijwel alleen op regeleinden van het koraal; in het voorspel af en toe een adempauze aan een frase-einde (in 13 van de 27 voorspelen), maar nooit als afsluiting van het voorspel |
| 8va | 41 van de 49 opnamen reiken tot c''' of hoger (hoogste noot mediaan d'''), bijna altijd in voor- of naspel |

## 2. Het ontwerp (vorm)

Het vaste model, in alle 18 schoon gedetecteerde stukken:

```
VOORSPEL  →  KORAAL (couplet 1)  →  TUSSENSPEL  →  KORAAL (couplet 2)  →  NASPEL
 ~33 %           ~21 %               ~9 %             (idem)               ~20 %
```

- **Aantal coupletten**: mediaan 2 (1 tot 3). Bij psalmen vrijwel altijd 2, bij Engelse hymns 1 of 2, bij
  kerstliederen soms 3. In de lange compilatievideo’s volgen series liederen elkaar op, elk met eigen
  voor- en naspel.
- **Verhouding**: het voorspel is het grootste onderdeel (mediaan 29 maten, 10 tot 65; in tijd mediaan
  ongeveer 70 seconden, 30 seconden tot 4 minuten). Het naspel is lang: mediaan 17,5 maten (7 tot 42),
  vaak even lang als een couplet.
- **Tussenspel**: kort (mediaan 13 maten) en soms afwezig; couplet 2 volgt dan direct na de fermate.
- **Wat nooit voorkomt**: het koraal zonder omlijsting; meer dan drie coupletten; eindigen met de laatste
  koraalregel. Er komt altijd een naspel, hoe kort ook (minimaal ongeveer 7 maten).

De vormdelen kunnen elk een eigen maatsoort en tempo hebben. Twee stukken zijn met de hand in delen
gesplitst en met afzonderlijke maatsoorten getranscribeerd:

| Stuk | Voorspel | Koraal | Naspel |
|---|---|---|---|
| Psalm 37 | 3/4, ♩ = 66 | 4/4, ♩ = 112 | 4/4, ♩ = 108 |
| Psalm 85 | 4/4, ♩ = 83 | 3/2, ♩ = 108 | 4/4, ♩ = 86 |

Het tempo is steeds omgerekend naar kwartnoten per minuut. In 3/2 komt ♩ = 108 overeen met 𝅗𝅥 = 54;
een hoger getal betekent dus niet zonder meer een sneller ervaren puls.

## 3. Voorspel

Getallen: 18 voorspelen, mediaan 29 maten.

**Karakter.** Het voorspel is een vrije fantasie over motieven van het koraal, geen letterlijke
doorspeling van de melodie. Het langste melodiefragment dat exact terugkomt is meestal 4 tot 7 noten.
Slechts in 3 van de 21 stukken opent het voorspel letterlijk met de kop van het koraal (Psalm 85,
‘Amazing grace’, ‘Mijn Jezus’). In twee stukken (‘Mijn Jezus’ en ‘Wij trekken in een lange stoet’)
wordt een hele regel geciteerd (12 intervallen).

**Textuur.**
- Beweeglijker dan de rest: 57% van de tellen bevat achtsten (koraal 42%, naspel 30%).
- Dunne aanslag: de rechterhand slaat gemiddeld 1,4 noten tegelijk aan, de linkerhand 1,1. Het beeld is
  overwegend twee- tot driestemmig: een zingende bovenstem, één middenstem en een baslijn.
- Opening: bijna altijd een eenstemmige melodie in de rechterhand (mediaan van de rechterhandaanslag in
  de eerste 4 maten: 1,26 noten) boven een liggende of langzaam lopende bas; de harmonie wordt pas na
  enkele maten gevuld.
- Register: hoogste noot mediaan b'' (83), bovenstem gemiddeld rond a' (70). Bas gemiddeld rond dis (51),
  laagste noot C (36). Het voorspel is het deel dat het hoogst reikt; hier zitten de meeste 8va’s.
- Dynamiek: mp tot mf, iets zachter dan het koraal (velocity 78,6 tegen 80,1). De eerste 6 seconden
  liggen gemiddeld ongeveer 5 punten onder het gemiddelde van het stuk: het voorspel begint zacht en groeit.

**Harmonie.** Dezelfde vocabulaire als het koraal (zie paragraaf 6), maar met meer sus-akkoorden
(16% sus4 en sus2 tegen 10% in het koraal) en meer maj7- en add9-kleuring. De harmonische puls is
2 akkoordwissels per maat. Typische openingen: I → IV(7) → I, I → Isus → I, I → II → …, in mineur i → VII → …

**Slot van het voorspel.** In 17 van de 18 gevallen géén fermate: het voorspel loopt op een
dominantspanning het koraal in. De meest voorkomende laatste twee akkoorden zijn Vsus4 → I (3 keer),
Isus → I (2 keer), V7 → I en III → I. Het voorspel eindigt dus op een vaak opgehouden dominant die
direct in het eerste akkoord van het koraal oplost, zonder pauze.

## 4. Hoofdspel: het koraal

Getallen: 31 coupletten in 18 stukken.

**Melodie altijd bovenaan.** De melodie ligt in de bovenstem van de rechterhand, in kwartnoten of halven.
Ze verhuist niet naar de tenor of bas. Het bereik van de bovenstem in het koraal is laag: gemiddeld rond
gis' (68), hoogste noot mediaan g'' (79). Het koraal staat dus in de normale zangligging, niet een octaaf hoger.

**Zetting.**
- Rechterhand: melodie plus één noot (gemiddeld 1,5 noten per aanslag); linkerhand bijna uitsluitend één
  basnoot (1,05). Dit zegt iets over de aanslag, niet over het aantal doorklinkende stemmen. Volle
  aanslagen van vier of meer noten zijn de uitzondering en vallen op regelbegin of regeleinde.
- Linkerhandoctaven: 16% van de basaanslagen (0 tot 67% per stuk), vooral in het laatste couplet en het
  naspel, om zwaarte te geven.
- Bij Geneefse psalmen (Psalm 1, 25, 37, 49, 73, 85) is het koraal ritmisch strikt: 0 tot 3% achtsten, de
  linkerhand speelt per tel. Bij hymns en kerstliederen zit 40 tot 70% achtsten: daar loopt de linkerhand
  door onder de lange melodienoten, met gebroken akkoorden en stapsgewijze baslijnen.
- Harmonische puls: 2 wissels per maat (4/4: op 1 en 3; 3/4: op 1 en 3 of 1 en 2).

**Regeleinden.** Elke koraalregel eindigt op een fermate (mediaan 4 tot 6 per couplet bij psalmen, 1 tot 3
bij hymns). De cadensen op fermates, gemeten als de laatste twee akkoorden vóór de fermate
(n = 328 gelabelde cadensen op 408 fermates), verdelen zich als volgt:

| Cadens op fermate | majeur | mineur |
|---|---|---|
| V → I (authentiek) | 11% | – |
| I → V (halfslot) | 9% | i → V 9% |
| IV → I (plagaal) | 7% | – |
| II → V, II → I (V/V, ii) | 6% | – |
| V → VI (bedrieglijk) | 3% | – |
| VII → i (subtonica, aeolisch) | – | 6% |
| VI → V, i → VI | – | 4% + 4% |
| overig (III → I, IV → bVII, i → VI in majeur, …) | ~64% | ~77% |

De belangrijkste uitkomst is de spreiding: geen enkele cadensformule domineert. De standaard V7 → I op
elke regel wordt vermeden; authentieke, plagale, halve en bedrieglijke slotwendingen wisselen elkaar af,
en in mineur komen de modale VII → i en VI → V veel voor. Bijna altijd (73%) staat het slotakkoord van
een regel in grondligging.

**Tweede couplet.** In de 12 stukken met twee coupletten:
- Bij de psalmen zijn couplet 1 en 2 vrijwel identiek gezet, met dezelfde aanslag, hetzelfde register en
  dezelfde akkoordgrootte (Psalm 1: 81/66/2,0 tegen 81/66/2,0). Variatie zit daar niet in de zetting,
  maar in de toonsoort (zie paragraaf 7) of in de linkerhand (octaven).
- Bij hymns verandert de zetting wel. In ‘I need Thee’ is couplet 2 stiller en dunner (velocity 69 → 67,
  akkoordgrootte 2,1 → 1,1, achtsten 71% → 25%). In ‘Great is thy faithfulness’ is couplet 2 voller
  (1,8 → 2,0) maar rustiger (60% → 28% achtsten) en ligt het hoger. In ‘Stille nacht’ is couplet 2
  zachter (82 → 75) en rustiger (53% → 16%). Het patroon: het tweede couplet is meestal rustiger, niet
  luider. De climax ligt niet in het laatste couplet, maar in het voorspel of tussenspel en aan het begin
  van het naspel.
- Een couplet wordt niet grondig geherharmoniseerd; de trapopeenvolgingen van couplet 1 en 2 overlappen sterk.

## 5. Tussenspel

Getallen: 13 tussenspelen, mediaan 13 maten (5 tot 74).

- Sluit direct aan op de laatste fermate van het couplet en pikt vaak het laatste motief op.
- Textuur en dynamiek liggen tussen voorspel en koraal in (49% achtsten, velocity 79, akkoordgrootte 1,9).
- Harmonisch het meest avontuurlijke deel: hier zitten de meeste I → III-wendingen (V/vi), het meeste
  gebruik van #IV en bVI, en de modulaties (paragraaf 7) vallen bijna altijd in het tussenspel of aan het
  begin van het naspel.
- Eindigt op dezelfde manier als het voorspel: zonder fermate (10 van de 13), op V, Vsus4 of I, als
  inleiding van het volgende couplet.

## 6. Harmonisatie: de vocabulaire

Over alle 49 opnamen (ongeveer 14 000 akkoordlabels per tel):

**Akkoordtypen**

| Type | Aandeel | Opmerking |
|---|---|---|
| majeurdrieklank | 48% | |
| mineurdrieklank | 17% | |
| **sus4** | **10,6%** | in elk stuk 2 tot 17%; het meest herkenbare kleurmiddel |
| sus2 | 5,4% | vooral op I en IV |
| maj7 | 3,9% | vooral IVmaj7, in mineur VImaj7 |
| dom7 | **3,0%** | opvallend weinig: slechts 8% van alle V-akkoorden in majeur is V7 |
| min7 | 2,8% | ii7, vi7 |
| add9 | 2,4% | Iadd9, IVadd9, bVIIadd9 |
| dim | 1,2% | viiº als doorgang |
| maj6, madd9 | ~1% | |
| m7♭5, min6, dim7 | < 0,3% | praktisch afwezig |

**Trappen in majeur (40 losse stukken)**, met de kwaliteit die het vaakst op die trap staat:

| Trap | Aandeel | Kwaliteit |
|---|---|---|
| I | 30% | 76% zuiver, 7% sus2, 6% sus4, 4% add9 |
| V | 16% | 55% zuiver, **21% sus4**, 8% dom7 |
| IV | 13% | 66% zuiver, 10% maj7, 9% sus2, 6% add9 |
| III | 10% | 34% iii, **23% III (= V/vi)**, rest doorgang |
| II | 9% | 39% ii, 12% ii7, **18% II (= V/V)** |
| VI | 9% | 55% vi, 15% VI (= V/ii) |
| VII | 3% | viiº of doorgang |
| bVII | 2,6% | majeur (mixolydisch of modaal leenakkoord), vaak als add9 |
| bIII, bVI, i | ~1 tot 2,6% | leenakkoorden uit de gelijknamige mineur |

**Trappen in mineur (Geneefse psalmen en andere)**

| Trap | Aandeel | Kwaliteit |
|---|---|---|
| i | 27% | 54% mineur, **23% majeur** (tonicamajeur of picardische terts op regeleinden) |
| V | 19% | 34% majeur, **26% mineur (v, aeolisch)**, 20% sus4 |
| VI | 14% | 51% majeur, **24% maj7** |
| VII | 9% | 67% majeur (subtonica, geen leidtoon) |
| iv | 9% | |
| III | 6% | majeur (relatieve majeur) |
| ii | 4% | iiº of ii |

**Wat dit betekent**

1. **Diatonisch en drieklankig.** 65% van alle akkoorden is een zuivere drieklank; septiemakkoorden
   van alle soorten samen blijven onder 13%. Verminderde septiem-, halfverminderde en chromatisch
   veranderde akkoorden komen niet voor. Geen jazzvoicings, geen gospeldominanten.
2. **De sus4 als handtekening.** Eén op de vijf dominanten is Vsus4, en de progressies Isus4 → I,
   Vsus4 → I en Vsus4 → V staan alle drie in de top 10 van akkoordopeenvolgingen. De kwart wordt
   opgehouden (vaak de melodienoot of de voorgaande basnoot) en lost pas laat of helemaal niet op.
   Die klank doet eerder aan Engelse hymn- en worshippiano denken dan aan een Bachkoraal.
3. **Secundaire dominanten, maar mild.** II (V/V) en III (V/vi) komen regelmatig voor (samen ongeveer 4%
   van alle akkoorden in majeur), meestal als zuivere majeurdrieklank, niet als septiemakkoord, en bijna
   altijd in het tussenspel of op de voorlaatste regel.
4. **Modaal in mineur.** In de psalmen in mineur komen de mineurdominant (v) en de majeursubtonica (VII)
   vaker voor dan de leidtoondominant (V-majeur). Daarmee blijft het dorische of aeolische karakter van
   de Geneefse melodieën behouden. Regeleinden en het slot krijgen vaak wél de picardische terts.
5. **Leenakkoorden uit mineur in majeur**: bVII (2,6%), bIII, bVI, als kleur, meestal in add9- of
   sus2-vorm en vaak vlak vóór het slot (‘Amazing grace’ eindigt bVII → I; ‘U zij de glorie’ I → bVII → I).
6. **Ligging: bijna alles in grondligging.** 74% grondligging, 12% kwartsextakkoord (vooral het
   cadenserende I6/4 → V), 9% sextakkoord. De bas is een grondtoonbas, geen lopende koraalbas.
7. **Basbeweging.** 45% sprongen (kwart of kwint), 30% liggend (de bas herhaalt of blijft), 14% stapsgewijs,
   10,5% octaafsprong. Orgelpunten: mediaan 5,5 per 100 maten (in sommige stukken 10 tot 15). Een
   liggende tonica of dominant onder wisselende akkoorden is een vast onderdeel van voor- en naspel.

**Meest voorkomende progressies (alle vormdelen)**: V → I, I → IV, I → V, Isus → I, IV → I, I → Isus,
I → III, Vsus → I, I → Vsus, Vsus → V, V → VI, VI → V, II → V, I → II. De kern is I–IV–V met
sus-versieringen, aangevuld met V/vi en V/V.

## 7. Modulaties

20 van de 40 losse stukken bevatten minstens één toonsoortwisseling (11 keer één, 6 keer twee, 3 keer
drie of meer). De modulaties liggen bijna altijd op de grens tussenspel → couplet of couplet → naspel.
Intervallen, gecontroleerd in weergaven van onder meer ‘I need Thee’ (F → D → G) en ‘U zij de glorie’
(G → C → F):

| Richting | Aantal | Voorbeeld |
|---|---|---|
| **kwart omhoog (naar de subdominant)** | 10 | G → C, C → F, D → G, Bes → Es |
| **kleine terts omlaag (naar VI-majeur)** | 6 | F → D, C → A, G → E |
| kleine terts omhoog | 4 | D → F, C → Es |
| hele toon omhoog | 6 | C → D, D → E |
| kwint omhoog en overig | 3 | |

Twee vaste procedés:

1. **Trapsgewijs de subdominantkant op**: G → C → F (‘U zij de glorie’), A → C → F → Bes (Psalm 119),
   C → Es → F → Bes. Elk volgend couplet of het naspel staat een kwart hoger, dus een kruis minder. Het
   klinkt warmer en donkerder, niet opgeschroefd.
2. **Omlaag naar VI en dan een kwart omhoog** (F → D → G in ‘It is well’; C → A): de VI-majeur fungeert
   als dominant van de nieuwe toonsoort, die netto een hele toon boven het begin ligt. Dit is de klassieke
   ‘laatste couplet een toon hoger’, maar via een omweg van een couplet in de tussentoonsoort.

Wat niet voorkomt: de halvetoonopschuiving (C → Des) van gospel- en koorarrangementen (één keer gemeten,
vermoedelijk een detectiefout) en moduleren binnen een couplet.

## 8. Naspel en slot

Getallen: 18 naspelen, mediaan 17,5 maten; slotgedrag over alle 49 opnamen.

**Ontwerp.** Het naspel begint direct na de laatste fermate, meestal met Isus → I of met I → III (V/vi)
als uitwijking, en is het rustigste deel: 30% achtsten, linkerhand 2,3 aanslagen per maat (voorspel 3,4).
De bas gaat hier het diepst (laagste noot mediaan A₁, in ‘Great is thy faithfulness’ tot C₂) en
linkerhandoctaven komen hier het vaakst voor. Het naspel bevat opvallend vaak de plagale wending IV → I en
de bedrieglijke V → VI (beide in de top 3 van naspelopeenvolgingen); in mineur iv → V en VII → VI.

**Het slot** (n = 49):

| Kenmerk | Bevinding |
|---|---|
| Slotakkoord | tonica in grondligging (36 keer), IV in grondligging (6 keer: de compilaties en ‘Eer zij God’, die op een plagale I7 → IV eindigen), V (1 keer, Psalm 19: open einde) |
| Kwaliteit | 42 keer majeur. Van de 14 slotakkoorden op een mineurtonica zijn er 10 majeur (picardische terts; in de ruwe MIDI gecontroleerd: Psalm 130 d–fis–a, Psalm 37 c–e–g, ‘Ik wil mij gaan vertroosten’ d–fis–a, ‘Lofzang van Maria’ eindigt op een losse b), 2 zonder terts (open kwint of unisono: Psalm 13, ‘Wij trekken’), 2 mineur (‘Stille nacht’, Psalm 61) |
| Laatste progressie | plagaal (IV → I, iv → i, I7 → IV) 15 keer; authentiek (V → I, #VII → i) 10 keer; subtonica of submediant (bVII → I, VII → i, VI → I) 7 keer; II of ii → I 7 keer; III → I 2 keer; overig of onbepaald 8 keer |
| Omvang slotakkoord | 3 tot 5 noten (mediaan 4); nooit een tienstemmig orgeltutti |
| Ligging | bovenste noot mediaan 22 halve tonen (bijna 2 octaven) onder de hoogste noot van het stuk: het stuk eindigt in het midden van het klavier, niet hoog |
| Ritenuto | in 46 van de 49 opnamen: de laatste 6 aanslagen duren mediaan 1,9 keer zo lang als de normale puls (1,1 tot 3,0 keer) |
| Diminuendo | de laatste 6 seconden liggen mediaan 15 velocitypunten onder het gemiddelde (tot −50) |
| Slotakkoord | wordt niet gebroken (48 van de 49), duurt mediaan 4,5 seconden en wordt met pedaal uitgehouden; geen echo, geen extra slotnoot |

Vaste formule dus: rustig naspel, (plagale) slotwending, lang ritenuto, zacht en middelhoog slotakkoord
van 3 tot 5 noten in majeur, uitgehouden op het pedaal.

## 9. Spel: pedaal, legato, dynamiek, agogiek

- **Pedaal**: 62 tot 95% van de tijd ingedrukt (mediaan 89%). Wissels volgen de harmonie (ongeveer 30 per
  minuut bij 2 wissels per maat en 86 bpm). Er wordt nooit ‘droog’ gespeeld; ook het koraal is volledig
  gepedaliseerd.
- **Legato**: noten overlappen gemiddeld 12% met de volgende (legato-index 1,12, spreiding 1,07 tot 1,21):
  een consequente legato-aanslag, geen staccato of portato, ook niet in de bas.
- **Dynamiek**: het relatieve niveau blijft tussen mp en f; pp en ff komen alleen als korte uitschieters
  voor (minder dan 4% van de maten). De climax ligt in het voorspel of tussenspel, het slot is het zachtste punt.
- **Agogiek**: binnen een vormdeel is het tempo stabiel; voorspel, koraal en naspel kunnen elk een eigen
  tempo hebben (paragraaf 2). Vrijheid zit in de fermates op regeleinden, een korte adem vóór een nieuw
  couplet en het slotritenuto.
- **Gebroken akkoorden** (arpeggio’s): 1 tot 17% van de akkoorden, meestal het eerste akkoord van een frase in
  voor- of naspel; nooit systematisch, nooit als begeleidingspatroon.

## 10. Samenvatting: altijd, regelmatig, zelden, niet aangetroffen

**Altijd (95% of meer)**
- Vorm voorspel → koraal → (tussenspel → koraal) → naspel; elk stuk eindigt met een naspel.
- Melodie in de bovenstem van de rechterhand, in zangligging.
- Fermates op de regeleinden van het koraal; harmonische puls 2 akkoorden per maat.
- Toonsoort met 0 tot 3 voortekens; tempo tussen 65 en 112.
- Harmonie in grondligging op een grondtoonbas; diatonische drieklanken als basis.
- Pedaal (ongeveer 90% van de tijd), legato-aanslag.
- Slot: ritenuto, diminuendo, tonica (of IV) in grondligging, 3 tot 5 noten, niet gebroken, middenregister.

**Regelmatig (in de meeste stukken)**
- Vsus4 en Isus4 als kleur (10% van alle akkoorden); Vsus4 → I als overgang van voorspel naar koraal.
- IVmaj7, IVadd9 en Isus2 als kleuring in voorspel en naspel.
- Secundaire dominanten V/V en V/vi als zuivere drieklank, vooral in tussenspelen.
- Modulatie tussen coupletten: een kwart omhoog, of via VI-majeur een hele toon omhoog (de helft van de stukken).
- Orgelpunt onder voor- en naspel; linkerhandoctaven in laatste couplet en naspel.
- Plagale slotwending (IV → I) in plaats van V → I.
- Picardische terts aan het slot van mineurstukken; in mineur de aeolische v en VII.
- 8va-passages in het voorspel (hoogste noot van het stuk mediaan d''').
- Tweede couplet rustiger dan het eerste (hymns); bij psalmen zijn de coupletten identiek gezet.
- Gebroken akkoord op een frasebegin.

**Zelden (minder dan 5% van de akkoorden of minder dan 20% van de stukken)**
- V7 als volwaardig dominantseptiem (8% van de V’s); ii7 en vi7; viiº.
- Leenakkoorden bVII, bIII, bVI (2 tot 4% samen).
- Een echte vierstemmige koraalzetting met lopende binnenstemmen.
- Drie coupletten; een tussenspel langer dan het voorspel.
- Slot op de dominant (open einde, één keer) of in mineur zonder picardische terts.

**Niet aangetroffen in dit corpus**
- Verminderde septiem-, halfverminderde, gealtereerde of jazzakkoorden (m7♭5 0,3%, dim7 0,07%: ruis).
- Chromatische halvetoonmodulatie als ‘gear change’; modulatie midden in een couplet.
- Melodie in tenor of bas; het koraal een octaaf hoger dan de zangligging.
- Meer dan drie voortekens; tempo buiten 65 tot 112 kwartnoten per minuut.
- Droog (ongepedaliseerd) spel, staccatobegeleiding, Alberti-bas of ostinatopatronen.
- Virtuoze uitbarstingen: ff-slot, hoog slotakkoord, gebroken slotakkoord, extra slotnoot na het slotakkoord.
- Beginnen met een vol akkoord: het voorspel opent eenstemmig of tweestemmig.

Deze lijst beschrijft wat in 49 opnamen is waargenomen. Ze sluit niet uit dat een nieuwe zetting
in dezelfde stijl andere keuzes maakt.

## 11. Wat de cijfers niet vertellen

- De **stemvoering** (parallelle kwinten, leidtoonbehandeling, binnenstemmen) is met een audiotranscriptie
  niet betrouwbaar te beoordelen; daarvoor is de gedrukte uitgave nodig. Uit twee boekfoto’s van Psalm 85
  blijkt in elk geval dat de gedrukte zetting driestemmig is, met linkerhandoctaven in het naspel en 8va in
  het voorspel, in overeenstemming met de metingen.
- De **melodische motiefverwerking** in voorspelen (omkering, augmentatie, sequens) is alleen kwalitatief
  bekeken. In Psalm 85 en ‘Mijn Jezus’ opent het voorspel met de koraalkop in augmentatie en wordt de
  tweede regel gesequenst; in de meeste andere stukken wordt de kop niet letterlijk geciteerd.
- Het **aantal zelfstandige stemmen** per moment is niet gemeten; de aanslagtellingen in paragraaf 3 en 4
  zijn daarvoor geen vervanging.
- Wie de vormdelen voor alle 40 stukken exact wil hebben, kan de sectiegrenzen per stuk vastleggen in
  `splits.json` en `analyse_stijl.py` opnieuw laten draaien. De rest van de verwerking hoeft daarvoor
  niet te veranderen. Zie de [transcriptiehandleiding](docs/transcriptie.md#stap-3--analyse_stijlpy-stijlanalyse).
