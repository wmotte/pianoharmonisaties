# Een psalmmelodie harmoniseren

Deze harmoniser schrijft een pianobegeleiding bij een eenstemmige melodie. Het
uitgangspunt is de koraalstijl in Gerrit Koeles pianospel: een herkenbare melodie,
een bas met enige zelfstandigheid en een begeleiding die kan wisselen tussen
liggende stemmen en gebroken akkoorden. Je krijgt MIDI om af te spelen en
MusicXML om in MuseScore te openen, verder uit te werken of af te drukken.

De map bevat de gekozen basisversie en vijf complete voorbeelden. Het zijn
gegenereerde harmonisaties van Psalm 6, 16, 49, 61 en 84, geen transcripties van
Koeles eigen uitvoeringen. Bij de vergelijking met drie psalmen was deze
basisversie telkens versie B. De latere proef met een andere akkoordherkenning
is niet in dit model overgenomen.

## Meteen bekijken

| Psalm | Partituur | Bewerkbare notatie | MIDI | Melodie-invoer |
|---|---|---|---|---|
| 6 | [PDF](voorbeelden/psalm_06.pdf) | [MusicXML](voorbeelden/psalm_06.musicxml) | [MIDI](voorbeelden/psalm_06.mid) | [JSON](voorbeelden/psalm_06.melodie.json) |
| 16 | [PDF](voorbeelden/psalm_16.pdf) | [MusicXML](voorbeelden/psalm_16.musicxml) | [MIDI](voorbeelden/psalm_16.mid) | [JSON](voorbeelden/psalm_16.melodie.json) |
| 49 | [PDF](voorbeelden/psalm_49.pdf) | [MusicXML](voorbeelden/psalm_49.musicxml) | [MIDI](voorbeelden/psalm_49.mid) | [JSON](voorbeelden/psalm_49.melodie.json) |
| 61 | [PDF](voorbeelden/psalm_61.pdf) | [MusicXML](voorbeelden/psalm_61.musicxml) | [MIDI](voorbeelden/psalm_61.mid) | [JSON](voorbeelden/psalm_61.melodie.json) |
| 84 | [PDF](voorbeelden/psalm_84.pdf) | [MusicXML](voorbeelden/psalm_84.musicxml) | [MIDI](voorbeelden/psalm_84.mid) | [JSON](voorbeelden/psalm_84.melodie.json) |

Open voor bewerking de MusicXML. Daarin staan de verdeling over twee balken,
maatsoorten en overbindingen al genoteerd. Bij het importeren van MIDI moet een
notatieprogramma die informatie deels opnieuw afleiden. De MIDI-klank hangt af
van het instrument waarmee je afspeelt; deze bestanden leveren geen opname of
pianoklank van Koele mee.

## Zelf gebruiken

Voer de opdrachten uit vanuit de hoofdmap van deze repository. Python 3.12 is
de gebruikte ontwikkelomgeving. Installeer de afhankelijkheden eenmalig:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-harmonizer.txt
```

Daarna kun je bijvoorbeeld de meegeleverde melodie van Psalm 49 harmoniseren:

```bash
.venv/bin/python harmonisatie/harmoniseer.py \
  harmonisatie/voorbeelden/psalm_49.melodie.json \
  --output harmonisatie/uitvoer/psalm_49 \
  --complete --search exact --exclude-group psalm_49
