"""Controleert de speelbaarheid van de pianozetting: geen hand grijpt meer dan een octaaf (12 halve tonen).

Gebruik (vanuit de liedmap): ../.venv/bin/python ../koele/greep.py [bron/naam.py ...]   (zonder argumenten: alle bronnen)
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]

import maak_partituren as mp  # noqa: E402

SPAN = 12


def spans(sc):
    """Momenten waarop een hand meer dan een octaaf grijpt, als 'RH m5: 14'."""
    uit = []
    for naam, staf in (("RH", sc.parts[-2]), ("LH", sc.parts[-1])):
        ev = []
        for m in staf.getElementsByClass("Measure"):
            for v in m.voices or [m]:
                for n in v.notes:
                    t = m.offset + n.offset
                    ev.append((t, t + n.quarterLength, [p.midi for p in n.pitches], m.number))
        for t in sorted({e[0] for e in ev}):
            klinkt = [p for a, b, ps, _ in ev if a <= t < b for p in ps]
            if klinkt and max(klinkt) - min(klinkt) > SPAN:
                mn = next(e[3] for e in ev if e[0] <= t < e[1])
                uit.append(f"{naam} m{mn}: {max(klinkt) - min(klinkt)}")
    return uit


def main(args):
    bronnen = [Path(a) for a in args] or sorted(Path("bron").glob("*.py"))
    for b in bronnen:
        try:
            sc = mp.bouw(mp.laad(b))
        except Exception as e:
            print(b.stem, "FOUT", str(e)[:80])
            continue
        u = spans(sc)
        print(b.stem, len(u), u[:8])


if __name__ == "__main__":
    main(sys.argv[1:])
