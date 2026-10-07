"""Telt per bron het aandeel kleurakkoorden en omkeringen (richtlijn Koele: kleur 15-25 %, omkeringen 10-15 %).

Kleur: sus, add, maj7 en septiemakkoorden (m7, 7). Omkering: een bas (na ':') anders dan de grondtoon.
Bijdominanten (V/V, V/vi) telt dit niet: die zijn zonder toonsoortanalyse niet van gewone akkoorden te onderscheiden.

Gebruik (vanuit de liedmap): ../.venv/bin/python ../koele/kleurstats.py [naam ...]   (zonder argumenten: alle bronnen)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import maak_partituren as mp  # noqa: E402

KLEUR = re.compile(r"sus|add|maj7|7")


def tel(stuk):
    akk = [t.rpartition("/")[0] for sec in stuk["secties"] for t in sec.get("akkoorden", "").split() if "/" in t]
    akk = [a for a in akk if a not in ("R", "=")]
    kleur = [a for a in akk if KLEUR.search(a.split(":")[0])]
    omk = [a for a in akk if ":" in a and a.split(":")[1] != re.match(r"[A-G][b#]?", a).group(0)]
    return len(akk), len(kleur), len(omk)


def main(namen):
    bronnen = sorted((mp.ROOT / "bron").glob("*.py"))
    if namen:
        bronnen = [b for b in bronnen if b.stem in namen]
    for b in bronnen:
        n, k, o = tel(mp.laad_module(b).STUK)
        print(f"{b.stem:28} {n:3} akkoorden, kleur {100 * k / n:3.0f} %, omkeringen {100 * o / n:3.0f} %")


if __name__ == "__main__":
    main(sys.argv[1:])