```

Het startscript gebruikt automatisch [model.json](model.json). De eigenlijke
code staat in [harmonizer](../harmonizer); houd deze twee mappen in dezelfde
repository. Voor generatie zijn de oorspronkelijke opnamen en de map
`private_data` niet nodig. Er is ook geen GPU of modeldienst nodig.

Kies een lege uitvoermap. Daar verschijnen `candidate.mid` en
`candidate.musicxml`, naast de gebruikte melodie, het effectieve model, de
noten van de zetting en een rapport. `--complete` vraagt om een tonicaslot voor
een volledig koraal. Laat die optie weg bij een los fragment. Voor een expliciet
majeurslot in een mineurkoraal kun je `--terminal-quality major` toevoegen.

`--exclude-group` is vooral nuttig bij corpusvergelijkingen: de generator weigert
een model waarin die liedgroep als training staat. Alle vijf voorbeeldpsalmen
zijn uit de training van dit model gehouden. Bij een eigen melodie kun je deze
optie weglaten.

MuseScore is alleen nodig als je meteen een PDF en een controle na herimport
wilt laten maken. Voeg op macOS bijvoorbeeld toe:

```bash
--musescore '/Applications/MuseScore 4.app/Contents/MacOS/mscore'
```

Op andere systemen geef je het pad naar de eigen MuseScore-installatie op.
De vijf bestaande voorbeelden bevatten al een PDF.

### Een eigen melodie aanleveren

JSON geeft de meeste controle over de muzikale invoer. Neem een meegeleverd
melodiebestand als uitgangspunt. Elke noot heeft een MIDI-toonhoogte `pitch`,
een begintijd `start` en een duur `duration`. Tijden zijn in kwartnoten: een
halve noot duurt `2`, ook in een 3/2-maat. Rusten ontstaan door ruimte tussen
noten te laten.

`tonic` is de grondtoon als toonklasse, met C = 0, D = 2, E = 4, F = 5,
G = 7, A = 9 en B = 11. `mode` geeft de modus aan, bijvoorbeeld `major`,
`minor`, `dorian` of `mixolydian`. Verder bevat de invoer:

- `meters`: maatsoorten met hun begintijd; `[0, 4, 4]` betekent 4/4 vanaf het begin.
- `phrases`: de eindposities van de frases, met de totale lengte als laatste grens.
- `length`: de totale lengte in kwartnoten; `bpm`: het tempo in kwartnoten per minuut.
- `fermatas`: eventuele posities waar een melodienoot eindigt met een fermate.

De melodie moet eenstemmig zijn. Een frasegrens mag geen noot doorsnijden.
Grondtoon, modus en frasegrenzen zijn inhoudelijke invoer: een verkeerde
mineur- of majeurkeuze verandert welke begeleiding aannemelijk wordt gevonden.

Een eenstemmige MusicXML kan ook rechtstreeks worden ingelezen als expliciete
toonsoortinformatie en fraseaanduidingen aanwezig zijn. Voor kale MIDI is extra
configuratie nodig die dit eenvoudige startscript niet aanbiedt. Gebruik voor
deze route daarom bij voorkeur de JSON-invoer.

## De begeleiding begint bij een figuur

Het model bevat 426 begeleidingsfiguren, afgeleid uit transcriptiefragmenten
van vijftien liedgroepen. Zo'n figuur legt vast hoe ver de begeleiding onder
de melodie ligt, wanneer de afzonderlijke tonen inzetten en hoelang ze blijven
klinken. Een bas die onder een lange melodienoot doorloopt, blijft daardoor een
mogelijke keuze. Hetzelfde geldt voor een binnenstem die even blijft liggen
terwijl een andere stem beweegt.

De generator zoekt figuren bij de melodietrap, modus, nootduur en plaats in de
maat. Toonafstanden zijn relatief opgeslagen, zodat een bruikbare ligging kan
meeverhuizen naar een andere toonhoogte. Naast die bronfiguren zijn er berekende
akkoordliggingen. Daarmee kan de generator ook verder als de verzamelde
voorbeelden geen passende zetting bevatten.

Er geldt geen vaste viernotenregel. Een koraal kan op het ene moment vierstemmig
zijn en elders opener klinken. Daarbij telt wat nog doorklinkt mee: drie nieuwe
aanslagen kunnen samen met een aangehouden toon vierstemmigheid opleveren.
Dat onderscheid is van belang bij pianomuziek met overbindingen en omspelingen.

## Een keuze moet ook aansluiten op de volgende

De generator beoordeelt zowel de afzonderlijke figuur als de verbinding met
haar buren. Hij weegt onder meer basbeweging, verplaatsing van binnenstemmen,
gemeenschappelijke tonen en wisselingen tussen liggende en bewegende
begeleiding. Overgangen die in de brongegevens voorkomen, krijgen een voorkeur.
De actieve controles begrenzen ook stemkruisingen, grote bassprongen en
parallelle reine intervallen tussen bas en melodie.

Met `--search exact` bewaart de zoekmotor verschillende relevante toestanden
zolang die later tot een andere keuze kunnen leiden. Pas na het doorzoeken van
de melodie ligt de gekozen route vast. Een iets duurdere ligging kan dus winnen
als zij een betere voortzetting mogelijk maakt. Dat is een exacte zoekopdracht
binnen de aangeboden kandidaten; de generator onderzoekt niet alle denkbare
harmonisaties.

Ook melodierusten krijgen aandacht. De begeleiding hoeft bij een ademhaling
niet automatisch stil te vallen. Het model bevat voorbeelden van zulke
verbindingen. Gemeenschappelijke binnenstemtonen kunnen worden overgebonden
wanneer de gekozen figuren dat toelaten. Registerprofielen helpen bepalen hoe
ver de bas onder de melodie ligt, en handbereik speelt mee bij de keuze van
liggingen en de verdeling over de pianobalken.

## Cadensen en harmonische kleur

Bij frase-einden vergelijkt de harmoniser de laatste melodietonen met
cadenscontexten uit het corpus. Die leveren mogelijke akkoorddoelen, soms met
een voorkeur voor een bepaalde basligging. Meerdere doelen kunnen naast elkaar
blijven bestaan. Een interne frase hoeft dus niet op de tonica te eindigen.

Het model biedt ook cadensvoorbereidingen en bewegende akkoordfiguren aan.
De uiteindelijke keuze hangt mede af van de beschikbare stemvoering. Dit is
nog geen uitgewerkt harmonieplan voor iedere volledige frase. Juist de
verbinding tussen aanloop, slot en volgende inzet blijft een zwak punt in
sommige uitkomsten.

De modus en de geleerde akkoordenschat bepalen de beschikbare harmonische
kleur. Chromatische tonen en dissonanten vragen om context; alleen tellen hoeveel
noten buiten een drieklank vallen geeft geen bruikbaar muzikaal oordeel. De code
bevat daarom ook controles op botsingen en melodische doorgang. De uitgebreidere
experimentele binnenstemzoekers en oplossingscontracten uit het onderzoek zijn
niet allemaal ingeschakeld in het meegeleverde model.

## Het eigen karakter van deze aanpak

Kenmerkend is de combinatie van kleine bronfiguren met een expliciete muzikale
zoekopdracht. De figuren dragen ritme, ligging en speelwijze over. De zoekregels
bepalen hoe ze bij een nieuwe melodie kunnen aansluiten. De melodie zelf blijft
vast: toonhoogten, inzetten en duren worden niet herschreven om een gemakkelijkere
harmonisatie te krijgen.

Het model is leesbare JSON. Daardoor is na te gaan welke voorbeelden en
voorkeuren een rol spelen, en kun je een wijziging vergelijken met precies
dezelfde melodie. Het bestand [manifest.json](manifest.json) legt de modelversie,
de codeversie via bestandskenmerken en de vijf meegeleverde uitgaven vast.
Lokale bronpaden zijn uit het verpakte model verwijderd; de muzikale gegevens
en bronidentiteiten zijn behouden.

Er wordt voor deze harmonisaties geen neuraal netwerk gefinetuned. De relatie
met Koeles spel zit in het gebruikte corpus en de muzikale keuzes die daaruit
zijn afgeleid. Dat levert een bruikbaar vertrekpunt voor een pianozetting op,
maar nog geen betrouwbare nabootsing van een volledige uitvoering. De
brontranscripties bevatten onzekerheden en de muzikale kwaliteit verschilt
per frase. De voorbeelden laten de gekozen versie zien zoals zij is, inclusief
de plekken die een pianist of arrangeur nog zou willen herzien.
