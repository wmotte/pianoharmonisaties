# De signatuur van Gerrit Koele — voorspel, koraal, tussenspel en naspel

Karakterisering van het ontwerp en de harmonisatie van Gerrit Koeles pianobewerkingen, gebaseerd op
een automatische analyse van alle 49 openbare YouTube-opnamen (40 losse liederen/psalmen en 9 compilaties;
samen ruim 5 uur muziek). De cijfers komen uit `analyse_stijl.py`; de kwalitatieve duiding is gecontroleerd 
aan de hand van MuseScore-renders van o.a. Psalm 85, Psalm 73, 'Mijn Jezus, ik hou van U', 'I need Thee every hour' 
en 'U zij de glorie'.

## 0. Methode en betrouwbaarheid

| Vraag | Middel |
|---|---|
| Akkoorden, trappen, liggingen, cadensen, modulaties | music21 (chordify per tel, sjabloon-matching op 15 akkoordtypen, Romeinse trappen t.o.v. de per-maat gedetecteerde toonsoort) |
| Vormdelen (voorspel / koraal / tussenspel / naspel) | melodische herhaling: een couplet is een passage waarvan de melodische intervalreeks elders (≥ 32 tellen verderop) vrijwel letterlijk terugkomt; wat niet herhaalt is voor-, tussen- of naspel |
| Pedaal, legato, gebroken akkoorden, aanslagsterkte | pretty_midi op de ruwe Transkun-MIDI (met CC64-pedaal), vóór alle opschoning |
| Ritenuto aan het slot | inter-onset-intervallen van de laatste 6 aanslagen t.o.v. de mediaan van het stuk |
| Controle van beweringen | MuseScore 4 CLI-renders van uitgekozen maten |

Gespecialiseerde harmonische-analysetools (DCML/ms3, Melisma, HumdRum) zouden de Romeinse-trappen-labels
iets consistenter maken, maar voegen op dit materiaal weinig toe: de harmonie is overwegend diatonisch en
drieklankgebaseerd, en de grootste foutbron is de audio-transcriptie zelf, niet de labeling.

**Wat is betrouwbaar en wat niet:**

- *Zeer betrouwbaar*: globale akkoordvocabulaire, trapverdeling, ligging, basbeweging, pedaalgebruik,
  tempo, toonsoortkeuze, begin- en slotgedrag, modulaties (met de hand gecontroleerd in renders).
- *Redelijk betrouwbaar*: de vormdelen. De automatische indeling is voor 18 van de 40 losse stukken
  schoon (voorspel – 1 à 3 coupletten met tussenspelen – naspel); deze 18 vormen de basis voor alle
  uitspraken per vormdeel. Bij de overige stukken is de vorm gefragmenteerd (vaak omdat het koraal er
  vrij wordt bespeeld, of omdat Transkun de melodie in dichte akkoorden niet consequent bovenaan zet).
- *Onbetrouwbaar / met korrel zout*: de categorie `aug` (3,5 % van alle akkoorden) is grotendeels een artefact
  van doorgangsnoten op akkoordwissels; het aandeel `sus2`/`add9` is eerder een onder- dan een overschatting
  (deze kleuren verdwijnen soms in de opschoning); melodie-citaten in het voorspel worden onderschat omdat de
  bovenstem daar versierd is.

## 1. Globaal profiel

| Kenmerk | Bevinding |
|---|---|
| Lengte los stuk | mediaan 98 maten ≈ 4 minuten (2:18 – 13:30) |
| Tempo | mediaan 86 bpm; alles tussen 65 en 112 (♩); nooit sneller, nooit langzamer |
| Maatsoort | 4/4 (33×) of 3/4 (16×); geen andere maatsoorten |
| Toonsoort | C, D, G, F, g, e, d, Bes, A, c, a — **nooit meer dan 3 voortekens**, en driekwart van de tijd 0–2 |
| Modus | 80 % majeur, 20 % mineur (Geneefse psalmen: modaal/aeolisch) |
| Modulatie | de helft van de losse stukken moduleert minstens één keer (zie §7) |
| Aanslag | gemiddeld ~70 (MIDI-velocity), spreiding klein (σ ≈ 14): een gelijkmatige, niet-virtuoze mf |
| Pedaal | 89 % van de tijd ingedrukt, ~30 wissels/min ≈ één wissel per akkoordwissel |
| Gebroken akkoorden | 9 % van de akkoorden wordt gebroken (arpeggio); nooit het slotakkoord |
| Fermates | mediaan 3,6 per 100 maten: vrijwel alleen op regeleinden van het koraal; in het voorspel af en toe een adempauze aan een frase-einde (in 13 van de 27 voorspelen), maar nooit als afsluiting van het voorspel |
| 8va | 41 van de 49 opnamen reiken tot c''' of hoger (hoogste noot mediaan d'''), bijna altijd in voor- of naspel |

