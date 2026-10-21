---
name: koele-pianozetting
description: Liederen (psalmen, Op Toonhoogte, Sela e.d.) omzetten naar MuseScore/PDF met een eigen pianobegeleiding in de stijl van Gerrit Koele, inclusief gitaarakkoorden uit de harmonisatie, regelcontrole, speelbaarheid, kleur en opmaak. Gebruik bij "zet deze liederen om naar MuseScore", "harmoniseer in de stijl van Koele", "maak de zetting voller/kleurrijker", "gitaarakkoorden boven de pianopartij", of bij een nieuwe muziekgroep-map.
---

# Pianozettingen in de stijl van Gerrit Koele

Gereedschap staat in `koele/` (getrackt, zie `koele/README.md`); de liederen zelf in een privémap
`muziekgroep_<datum>/` (werkend voorbeeld: `muziekgroep_11_oct/`). Alle scripts draai je **vanuit de liedmap**:
`../.venv/bin/python ../koele/<script>.py`. Lees eerst `stijlanalyse.md` (repo-root) en de docstrings van
`koele/maak_partituren.py` (bronnotatie) en `koele/zetter.py` (akkoordnotatie).
Een zetting juist uitdunnen of vierstemmig maken: skill `vierstemmig-reduceren`.

## Privacy — altijd
- Bladmuziek, bijlagen en bronnen zijn auteursrechtelijk/privé en de repo is openbaar: zet een nieuwe liedmap
  direct in `.gitignore` (zoals `/muziekgroep_11_oct/`). Nooit committen of pushen.
- De pre-commit-hook `.githooks/pre-commit` weigert liedmappen en bladmuziek; activeren in een verse clone met
  `git config core.hooksPath .githooks`.
- Originelen in `raw/`; tijdelijke renders en scratch in `tmp/`.

## Werkwijze
1. **Transcriberen** per lied naar `bron/<naam>.py` (`STUK` met secties): melodie, tegenstem, "1" (piano-bovenstem
   als die afwijkt van de melodie, bijv. in voorspel/tussenspel), tekst, voltas, herhalingen. Akkoorden uit de
   bron negeren; zelf harmoniseren. Melodie en tekst volgen de bundel die de gemeente zingt (zie **Tekst en
   melodiebron**).
2. **Akkoorden kiezen** (`"akkoorden"`); `zetter.py` zet alt/tenor/bas met de regels als harde eisen.
   Twijfel over één maat: `../koele/probeer.py <naam> <sectie> <maat> 'kand1' 'kand2'` toetst varianten
   zonder de bron te wijzigen.
3. **Bouwen = controleren**: `../.venv/bin/python ../koele/maak_partituren.py [naam ...]`. Dit draait regels,
   stemcontrole, greep (≤ 1 octaaf per hand), grijze rusten en opmaak in één keer. Klaar als elk stuk
   `<naam>: ok` meldt (exit 0); `LET OP`-regels beoordeel je zelf. `geen regelgoede verbinding naar X` =
   kies een ander akkoord of omkering, versoepel de regels niet.
4. **Kleur meten**: `../koele/kleurstats.py` → doel 15–25 % kleur, 10–15 % omkeringen.
5. **Bekijken**: render alleen de PDF-pagina's waar de controle iets meldt, plus een steekproef
   (`pdftoppm -r 80 -png -f <p> -l <p> "pdf/<bestand>.pdf" tmp/<naam>`). Kijk kritisch naar herhaalde noten in
   binnenstemmen, vreemde sprongen, twee dezelfde noten tegelijk. Controleer ook de leesbaarheid en plaatsing
   van gitaarakkoorden, vooral lange kleur-/slashakkoorden en dicht opeenvolgende sus4-oplossingen.

## Tekst en melodiebron
- **Psalmen (OB)**: de gemeente zingt de OB 1773. Lees de melodie van de OB-scan van de gebruiker; een Geneefse
  bron (genevanpsalter.com) is alleen een hulp bij het aflezen. Voortekens volgen de OB-scan (bijv. de gis in
  Psalm 19 regel 11), ook waar de Geneefse melodie afwijkt. Tekst: psalmboek.nl. Elke regelslotnoot wordt een
  hele noot (in de OB een halve met ademteken).
