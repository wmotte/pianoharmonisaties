# Gerrit Koele – van YouTube naar bladmuziek

Met deze scripts zet je de openbare pianovideo's van
[Gerrit Koele](https://www.youtube.com/@GerritKoeleMusicus/videos) om naar bladmuziek.
Je krijgt MusicXML voor MuseScore en MIDI om af te spelen.
Daarna kun je de stemvoering controleren en de begeleiding laten aanpassen.

Je kunt ook een nieuwe pianobegeleiding laten schrijven bij een psalmmelodie.
Daarvoor gebruikt de harmoniser patronen uit Koeles pianospel.

## Kies waar je wilt beginnen

- [Een psalmmelodie harmoniseren](#psalmen-harmoniseren): geef zelf de melodie op.
- [Een opname omzetten](#opnamen-omzetten): laat de gespeelde noten herkennen en uitschrijven.
- [Voorbeelden bekijken](#voorbeelden): vergelijk de partituren zonder eerst iets te installeren.

De installatievoorbeelden gebruiken Python 3.12. De twee toepassingen hebben verschillende
pakketten nodig en krijgen daarom elk een eigen virtuele omgeving: `.venv-harmonisatie`
voor de harmoniser en `.venv` voor transcriptie. Voer de commando's uit vanuit de hoofdmap van deze repository.

## Psalmen harmoniseren

Geef de harmoniser een melodie met de toonsoort, maatsoort en het einde van elke muzikale frase.
Het programma kiest de akkoorden en schrijft de bas en binnenstemmen uit als pianopartituur.
De opgegeven melodie blijft intact. Een opname of bestaande begeleiding is niet nodig.

Maak met een geïnstalleerde Python 3.12 de omgeving aan en harmoniseer bijvoorbeeld Psalm 49:

```bash
python3.12 -m venv .venv-harmonisatie
.venv-harmonisatie/bin/python -m pip install -r requirements-harmonizer.txt
.venv-harmonisatie/bin/python harmonisatie/harmoniseer.py \
  harmonisatie/voorbeelden/psalm_49.melodie.json \
  --output harmonisatie/uitvoer/psalm_49 --complete --search exact
```

Kies een lege uitvoermap. Daar verschijnen onder meer `candidate.musicxml` en `candidate.mid`.
Open de MusicXML in MuseScore om de partituur te bekijken of verder te bewerken.
Voor deze generatie zijn de oorspronkelijke opnamen niet nodig.

De harmoniser is experimenteel. De gegenereerde zettingen zijn geïnspireerd op Koeles stijl.
Het zijn geen uitvoeringen van Gerrit Koele.

In de [gebruiksaanwijzing](harmonisatie/HARMONISATIE.md) staan vijf complete voorbeelden
van Psalm 6, 16, 49, 61 en 84, met PDF, MusicXML, MIDI en de ingevoerde melodie.
Daar lees je ook hoe je een eigen melodie invoert en via MuseScore een PDF maakt.

## Opnamen omzetten

Installeer voor transcriptie de pakketten uit `requirements.txt`.
Met [uv](https://docs.astral.sh/uv/) maak je daarvoor de omgeving `.venv`:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

`transcribe_midi.sh` gebruikt de Python uit deze map. De omgeving hoeft niet geactiveerd te zijn.
Je kunt ook [installeren met standaard pip](docs/transcriptie.md#installatie-met-standaard-pip).

Voor downloaden en audioverwerking heb je ook externe programma's nodig.
`yt-dlp` haalt video's op. `ffmpeg` zet de gedownloade audio om naar mp3 en is nodig om opnamen in delen te knippen.
Op macOS installeer je ze met Homebrew:

```bash
brew install ffmpeg yt-dlp
```

Zet je eigen mp3-bestanden in `mp3/`. Je kunt ook alle openbare video's van Koeles kanaal
laten downloaden met:

```bash
./download_koele.sh
```

Het downloadscript slaat video's over die het eerder heeft opgehaald.
Schrijf daarna de opnamen uit als partituur:

```bash
./transcribe_midi.sh --split-sections
```

Het script herkent de noten met Transkun en maakt daar een partituur van.
Met `--split-sections` verwerkt het voorspel, koraal en naspel afzonderlijk,
zodat elk deel zijn eigen tempo en maatsoort kan krijgen.

De ruwe herkende noten komen in `midi_raw/`. De MusicXML-partituren en opgeschoonde MIDI
staan in `midi/`. Open voor de bladmuziek de MusicXML in MuseScore 4.

De [transcriptiehandleiding](docs/transcriptie.md) beschrijft de opties, handmatige snijpunten,
maatsoorten en toonsoorten. Daar staan ook de uitleg van de berekeningen en de extra
installatiestap voor het optionele ByteDance-model.

Orgelopnamen vragen een ander model en een andere opschoning, vanwege registers, 16'-pedaal en kerkgalm.
De map [orgelimprovisaties/](orgelimprovisaties/README.md) zet een orgelopname om naar een partituur
op drie balken: twee manualen en pedaal.

## De harmonie controleren en de begeleiding aanpassen

Je kunt de partituren in `midi/` laten toetsen aan de regels van de klassieke koraalzetting:

```bash
.venv/bin/python controleer_harmonie.py
```

De gemarkeerde partituren staan in `midi_controle/`. Betrokken noten zijn rood,
met de regelcode eronder. De [uitleg van de controle](docs/harmoniecontrole.md) beschrijft
wat de codes betekenen, welke bronnen zijn gebruikt en wat de controle niet kan beoordelen.
Een melding kan ook ontstaan door een transcriptiefout of door gangbare pianopraktijk,
zoals een wijde ligging. Bekijk daarom de partituur voordat je een noot corrigeert.

Het script schrijft ook een verzamelrapport met de aantallen meldingen per code en per stuk.
Voor de vier meegeleverde voorbeelden staat dat rapport in
[voorbeelden/harmonie_controle.md](voorbeelden/harmonie_controle.md).

Om de binnenstemmen te laten aanpassen met behoud van melodie en bas, gebruik je:

```bash
.venv/bin/python corrigeer_harmonie.py
```

De gewijzigde noten worden groen en de resterende meldingen rood.
De uitvoer staat in `midi_gecorrigeerd/`.
Met `hypercorrectie.py` mag ook de bas veranderen, terwijl de melodie vast blijft.
De [handleiding voor herzetten](docs/herzetten.md) legt beide methoden uit,
inclusief zoektijd, hervatten en de betekenis van de status `volledig`.
Minder regelmeldingen betekent op zichzelf niet dat de muziek beter klinkt.

## De stijlanalyse lezen

[stijlanalyse.md](stijlanalyse.md) beschrijft Koeles pianospel op basis van automatische metingen
over alle 49 opnamen: vorm, akkoordvocabulaire, cadensen, modulaties, slot en speelwijze.
Het document geeft zelf aan welke metingen betrouwbaar zijn en welke met voorbehoud te lezen zijn.
De [transcriptiehandleiding](docs/transcriptie.md#stap-3--analyse_stijlpy-stijlanalyse)
beschrijft hoe je de analyse zelf uitvoert en welke gegevens het script verzamelt.

## Voorbeelden

In [voorbeelden/](voorbeelden/) staan vier uitgewerkte transcripties:

| Stuk | Wat laat het voorbeeld zien? |
|---|---|
| Psalm 85 | Splitsing in delen met de maatsoorten 4/4 → 3/2 → 4/4. |
| Psalm 37 | Splitsing in delen met de maatsoorten 3/4 → 4/4 → 4/4. |
| De Lofzang van Maria | Correctie van parallelle octaven. |
| U zij de glorie | Toonsoortwisselingen en correctie van verdubbelde leidtonen. |

Bij elk stuk vind je de audio, de oorspronkelijke MusicXML-partituur, de gemarkeerde controle
en de gecorrigeerde versie. De [toelichtingen per stuk](voorbeelden/readmes/) bevatten links
naar de oorspronkelijke YouTube-uitvoeringen. De rapporten van de controle en de correctie
staan in dezelfde map. Ook zijn er [versies met een aangepaste bas](voorbeelden/hypercorrectie/),
met een [rapport over de hypercorrectie](voorbeelden/hypercorrectie/hypercorrectie.md).

## Eigen pianozettingen maken

De map [koele/](koele/) bevat de scripts waarmee eigen zettingen van liederen worden gebouwd:
van een tekstbron met melodie, liedtekst en vierstemmige pianozetting naar MuseScore en PDF,
met gitaarakkoorden boven de pianobalk. Dezelfde regelcontrole als hierboven toetst de stemvoering.
De liederen zelf zijn niet meegeleverd. De [toelichting](koele/README.md) beschrijft het invoerformaat
en de scripts.

## Naslag

| Document | Inhoud |
|---|---|
| [Psalmen harmoniseren](harmonisatie/HARMONISATIE.md) | Eigen melodieën invoeren, voorbeelden en beperkingen van de generator. |
| [Transcriptie](docs/transcriptie.md) | Opties, berekeningen, probleemoplossing en afbeeldingen maken met MuseScore. |
| [Harmoniecontrole](docs/harmoniecontrole.md) | Regelcodes, muziektheoretische bronnen en beperkingen van de controle. |
| [Begeleiding herzetten](docs/herzetten.md) | Binnenstemmen aanpassen, hypercorrectie en muzikale voorkeuren. |
| [Stijlanalyse](stijlanalyse.md) | Vorm, harmonie en speelwijze in 49 opnamen, met de betrouwbaarheid van de metingen. |
| [Orgelopnamen](orgelimprovisaties/README.md) | Orgelopnamen omzetten naar een partituur met manualen en pedaal, met een vergelijking van transcriptiemodellen. |
| [Eigen zettingen](koele/README.md) | Liederen vanuit een tekstbron omzetten naar MuseScore en PDF met een eigen pianobegeleiding. |