## 2. Het ontwerp (vorm)

Het vaste model, in 18 van de 18 schoon gedetecteerde stukken:

```
VOORSPEL  →  KORAAL (couplet 1)  →  TUSSENSPEL  →  KORAAL (couplet 2)  →  NASPEL
 ~33 %           ~21 %               ~9 %             (idem)               ~20 %
```

- **Aantal coupletten**: mediaan 2 (1–3). Bij psalmen vrijwel altijd 2, bij Engelse hymns 1–2, bij
  kerstliederen soms 3. In de lange compilatievideo's worden series liederen achter elkaar gespeeld,
  elk met eigen voor- en naspel.
- **Verhouding**: het voorspel is het grootste onderdeel (mediaan 29 maten, 10–65; in tijd: mediaan ~70 s,
  30 s – 4 min). Het naspel is lang: mediaan 17,5 maten (7–42), vaak even lang als een couplet.
- **Tussenspel**: kort (mediaan 13 maten) en soms afwezig (couplet 2 volgt dan direct na de fermate).
- **Wat hij nooit doet**: het koraal zonder omlijsting spelen; meer dan drie coupletten; het stuk eindigen
  met de laatste koraalregel (er komt áltijd een naspel, hoe kort ook — minimaal ~7 maten).

## 3. Voorspel

Getallen: 18 voorspelen, mediaan 29 maten.

**Karakter.** Het voorspel is een vrije fantasie *over motieven* van het koraal, geen letterlijke
'doorspeel' van de melodie. Het langste melodie-fragment dat exact terugkomt is meestal 4–7 noten; slechts
in 3 van de 21 stukken opent het voorspel letterlijk met de kop van het koraal (Psalm 85, 'Amazing grace',
'Mijn Jezus'). In twee stukken ('Mijn Jezus', 'Wij trekken in een lange stoet') citeert hij wel een hele
regel (12 intervallen).

**Textuur.**
- Beweeglijker dan de rest: 57 % van de tellen bevat achtsten (koraal: 42 %, naspel: 30 %).
- Dunne zetting: rechterhand gemiddeld 1,4 noten tegelijk, linkerhand 1,1. Het is overwegend
  **tweestemmig tot driestemmig**: een zingende bovenstem, één middenstem en een baslijn.
- Opening: bijna altijd (mediaan RH-akkoordgrootte in de eerste 4 maten: 1,26) een **eenstemmige melodie
  in de rechterhand** boven een liggende of langzaam lopende bas; de harmonie wordt pas na enkele maten
  gevuld.
- Register: hoogste noot mediaan b'' (83), bovenstem gemiddeld rond a' (70). Bas gemiddeld rond dis (51),
  laagste noot C (36). Het voorspel is het deel dat het **hoogste** reikt — hier zitten de meeste 8va's.
- Dynamiek: mp–mf, iets zachter dan het koraal (velocity 78,6 vs 80,1); de eerste 6 seconden liggen
  gemiddeld ~5 punten onder het stuk-gemiddelde. Het voorspel begint dus zacht en groeit.

**Harmonie.** Dezelfde vocabulaire als het koraal (zie §6), maar met méér sus-akkoorden (16 % sus4+sus2
tegen 10 % in het koraal) en meer maj7/add9-kleuring. De harmonische puls is 2 akkoordwissels per maat.
Typische openingen: I → IV(7) → I, I → Isus → I, I → II → …, in mineur i → VII → …