- Elk lied krijgt de **tekst van alle te zingen coupletten** onder de zangbalk (`"tekst"`, regel n begint met
  `"n.~"`). Ontbreekt een couplet in de bron, vraag het de gebruiker; vul nooit zelf aan.
- **Herhaling met voltas** (`"1.2.3.4."` en `"5."`): tekstregel n bevat couplet n plus de opmaat van couplet
  n+1 onder volta 1; de laatste tekstregel eindigt onder de slotvolta.
- **Wisselzang** (allen/mannen/vrouwen) als `"ondertitel"`.
- `"componist"` noemt alleen de melodie (componist/bron), zonder vermelding van de zetter.

## Gitaarakkoorden boven de pianopartij
- Zet akkoordsymbolen boven de **bovenste pianobalk**, afgeleid uit de eigen harmonisatie (`"akkoorden"`)
  en de **werkelijk gezette bas** in stem `"4"`. Neem geen akkoorden over uit `raw/`. `gitaarakkoorden()` in
  `maak_partituren.py` doet dit automatisch, inclusief omkeringen die de zetter zelf kiest (`C/E`, `G/B`).
- Behoud de harmonische kleur: sus4/sus2, add9, maj7 en m7 waar die in de zetting staan. Geef bij de eerste
  klinkende harmonie van elke maat een symbool en vervolgens bij iedere betekenisvolle akkoord- of baswissel.
  Doorgaans twee akkoorden per maat in 4/4 of 2/2, extra bij cadensen of doorgaande bassen. Melodische
  doorgangen en gebroken begeleidingsfiguren krijgen niet per noot een nieuw akkoord.
- Herhaalde gelijke akkoorden binnen de maat en `=` lopen door zonder extra symbool; aan het begin van een
  volgende maat herhaal je het geldende akkoord voor houvast. `R` onderbreekt de harmonie met `N.C.` als er
  een akkoord klonk. Symbolen voegen geen speelnoten toe en veranderen de pianozetting niet.
- Review de symbolen tegen de gekozen harmonie en klinkende bas, ook bij opmaten, herhalingen en
  maat-/toonsoortwisselingen. Beoordeel de PDF op botsingen en pas zo nodig akkoordafstand of regelverdeling
  aan. Secties met alleen uitgeschreven stemmen, zonder `"akkoorden"`, vragen eerst afzonderlijke harmonische
  analyse; de automatische functie voegt daar geen symbolen toe.
- Sectieletters zoals A/B/C staan in een kader boven de zangbalk, zodat ze herkenbaar blijven als
  vormaanduiding. Gitaarakkoorden staan boven de pianobalk.

## Stijl (wat de gebruiker wil)
- **Kleur, niet saai**: sus4 (Vsus4→V, Isus4→I, Koeles handtekening), sus2/add9 op I en IV, IVmaj7, vi7/ii7
  (septiem stapsgewijs omlaag), af en toe V/V of V/vi; in mineur modale v, VII, VImaj7, picardische terts.
  Geen jazz-, verminderde of halfverminderde akkoorden, weinig V7.
- **Modaal blijft modaal**: harmoniseer met akkoorden uit de modus. E-dorisch (twee kruisen): Em, G, D, Bm, A,
  F♯m; C- en Am-akkoorden alleen waar de melodie zelf c heeft. Mineurakkoorden uit de eolische toonladder
  geven anders herstellingstekens in elke maat.
- **Harmonisch ritme**: in 4/4 en 2/2 meestal 2 akkoorden per maat; hele maten alleen bij stilstand of slot.
- **Baslijn**: doorgaande bassen (`C G:B Am`, `F C:E Dm`); kwartsext alleen cadenserend.
- **Cadensen afwisselen**; herhaalde regels de tweede keer anders harmoniseren. Canon: elke regel hetzelfde schema.
- **Voorspel**: elk lied zonder intro krijgt er een (2–4 maten, meestal de slotregel), eindigend op Vsus4 → V met
  de bovenstem op de kwint; pas `"regels"` aan (maatnummers verschuiven). Bestaande intro's: vorm houden.
