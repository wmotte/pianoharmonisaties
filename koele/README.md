# koele — pianozettingen in de stijl van Gerrit Koele

Gereedschap om liederen uit `bron/*.py` om te zetten naar MuseScore (`.mscz`) en PDF met een eigen,
regelgecontroleerde pianobegeleiding. De liederen zelf staan in privémappen (`muziekgroep_<datum>/`, gitignored);
werkwijze en stijlkeuzes staan in de skill `.agents/skills/koele-pianozetting/SKILL.md`.
Gitaarakkoorden staan boven de bovenste pianobalk en volgen de eigen harmonisatie plus de werkelijk gezette
bas (slashakkoorden bij omkeringen). Elke maat geeft houvast; binnen een maat verschijnen alleen gewijzigde
harmonieën. Kleurakkoorden blijven behouden, doorgangsnoten en arpeggio's krijgen geen extra symbolen.

Alle scripts draai je vanuit een liedmap met `bron/`:

```sh
cd muziekgroep_11_oct
../.venv/bin/python ../koele/maak_partituren.py [naam ...]   # bouwen + alle controles
```

| Script | Doel |
|---|---|
| `maak_partituren.py` | Bouwt XML, MuseScore en PDF; draait regels, stemcontrole, greep, grijze rusten en opmaak. Exit 1 bij problemen. Opties: `--alleen-xml`, `--zonder-controle`. Bronnotatie in de docstring. Na het renderen balanceert `balanceer_paginas()` de regels over de pagina's (zet `"paginas"` en bouwt opnieuw). `vul()` legt per tenornoot de tenor in de rechterhand (melodie + alt + tenor binnen een octaaf) of als samenklank bij de bas. |
| `zetter.py` | Zet alt, tenor en bas bij gegeven akkoorden (`"akkoorden"`): parallellen, overlap, sprongen en verborgen kwinten als harde eisen; septiem- en leidtoonoplossing als zware zachte kosten; zachte kosten sturen de tenor binnen het bereik van de rechterhand. |
| `controleer.py` | Regel- en stemcontrole per bron (ook los te draaien); zachte codes uit `harmonie_regels.ZACHT` en een leidtoon in de tegenstem die niet stapsgewijs oplost als `LET OP`. |
| `greep.py` | Speelbaarheid: geen hand grijpt meer dan een octaaf. |
| `opmaak.py` | Lay-out: geen regel met één uitgerekte maat, geen te korte laatste regel, pagina's in balans (hoogstens één regel verschil met de volgende pagina). Leest positie, breedte en pagina per maat uit MuseScores mpos-export (`systemen_per_pagina()`); `balans()` berekent waar pagina 2, 3, … moeten beginnen. |
| `probeer.py` | Toetst akkoordvarianten voor één maat zonder de bron te wijzigen. |
| `waarom.py` | Laat bij `geen regelgoede verbinding` zien welke regel elke kandidaat blokkeert. |
| `kleurstats.py` | Aandeel kleurakkoorden en omkeringen per bron. |
| `transponeer.py` | Transponeert een bron (stemmen en akkoorden). |
| `stijl.mss` | MuseScore-stijl voor alle partituren. |

Regels zelf: `harmonie_regels.py` in de repo-root. Commits van liedmappen of bladmuziek worden geweigerd door
`.githooks/pre-commit` (activeren met `git config core.hooksPath .githooks`).