**Slot van het voorspel.** In 17 van de 18 gevallen géén fermate; het voorspel loopt op een
dominant-spanning het koraal in. De meest voorkomende laatste twee akkoorden: **Vsus4 → I** (3×), Isus → I
(2×), V7 → I, III → I. Kortom: het voorspel eindigt op een (vaak opgehouden) dominant die direct in het
eerste akkoord van het koraal oplost, zonder pauze.

## 4. Hoofdspel: het koraal

Getallen: 31 coupletten in 18 stukken.

**Melodie altijd bovenaan.** De melodie ligt in de bovenstem van de rechterhand (in de zetting als
kwartnoten/halven); hij verplaatst haar niet naar de tenor of bas. Het bereik van de bovenstem in het
koraal is laag: gemiddeld rond gis' (68), hoogste noot mediaan g'' (79). Hij zet het koraal dus in de
**normale zangligging**, niet een octaaf hoger.

**Zetting.**
- Rechterhand: melodie + 1 noot (gemiddeld 1,5 noten per aanslag); linkerhand: bijna uitsluitend één
  basnoot (1,05). De typische zetting is **driestemmig**, niet vierstemmig-koraalachtig. Volle akkoorden
  (≥4 noten) zijn de uitzondering en komen op regelbegin/-einde.
- Linkerhand-octaven: 16 % van de basaanslagen (0–67 % per stuk); vooral in het laatste couplet en het
  naspel, om zwaarte te geven.
- Bij Geneefse psalmen (Psalm 1, 25, 37, 49, 73, 85) is het koraal ritmisch strikt: 0–3 % achtsten, de
  linkerhand speelt per tel. Bij hymns en kerstliederen zit 40–70 % achtsten: daar loopt de linkerhand
  (gebroken akkoorden, stapsgewijze baslijnen) door onder de lange melodienoten.
- Harmonische puls: 2 wissels per maat (4/4: op 1 en 3; 3/4: op 1 en 3 of 1 en 2).

**Regeleinden.** Elke koraalregel eindigt op een fermate (mediaan 4–6 per couplet bij psalmen, 1–3 bij
hymns). De cadensen op fermates (gemeten als de laatste twee
akkoorden vóór de fermate; n = 328 gelabelde fermate-cadensen op 408 fermates) verdelen zich als volgt:

| Cadens op fermate | majeur | mineur |
|---|---|---|
| V → I (authentiek) | 11 % | – |
| I → V (halfslot) | 9 % | i → V 9 % |
| IV → I (plagaal) | 7 % | – |
| II → V, II → I (V/V, ii) | 6 % | – |
| V → VI (bedrieglijk) | 3 % | – |
| VII → i (subtonica, aeolisch) | – | 6 % |
| VI → V, i → VI | – | 4 % + 4 % |
| overig (III → I, IV → bVII, i → VI in majeur, …) | ~64 % | ~77 % |

De belangrijkste uitkomst is de *spreiding*: geen enkele cadensformule domineert. Koele vermijdt de
standaard V7 → I op elke regel; hij gebruikt afwisselend authentieke, plagale, halve en bedrieglijke
slotwendingen en in mineur veel de modale VII → i en VI → V. Bijna altijd (73 %) staat het slotakkoord
van een regel in grondligging.

**Tweede couplet.** In de 12 stukken met twee coupletten:
- Bij de **psalmen** zijn couplet 1 en 2 vrijwel identiek gezet (dezelfde aanslag, register,
  akkoordgrootte — bv. Psalm 1: 81/66/2.0 tegen 81/66/2.0). Variatie zit daar niet in de zetting maar in
  toonsoort (zie §7) of in de linkerhand (octaven).
- Bij **hymns** verandert hij wel: 'I need Thee' couplet 2 is stiller en dunner (velocity 69 → 67,
  akkoordgrootte 2,1 → 1,1, achtsten 71 % → 25 %); 'Great is thy faithfulness' couplet 2 is voller
  (1,8 → 2,0) maar rustiger (60 % → 28 % achtsten) en ligt hoger; 'Stille nacht' couplet 2 is zachter (82 →
  75) en rustiger (53 % → 16 %). Het patroon: **het tweede couplet is meestal rustiger, niet luider** — de
  climax ligt niet in het laatste couplet maar in het voorspel/tussenspel en het begin van het naspel.
