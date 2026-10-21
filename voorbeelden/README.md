# Voorbeelden: vier transcripties

Deze map bevat vier uitgewerkte transcripties van opnamen van Gerrit Koele. Per stuk staan hier de
audio, de partituur direct na transcriptie, de gemarkeerde harmoniecontrole en de versie met herzette
binnenstemmen.

| Stuk | Wat laat het voorbeeld zien? | Opname | Toelichting |
|---|---|---|---|
| Psalm 85 | Splitsing in delen met de maatsoorten 4/4 → 3/2 → 4/4. | [YouTube](https://www.youtube.com/watch?v=qfzzrg627Ho) | [psalm_85.md](readmes/psalm_85.md) |
| Psalm 37 | Splitsing in delen met de maatsoorten 3/4 → 4/4 → 4/4, genoteerd met twee mollen (C-dorisch). | [YouTube](https://www.youtube.com/watch?v=b9ReiRKeBxg) | [psalm_37.md](readmes/psalm_37.md) |
| De Lofzang van Maria | Correctie van parallelle octaven. | [YouTube](https://www.youtube.com/watch?v=e8Sz1o3a8pA) | [de_lofzang_van_maria.md](readmes/de_lofzang_van_maria.md) |
| U zij de glorie | Toonsoortwisselingen en correctie van verdubbelde leidtonen. | [YouTube](https://www.youtube.com/watch?v=i7hRZbaeYpw) | [u_zij_de_glorie.md](readmes/u_zij_de_glorie.md) |

## Mapindeling

- `readmes/`: toelichting per stuk, met de bestandsnamen en de link naar de opname.
- `mp3/`: de van YouTube gedownloade audio.
- `ongecorrigeerd/`: MusicXML direct na transcriptie en opschoning.
- `controle/`: MusicXML van de harmoniecontrole. De betrokken noten zijn rood, met de regelcode onder
  de noot. Het tekstbestand ernaast bevat alle meldingen met maat en tel.
- `gecorrigeerd/`: MusicXML na herzetting van de binnenstemmen, met melodie en bas ongewijzigd.
  Gewijzigde noten zijn groen, met de oorspronkelijke noot als toelichting; resterende meldingen zijn rood.
- `hypercorrectie/`: zettingen waarin de melodie vastligt en ook de bas mag veranderen.

Open de MusicXML-bestanden in MuseScore 4 om ze te bekijken en af te spelen.

## Rapporten

- [harmonie_controle.md](harmonie_controle.md): meldingen per code en per stuk vóór de herzetting
  ([JSON](harmonie_controle.json)).
- [harmonie_correctie.md](harmonie_correctie.md): gewijzigde noten en meldingen per code vóór en na de
  herzetting van de binnenstemmen ([JSON](harmonie_correctie.json)).
- [hypercorrectie/hypercorrectie.md](hypercorrectie/hypercorrectie.md): resultaat van de hypercorrectie
  en de acceptatiecriteria ([JSON](hypercorrectie/hypercorrectie.json)).

De betekenis van de regelcodes staat in de [uitleg van de controle](../docs/harmoniecontrole.md).
Een melding is geen fout in de uitvoering: ze kan ook ontstaan door een transcriptiefout of door
gangbare pianopraktijk, zoals een wijde ligging. Minder meldingen betekent niet vanzelf dat de muziek
beter klinkt.

De controle en de correctie zijn vanuit de hoofdmap te herhalen met:

```bash
.venv/bin/python controleer_harmonie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/controle --report-dir voorbeelden --force
.venv/bin/python corrigeer_harmonie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/gecorrigeerd --report-dir voorbeelden --force
```

De hypercorrectie heeft een tijdslimiet per stuk; zie de [handleiding voor herzetten](../docs/herzetten.md).