- **Overgang voorspel → zang** (automatisch, `voorspel_pauze()`): fermates + caesuur aan het eind van de eerste
  sectie zonder zang, zang op een nieuwe regel met kaderlabel **Zang**. Vervalt als een noot overgebonden is naar
  het zingen — de zang gaat altijd voor.
- **Afspeelduur fermates**: 150% van de notatieduur in MuseScore. `fermate_duur()` zet bij de nabewerking
  van de `.mscz` elke fermate op `<timeStretch>1.5</timeStretch>`, zodat opnieuw bouwen de voorkeur behoudt.
- **Standaardtempo psalmen**: 90 kwartnoten per minuut, tenzij de gebruiker expliciet een ander tempo vraagt.
  Zet `"tempo": 90` in de eerste sectie, zodat MuseScore dit vanaf het voorspel gebruikt en het tempo bij
  opnieuw bouwen behouden blijft. Vermijd onbedoelde terugval naar MuseScores standaardtempo van 120.
- **Voller dan Koeles kale zetting**: `vul()` in maak_partituren.py (alleen partituur, niet in de controle).

## Speelbaarheid (harde eis van de gebruiker)
- Per hand hoogstens een octaaf. Goed patroon: **links één lage noot, rechts drie** (melodie + alt + tenor).
- `vul()` verplaatst de tenor naar de rechterhand als die binnen een octaaf onder de melodie past én ≥ F3 ligt
  (`RH_MIN`, anders hulplijnen); alleen dan krijgt de bas een octaaf eronder (niet onder G1).
- Popballads (Sela e.d.): `"linkerhand": "gebroken"` in STUK → gebroken akkoorden in de linkerhand.
- Begeleidingsvariant zonder melodie in de piano: `"begeleiding": "akkoorden"` in STUK. Maten met zang krijgen
  rechts gesloten akkoorden (F3–D5, kleine bewegingen) en links alleen de bas; maten zonder zang houden de
  melodie. Op een `R` in `"akkoorden"` (opmaat na het voorspel, opmaat van het volgende couplet) speelt de
  piano de melodie mee, zodat ze na het voorspel niet stilvalt. Tegen voorspelbaarheid wisselt de rechterhand
  per akkoord van twee tellen van figuur naar de drukte van de zang (`_rh_figuur()`) en de linkerhand van
  gebroken figuur (`LH_FIGUREN`); meer afwisseling hoort daar, niet in losse bronnen. De linkerhand kiest per
  basnoot het octaaf dicht bij de vorige (C2–E3) en loopt in achtsten door waar de zang een tel stilstaat;
  controleer de baslijn maat voor maat op sprongen. Gebruik dit ook als fluit of zangers de
  melodie al hebben. Maak zo'n variant als aparte bron (`<naam>_akkoorden.py`, bestandsnaam met `b`) naast het
  origineel; die kan STUK uit het origineel laden en alleen `"begeleiding"` en `"bestandsnaam"` overschrijven.
- Uitgebreide versie (tussenspelen, eigen zetting per couplet, bovenstem): aparte bron die ROMP/tekst uit het
  origineel laadt, één sectie per couplet en tussenspel; de opmaat van het volgende couplet staat in de laatste
  maat van de vorige sectie.
- **Piano-bovenstem boven de zang** ("1" in een zangsectie): moet hoorbaar een eigen stem zijn. Geef hem een
  eigen ritme (lang waar de melodie beweegt, achtsten waar de melodie aanhoudt), tegenbeweging en een
  hoogtepunt; parallel meelopen in kwarten verdwijnt in de zetting. Zet `"teksten": {0: "piano: bovenstem naar
  voren"}` in de sectie. Bereik D5–G5 (A5 alleen boven een omkering): hoger past onder een grondligging geen
  terts meer in de zetting (`geen ligging voor X`). Achtsten in de bovenstem kunnen S-A > octaaf of een
  septiem/leidtoon geven; los dat op in de bovenstem.