- Hij herharmoniseert een couplet niet grondig; de trap-bigrammen van couplet 1 en 2 overlappen sterk.

## 5. Tussenspel

Getallen: 13 tussenspelen, mediaan 13 maten (5–74).

- Sluit direct aan op de laatste fermate van het couplet en pikt vaak het laatste motief op.
- Textuur en dynamiek tussen voorspel en koraal in (49 % achtsten, velocity 79, akkoordgrootte 1,9).
- Harmonisch het meest avontuurlijke deel: hier zitten de meeste **I → III**-wendingen (V/vi), het meeste
  gebruik van #IV en bVI, en de modulaties (§7) vallen bijna altijd in het tussenspel of aan het begin
  van het naspel.
- Eindigt op dezelfde manier als het voorspel: zonder fermate (10 van de 13), op V, Vsus4 of I, dat het
  volgende couplet inleidt.

## 6. Harmonisatie: de vocabulaire

Over alle 49 opnamen (±14 000 akkoordlabels per tel):

**Akkoordtypen**

| Type | Aandeel | Opmerking |
|---|---|---|
| majeur-drieklank | 48 % | |
| mineur-drieklank | 17 % | |
| **sus4** | **10,6 %** | in élk stuk 2–17 %; het meest herkenbare kleurmiddel |
| sus2 | 5,4 % | vooral op I en IV |
| maj7 | 3,9 % | vooral IVmaj7, in mineur VImaj7 |
| dom7 | **3,0 %** | opvallend weinig: slechts 8 % van alle V-akkoorden in majeur is V7 |
| min7 | 2,8 % | ii7, vi7 |
| add9 | 2,4 % | Iadd9, IVadd9, bVIIadd9 |
| dim | 1,2 % | viiº als doorgang |
| maj6 / madd9 | ~1 % | |
| m7♭5, min6, dim7 | < 0,3 % | **praktisch afwezig** |

**Trappen in majeur (40 losse stukken)** — met de kwaliteit die het vaakst op die trap staat:

| Trap | Aandeel | Kwaliteit |
|---|---|---|
| I | 30 % | 76 % zuiver, 7 % sus2, 6 % sus4, 4 % add9 |
| V | 16 % | 55 % zuiver, **21 % sus4**, 8 % dom7 |
| IV | 13 % | 66 % zuiver, 10 % maj7, 9 % sus2, 6 % add9 |
| III | 10 % | 34 % iii, **23 % III (= V/vi)**, rest doorgang |
| II | 9 % | 39 % ii, 12 % ii7, **18 % II (= V/V)** |
| VI | 9 % | 55 % vi, 15 % VI (= V/ii) |
| VII | 3 % | viiº / doorgang |
| bVII | 2,6 % | majeur (mixolydisch/modaal leenakkoord), vaak als add9 |
| bIII, bVI, i | ~1–2,6 % | leenakkoorden uit de gelijknamige mineur |

**Trappen in mineur (Geneefse psalmen e.a.)**

| Trap | Aandeel | Kwaliteit |
|---|---|---|
| i | 27 % | 54 % mineur, **23 % majeur** (tonica-majeur/picardische terts op regeleinden) |
| V | 19 % | 34 % majeur, **26 % mineur (v, aeolisch)**, 20 % sus4 |
| VI | 14 % | 51 % majeur, **24 % maj7** |
| VII | 9 % | 67 % majeur (subtonica, geen leidtoon) |
| iv | 9 % | |
| III | 6 % | majeur (relatieve majeur) |
| ii | 4 % | iiº / ii |

**Wat dit betekent**

1. **Diatonisch en drieklankig.** 65 % van alle akkoorden is een zuivere drieklank; septiemakkoorden
   (alle soorten samen) < 13 %. Verminderde septiem-, halfverminderde en chromatisch veranderde akkoorden
   komen niet voor. Geen jazz-voicings, geen 'gospel'-dominanten.
