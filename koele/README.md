# Eigen pianozettingen in de stijl van Gerrit Koele

De scripts in deze map zetten een lied om naar MuseScore (`.mscz`) en PDF, met een eigen vierstemmige
pianobegeleiding en gitaarakkoorden boven de bovenste pianobalk. De stemvoering wordt getoetst aan
dezelfde regels als de harmoniecontrole in de hoofdmap (`harmonie_regels.py`).

## Invoer

Elk lied is een Python-bestand in de map `bron/` van een liedmap. Het bevat de zangmelodie met tekst,
eventueel een tegenstem, en de vier stemmen van de pianozetting in een korte tekstnotatie.
Zo staat `Bb3/4` voor een bes in het kleine octaaf als kwartnoot, `R/4` voor een kwartrust en
`M6/4` vooraan in een maat voor een maatwissel. Per sectie zijn verder tempo, opmaat, volta’s en
herhalingstekens op te geven. Het volledige formaat staat in de docstring van `maak_partituren.py`.
De liedmappen zelf zijn niet meegeleverd.

## Gebruik

Draai de scripts vanuit een liedmap met `bron/`:

```sh
cd <liedmap>
../.venv/bin/python ../koele/maak_partituren.py [naam ...]
```

De uitvoer komt in `musescore/`, `pdf/` en `tmp/` in de liedmap. Voor de PDF is MuseScore 4 nodig;
het pad naar MuseScore staat bovenaan `maak_partituren.py`.

| Script | Doel |
|---|---|
| `maak_partituren.py` | Bouwt MusicXML, MuseScore-bestand en PDF en draait alle controles: regels, stemcontrole, greep, grijze rusten en opmaak. Exitcode 1 bij problemen. Opties: `--alleen-xml`, `--zonder-controle`. Na het renderen worden de regels over de pagina’s in balans gebracht. |
| `zetter.py` | Zet alt, tenor en bas bij een gegeven akkoordenreeks. Parallellen, overlap, grote sprongen en verborgen kwinten zijn harde eisen; de oplossing van septiem en leidtoon weegt zwaar mee. Zachte kosten houden de tenor binnen het bereik van de rechterhand. |
| `controleer.py` | Regel- en stemcontrole per bron, ook los te draaien. Zachte codes uit `harmonie_regels.ZACHT` verschijnen als `LET OP` en keuren de zetting niet af. |
| `greep.py` | Speelbaarheid: geen hand grijpt meer dan een octaaf. |
| `opmaak.py` | Lay-out: geen regel met één uitgerekte maat, geen te korte laatste regel, pagina’s in balans met hoogstens één regel verschil. Leest positie en breedte per maat uit de MuseScore-export. |
| `probeer.py` | Toetst akkoordvarianten voor één maat zonder de bron te wijzigen. |
| `waarom.py` | Laat bij een verbinding zonder regelgoede oplossing zien welke regel elke kandidaat blokkeert. |
| `kleurstats.py` | Aandeel kleurakkoorden en omkeringen per bron. |
| `transponeer.py` | Transponeert een bron, stemmen en akkoorden. |
| `stijl.mss` | MuseScore-stijl voor alle partituren. |

## Gitaarakkoorden

De akkoordsymbolen volgen de gekozen harmonisatie en de werkelijk gezette bas; bij een omkering staat
een slashakkoord. Elke maat krijgt een symbool, binnen een maat verschijnen alleen gewijzigde harmonieën.
Kleurakkoorden blijven behouden; doorgangsnoten en arpeggio’s krijgen geen eigen symbool.

## Werkwijze en privémateriaal

De werkwijze en stijlkeuzes achter de zettingen staan in de skill
[`koele-pianozetting`](../.agents/skills/koele-pianozetting/SKILL.md).
Liedmappen en bladmuziek horen niet in deze repository. De hook `.githooks/pre-commit`
weigert zulke commits; activeer hem met `git config core.hooksPath .githooks`.
