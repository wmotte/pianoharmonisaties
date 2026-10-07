---
name: koele-pianozetting
description: Liederen (psalmen, Op Toonhoogte, Sela e.d.) omzetten naar MuseScore/PDF met een eigen pianobegeleiding in de stijl van Gerrit Koele — transcriberen naar bron/*.py, harmoniseren, regelcontrole, speelbaarheid, kleur en opmaak. Gebruik bij "zet deze liederen om naar MuseScore", "harmoniseer in de stijl van Koele", "maak de zetting voller/kleurrijker", of bij een nieuwe muziekgroep-map.
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
   bron negeren; zelf harmoniseren.
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
   binnenstemmen, vreemde sprongen, twee dezelfde noten tegelijk.

## Stijl (wat de gebruiker wil)
- **Kleur, niet saai**: sus4 (Vsus4→V, Isus4→I, Koeles handtekening), sus2/add9 op I en IV, IVmaj7, vi7/ii7
  (septiem stapsgewijs omlaag), af en toe V/V of V/vi; in mineur modale v, VII, VImaj7, picardische terts.
  Geen jazz-, verminderde of halfverminderde akkoorden, weinig V7.
- **Harmonisch ritme**: in 4/4 en 2/2 meestal 2 akkoorden per maat; hele maten alleen bij stilstand of slot.
- **Baslijn**: doorgaande bassen (`C G:B Am`, `F C:E Dm`); kwartsext alleen cadenserend.
- **Cadensen afwisselen**; herhaalde regels de tweede keer anders harmoniseren. Canon: elke regel hetzelfde schema.
- **Voorspel**: elk lied zonder intro krijgt er een (2–4 maten, meestal de slotregel), eindigend op Vsus4 → V met
  de bovenstem op de kwint; pas `"regels"` aan (maatnummers verschuiven). Bestaande intro's: vorm houden.
- **Overgang voorspel → zang** (automatisch, `voorspel_pauze()`): fermates + caesuur aan het eind van de eerste
  sectie zonder zang, zang op een nieuwe regel met kaderlabel **Zang**. Vervalt als een noot overgebonden is naar
  het zingen — de zang gaat altijd voor.
- **Voller dan Koeles kale zetting**: `vul()` in maak_partituren.py (alleen partituur, niet in de controle).

## Speelbaarheid (harde eis van de gebruiker)
- Per hand hoogstens een octaaf. Goed patroon: **links één lage noot, rechts drie** (melodie + alt + tenor).
- `vul()` verplaatst de tenor naar de rechterhand als die binnen een octaaf onder de melodie past én ≥ F3 ligt
  (`RH_MIN`, anders hulplijnen); alleen dan krijgt de bas een octaaf eronder (niet onder G1).
- Popballads (Sela e.d.): `"linkerhand": "gebroken"` in STUK → gebroken akkoorden in de linkerhand.

## Toonsoort en opmaak
- Max. 2 mollen of 2 kruisen; let op te hoge zangnoten (bijv. hoge es). Transponeren:
  `../koele/transponeer.py <naam> <interval> <toonaard> <toonsoort>` (bijv. `psalm_134 M2 F -1`); daarna kan de
  oude harmonie breken (S7 e.d.) → opnieuw kiezen.
- Uitgerekte regels of een te korte laatste regel: `"regels"` (maatnummers met nieuwe regel) of
  `"spatium": 1.5–1.6` per stuk. MuseScore breekt zelf af bij te volle systemen.

## Valkuilen
- Back-up vóór elke herzetting: `cp bron/<naam>.py tmp/backup/<naam>_<reden>.py`.
- Een regel in zetter.py versoepelen voor één verbinding breekt elders de controle (H8/AP8); pas het akkoord aan.
- Grijze (onzichtbare) rusten ontstaan als MusicXML-stemnummers per balk niet aaneensluiten (balk 1: 1, 2…;
  balk 2: 5, 6…). `nabewerk()` hernummert per maat; nieuwe stemmen altijd via die route laten lopen.
- Spatium werkt alleen via `<spatium>` in `score_style.mss` binnen de .mscz (`ruim_bereik()` doet dat).
- Veel stukken tegelijk: per 3 stukken een agent met deze skill; wacht op hun meldingen en bouw daarna zelf
  alles opnieuw met één `maak_partituren.py`-run.