2. **De sus4 als handtekening.** Eén op de vijf dominanten is Vsus4, en de progressies **Isus4 → I**,
   **Vsus4 → I** en **Vsus4 → V** staan alle drie in de top-10 van akkoordopeenvolgingen. Hij houdt de
   kwart op (vaak de melodienoot of de voorgaande basnoot) en lost pas laat of helemaal niet op — een
   klank die eerder aan Engelse hymn-/worship-piano doet denken dan aan een Bach-koraal.
3. **Secundaire dominanten, maar mild.** II (V/V) en III (V/vi) komen regelmatig voor (samen ~4 % van alle
   akkoorden in majeur), meestal als zuivere majeurdrieklank, niet als septiemakkoord, en bijna altijd
   in het tussenspel of op de voorlaatste regel.
4. **Modaal in mineur.** In de psalmen in mineur gebruikt hij vaker de mineur-dominant (v) en de majeur
   subtonica (VII) dan de leidtoon-dominant (V-majeur); daarmee respecteert hij het dorisch/aeolische
   karakter van de Geneefse melodieën. Regeleinden en het slot krijgen vaak wél de picardische terts.
5. **Leenakkoorden uit mineur in majeur**: bVII (2,6 %), bIII, bVI — als kleur, meestal in add9- of
   sus2-vorm en vaak vlak vóór het slot ('Amazing grace' eindigt bVII → I; 'U zij de glorie' I → bVII → I).
6. **Ligging: bijna alles in grondligging.** 74 % grondligging, 12 % kwartsextakkoord (vooral cadenserend
   I6/4 → V), 9 % sextakkoord. De bas is een *wortelbas*, geen lopende koraalbas.
7. **Basbeweging.** 45 % sprongen (kwart/kwint), 30 % liggend (bas herhaalt of blijft), 14 % stapsgewijs,
   10,5 % octaafsprong. Orgelpunten: mediaan 5,5 per 100 maten (in sommige stukken 10–15) — een liggende
   tonica of dominant onder wisselende akkoorden is een vast onderdeel van voor- en naspel.

**Meest voorkomende progressies (alle vormdelen)**: V → I, I → IV, I → V, Isus → I, IV → I, I → Isus,
I → III, Vsus → I, I → Vsus, Vsus → V, V → VI, VI → V, II → V, I → II. Ofwel: de kern is I–IV–V met
sus-versieringen, aangevuld met V/vi en V/V.

## 7. Modulaties

20 van de 40 losse stukken bevatten minstens één toonsoortwisseling (11× één, 6× twee, 3× drie of meer).
De modulaties liggen bijna altijd op de grens tussenspel → couplet of couplet → naspel. Intervallen
(gecontroleerd in renders, o.a. 'I need Thee' F → D → G en 'U zij de glorie' G → C → F):

| Richting | Aantal | Voorbeeld |
|---|---|---|
| **kwart omhoog (naar de subdominant)** | 10 | G → C, C → F, D → G, Bes → Es |
| **kleine terts omlaag (naar VI-majeur)** | 6 | F → D, C → A, G → E |
| kleine terts omhoog | 4 | D → F, C → Es |
| hele toon omhoog | 6 | C → D, D → E |
| kwint omhoog / overig | 3 | |

Twee vaste procedés:

1. **Trapsgewijs de subdominantkant op**: G → C → F ('U zij de glorie'), A → C → F → Bes (Psalm 119),
   C → Es → F → Bes. Elk volgend couplet (of het naspel) staat een kwart hoger = een kruis minder; het
   klinkt warmer/donkerder, niet 'opgeschroefd'.
2. **Omlaag naar VI en dan een kwart omhoog** (F → D → G; F → D → G in 'It is well'; C → A): de VI-majeur
   fungeert als dominant van de nieuwe toonsoort, die netto een hele toon boven het begin ligt. Dit is de
   klassieke 'laatste-couplet-een-toon-hoger', maar via een omweg van een couplet in de tussentoonsoort.

Wat hij **niet** doet: de halve-toon-opschuiving (C → Des) van gospel-/koorarrangementen (1× gemeten en
dat is vermoedelijk een detectiefout), en moduleren binnen een couplet.

## 8. Naspel en slot