- **Dwarsfluit** (variant `<naam>_fluit.py`, bestandsnaam `01b … (dwarsfluit)`): de bovenstem als
  `"tegenstem"` per sectie, en `STUK["tegenstemnaam"] = ("Dwarsfluit", "Fl.")`, zodat balk, MuseScore-kanaal en
  klank fluit zijn (anders “Tegenstem” met zangklank). Ligging: in het octaaf van de piano-bovenstem
  (ongeveer D4–E5), niet een octaaf hoger; de gebruiker vond B5–E6 te hoog. In het voorspel speelt de fluit de
  piano-bovenstem in dezelfde ligging mee. Stijl (voorbeeld: `muziekgroep_25_oct/bron/psalm_62_fluit.py`):
  per regel afwisselend lange noten, een syncope (kwart + gepunteerde halve, of overgebonden over de maatstreep),
  een korte kwartloop door akkoordtonen en een verbindingsnoot naar de volgende regel; op de lange slotnoot van
  de melodie beweegt de fluit, en waar de melodie stijgt gaat de fluit vaak omlaag. Alleen halve en hele noten
  klinkt te eenvoudig. De fluit telt mee in de zetting: een fluitnoot kan `geen regelgoede verbinding` geven,
  ook een paar maten verderop; varieer dan de fluitnoten rond die plek.
- Naspel tijdens de collecte: lang (12–16 maten) met herhaalteken en kop "Naspel – ad lib. herhalen
  (collecte)", daarna een slot van 3 maten met "rit.".

## Toonsoort en opmaak
- Max. 2 mollen of 2 kruisen; let op te hoge zangnoten (bijv. hoge es). Transponeren:
  `../koele/transponeer.py <naam> <interval> <toonaard> <toonsoort>` (bijv. `psalm_134 M2 F -1`); daarna kan de
  oude harmonie breken (S7 e.d.) → opnieuw kiezen.
- Uitgerekte regels of een te korte laatste regel: `"regels"` (maatnummers met nieuwe regel) of
  `"spatium": 1.5–1.6` per stuk. MuseScore breekt zelf af bij te volle systemen. Veel tekstregels (vier of
  vijf coupletten): spatium 1.2–1.4, zodat het stuk liefst op één pagina past.
- **Partituuropmaak** (voorkeur gebruiker, vastgelegd in `koele/stijl.mss` en `ruim_bereik()`): A4, kleine
  titel (16 pt) en een laag titelkader zodat de muziek de ruimte krijgt, tekst donkerblauw, gitaarakkoorden
  donkerrood en vet. Kleuren en lettergroottes horen in `stijl.mss`, niet per stuk.

## Valkuilen
- Back-up vóór elke herzetting: `cp bron/<naam>.py tmp/backup/<naam>_<reden>.py`.
- Een regel in zetter.py versoepelen voor één verbinding breekt elders de controle (H8/AP8); pas het akkoord aan.
- Grijze (onzichtbare) rusten ontstaan als MusicXML-stemnummers per balk niet aaneensluiten (balk 1: 1, 2…;
  balk 2: 5, 6…). `nabewerk()` hernummert per maat; nieuwe stemmen altijd via die route laten lopen.
- Spatium werkt alleen via `<spatium>` in `score_style.mss` binnen de .mscz (`ruim_bereik()` doet dat).
- `transponeer.py` laat herstellingstekens (`n`) vallen: controleer na transponeren elke `Fn4` e.d. en zet ze terug.
- De regelcontrole leidt de toonsoort af uit de voortekening (groot, mineur, dorisch). Mixolydisch met één kruis
  leest als G groot, dus fis telt als leidtoon: vermijd dan F♯m en verdubbelde fissen in plaats van de regels
  aan te passen.
- Veel stukken tegelijk: per 3 stukken een agent met deze skill; wacht op hun meldingen en bouw daarna zelf
  alles opnieuw met één `maak_partituren.py`-run.
