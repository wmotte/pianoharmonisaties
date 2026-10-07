"""Probeert akkoordvarianten voor één maat en meldt welke regelgoed en speelbaar zijn.

Gebruik (vanuit de liedmap):
    ../.venv/bin/python ../koele/probeer.py <naam> <sectie> <maat> '<kandidaat>' ['<kandidaat>' ...]
    bijv. ... probeer.py psalm_100 1 3 'Am7/2 D/2' 'C/2 D/2' 'Am/2 D:F#/2'

<sectie> is de index in "secties" (0 = eerste), <maat> telt vanaf 1 binnen die sectie (maatstrepen in
"akkoorden"). Een kandidaat is de inhoud van die maat in akkoordnotatie. De bron zelf blijft ongewijzigd;
neem een goede kandidaat daarna zelf over in bron/<naam>.py.
"""
import copy
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HIER = Path(__file__).resolve().parent
sys.path[:0] = [str(HIER), str(HIER.parent)]

import maak_partituren as mp  # noqa: E402
import controleer  # noqa: E402
import greep  # noqa: E402
import zetter  # noqa: E402
from harmonie_regels import Score, check  # noqa: E402

STREEP = re.compile(r"(\|\]|\|\||:\||\|:|\|)")


def vervang_maat(akkoorden, maat, nieuw):
    """Vervangt de inhoud van maat <maat> (vanaf 1) in een akkoordenstring."""
    delen = STREEP.split(akkoorden)
    # delen: inhoud, streep, inhoud, streep, ...; een leeg begin ontstaat bij een beginnende |:
    inhoud = [i for i in range(0, len(delen), 2) if delen[i].strip()]
    if not 1 <= maat <= len(inhoud):
        sys.exit(f"maat {maat} bestaat niet (sectie heeft {len(inhoud)} maten)")
    delen[inhoud[maat - 1]] = f" {nieuw} "
    return "".join(delen)


def beoordeel(stuk):
    """Lijst met problemen (leeg = goed): regels, stemmen en greep."""
    tmp = mp.ROOT / "tmp" / "controle"
    tmp.mkdir(parents=True, exist_ok=True)
    xml = tmp / "probeer.musicxml"
    try:
        gezet = zetter.zet_stuk(stuk)
        mp.bouw(gezet, met_zang=False).write("musicxml", fp=xml)
    except Exception as e:
        return [f"FOUT {str(e)[-120:]}"]
    problemen = [f"{f['code']} m{f['measure']}" for f in check(Score(xml))]
    problemen += controleer.stemcontrole(gezet)[0]
    problemen += greep.spans(mp.bouw(gezet))
    return problemen


def main(naam, sectie, maat, *kandidaten):
    mod = mp.laad_module(mp.ROOT / "bron" / f"{naam}.py")
    for k in kandidaten:
        stuk = copy.deepcopy(mod.STUK)
        sec = stuk["secties"][int(sectie)]
        sec["akkoorden"] = vervang_maat(sec["akkoorden"], int(maat), k)
        problemen = beoordeel(stuk)
        print(f"{k!r}: {'ok' if not problemen else '; '.join(problemen[:6])}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