Getallen: 18 naspelen, mediaan 17,5 maten; slotgedrag over alle 49 opnamen.

**Ontwerp.** Het naspel begint direct na de laatste fermate, meestal met **Isus → I** of **I → III** (V/vi)
als uitwijking, en is het *rustigste* deel: 30 % achtsten, linkerhand 2,3 aanslagen per maat (voorspel
3,4). De bas gaat hier het diepst (laagste noot mediaan A₁, in 'Great is thy faithfulness' tot C₂) en
LH-octaven zijn hier het vaakst. Het naspel bevat opvallend vaak de plagale wending IV → I en de
bedrieglijke V → VI (beide in de top-3 van naspel-bigrammen); in mineur iv → V en VII → VI.

**Het slot** (n = 49):

| Kenmerk | Bevinding |
|---|---|
| Slotakkoord | tonica in grondligging (36×), IV in grondligging (6× — de compilaties en 'Eer zij God', die op een plagale I7 → IV eindigen), V (1×, Psalm 19: open einde) |
| Kwaliteit | 42× majeur. Van de 14 slotakkoorden op een mineur-tonica zijn er 10 majeur (**picardische terts**; in de ruwe MIDI gecontroleerd: Psalm 130 d–fis–a, Psalm 37 c–e–g, 'Ik wil mij gaan vertroosten' d–fis–a, 'Lofzang van Maria' eindigt op een losse b), 2 zonder terts (open kwint/unisono: Psalm 13, 'Wij trekken'), 2 mineur ('Stille nacht', Psalm 61) |
| Laatste progressie | plagaal (IV → I, iv → i, I7 → IV) 15×; authentiek (V → I, #VII → i) 10×; subtonica/submediant (bVII → I, VII → i, VI → I) 7×; II/ii → I 7×; III → I 2×; overig/onbepaald 8× |
| Omvang slotakkoord | 3–5 noten (mediaan 4); nooit een tienstemmig 'orgel-tutti' |
| Ligging | bovenste noot mediaan **22 halve tonen (bijna 2 octaven) onder de hoogste noot van het stuk**: hij eindigt in het midden van het klavier, niet hoog |
| Ritenuto | in 46 van de 49 opnamen: de laatste 6 aanslagen zijn mediaan **1,9× zo lang** als de normale puls (1,1–3,0×) |
| Diminuendo | de laatste 6 seconden liggen mediaan 15 velocity-punten onder het gemiddelde (tot −50) |
| Slotakkoord | wordt **niet gebroken** (48 van de 49), duurt mediaan 4,5 s en wordt met pedaal uitgehouden; geen echo, geen extra slotnoot |

Vaste formule dus: rustig naspel → (plagale) slotwending → lang ritenuto → zacht, middelhoog, 3–5-stemmig
majeur-slotakkoord, uitgehouden op het pedaal.

## 9. Spel: pedaal, legato, dynamiek, agogiek

- **Pedaal**: 62–95 % van de tijd ingedrukt (mediaan 89 %). Wissels volgen de harmonie (≈ 30/min bij 2
  wissels per maat en 86 bpm). Hij speelt nooit 'droog'; ook het koraal is volledig gepedaliseerd.
- **Legato**: noten overlappen gemiddeld 12 % met de volgende (legato-index 1,12, spreiding 1,07–1,21):
  een consequente legato-aanslag, geen staccato of portato, ook niet in de bas.
- **Dynamiek**: het relatieve niveau blijft tussen mp en f; pp en ff komen alleen als korte uitschieters
  voor (< 4 % van de maten). De climax ligt in het voorspel/tussenspel, het slot is het zachtste punt.
- **Agogiek**: tempo binnen een stuk stabiel (Viterbi-maatvolger vindt zelden onregelmatige maten);
  vrijheid zit in fermates (regeleinden), een korte adem vóór een nieuw couplet en het slot-ritenuto.
- **Gebroken akkoorden** (arpeggio's): 1–17 % van de akkoorden, meestal het eerste akkoord van een frase in
  voor- of naspel; nooit systematisch, nooit als begeleidingspatroon.

## 10. Samenvatting: altijd / regelmatig / zelden / nooit

**Altijd (≥ 95 %)**
- Vorm voorspel → koraal → (tussenspel → koraal) → naspel; elk stuk eindigt met een naspel.
- Melodie in de bovenstem van de rechterhand, in zangligging; koraal driestemmig gezet.
- Fermates op de regeleinden van het koraal; harmonische puls 2 akkoorden per maat.
- Toonsoort met 0–3 voortekens; tempo 65–112.
- Grondliggings-harmonie op wortelbas; diatonische drieklanken als basis.
- Pedaal (≈ 90 % van de tijd), legato-aanslag.
- Slot: ritenuto, diminuendo, tonica (of IV) in grondligging, 3–5 noten, niet gebroken, middenregister.

**Regelmatig (in de meeste stukken)**
- Vsus4 en Isus4 als kleur (10 % van alle akkoorden); Vsus4 → I als overgang voorspel → koraal.
- IVmaj7 / IVadd9 / Isus2-kleuring in voorspel en naspel.
- Secundaire dominanten V/V en V/vi als zuivere drieklank, vooral in tussenspelen.
- Modulatie tussen coupletten: een kwart omhoog, of via VI-majeur een hele toon omhoog (de helft van de
  stukken).
- Orgelpunt onder voor- en naspel; linkerhandoctaven in laatste couplet/naspel.
- Plagale slotwending (IV → I) in plaats van V → I.
- Picardische terts aan het slot van mineur-stukken; in mineur de aeolische v en VII.
- 8va-passages in het voorspel (hoogste noot van het stuk mediaan d''').
- Tweede couplet rustiger dan het eerste (hymns); psalmen: coupletten identiek gezet.
- Gebroken akkoord op een frasebegin.

**Zelden (< 5 % van de akkoorden of < 20 % van de stukken)**
- V7 als volwaardig dominantseptiem (8 % van de V's); ii7/vi7; viiº.
- Leenakkoorden bVII, bIII, bVI (2–4 % samen).
- Echte vierstemmige koraalzetting met lopende binnenstemmen.
- Drie coupletten; tussenspel langer dan het voorspel.
- Slot op de dominant (open einde, 1×) of in mineur zonder picardische terts.

**Nooit**
- Verminderde septiem-, halfverminderde, alterered of jazz-akkoorden (m7♭5 0,3 %, dim7 0,07 % = ruis).
- Chromatische halve-toon-modulatie als 'gear change'; modulatie midden in een couplet.
- Melodie in tenor of bas; koraal een octaaf hoger dan de zangligging.
- Meer dan 3 voortekens; andere maatsoorten dan 4/4 en 3/4; tempo boven 112 of onder 65.
- Droog (ongepedaliseerd) spel, staccato-begeleiding, Alberti-bas of ostinato-patronen.
- Virtuoze uitbarstingen: ff-slot, hoog slotakkoord, gebroken slotakkoord, extra slotnoot na het
  slotakkoord.
- Beginnen met een vol akkoord: het voorspel opent eenstemmig of tweestemmig.

## 11. Wat de cijfers niet vertellen (en hoe verder)

- De **stemvoering** (parallelle kwinten, leidtoonbehandeling, binnenstemmen) is met een audio-transcriptie
  niet betrouwbaar te beoordelen; daarvoor is het gedrukte boek nodig. Uit de twee boekfoto's van Psalm 85
  blijkt in elk geval dat de gedrukte zetting driestemmig is, met LH-octaven in het naspel en 8va in het
  voorspel — consistent met de metingen.
- De **melodische motiefverwerking** in voorspelen (omkering, augmentatie, sequens) is alleen kwalitatief
  bekeken: in Psalm 85 en 'Mijn Jezus' opent het voorspel met de koraalkop in augmentatie en sequenst hij
  de tweede regel; in de meeste andere stukken wordt de kop niet letterlijk geciteerd.
- Wie de vormdelen voor álle 40 stukken exact wil hebben, kan de sectiegrenzen in `stijlanalyse.json` met
  de hand corrigeren en `analyse_stijl.py` daarop opnieuw laten aggregeren; de rest van de pijplijn hoeft
  daar niet voor te veranderen.
