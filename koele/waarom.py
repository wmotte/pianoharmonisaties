"""Waarom loopt de zetter vast? Herhaalt de zoektocht van zetter.zet_stuk tot het eerste segment zonder
regelgoede verbinding en laat per bereikbare vorige ligging zien welke regel elke kandidaat blokkeert.

Gebruik (vanuit de liedmap): ../.venv/bin/python ../koele/waarom.py <naam>
"""

import inspect
import re
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
HIER = Path(__file__).resolve().parent
sys.path[:0] = [str(HIER.parent), str(HIER)]

from music21 import pitch  # noqa: E402

import maak_partituren as mp  # noqa: E402
import zetter  # noqa: E402


def pn(m):
    return pitch.Pitch(midi=m).nameWithOctave if m is not None else "-"


def main(naam):
    stuk = mp.laad_module(mp.ROOT / "bron" / f"{naam}.py").STUK
    segs = zetter.segmenten(stuk)
    S, teg = zetter.tijdlijn(stuk, "1"), zetter.tijdlijn(stuk, "tegenstem")
    echte = [s for s in segs if s["sym"] not in ("R", "=")]
    # overgang() met de regelnaam als uitkomst in plaats van INF
    bron = inspect.getsource(zetter.overgang)
    regel = {str(m.start()): bron[:m.start()].rstrip().split("\n")[-1].strip()[:70]
             for m in re.finditer(r"return INF", bron)}
    ns = dict(zetter.__dict__)
    exec(re.sub(r"return INF", lambda m: f"return {m.start()!r}", bron), ns)
    vl = vseg = None
    for seg in echte:
        kand = zetter.kandidaten(seg, S, teg)
        if not kand:
            print(f"geen ligging voor {seg['sym']} in sectie {seg['sec'] + 1} maat {seg['maat'] + 1}")
            return
        laag = {}
        for st, k in kand:
            if vl is None:
                laag[st] = k
            else:
                laag[st] = min((vk + k + zetter.overgang(vst, st, vseg, seg, S, teg)
                                for vst, vk in vl.items() if vk < zetter.INF), default=zetter.INF)
        if all(v == zetter.INF for v in laag.values()):
            print(f"vast: {vseg['sym']} -> {seg['sym']} (sectie {seg['sec'] + 1}, maat {seg['maat'] + 1})")
            print("  melodie:", [(float(on), float(end), pn(m)) for on, end, m in S if on < seg["end"] and end > vseg["on"]])
            print("  tegenstem:", [(float(on), float(end), pn(m)) for on, end, m in teg if on < seg["end"] and end > vseg["on"]])
            print("  kandidaten:", [" ".join(map(pn, st)) for st, k in kand])
            for vst, vk in vl.items():
                if vk == zetter.INF:
                    continue
                c = Counter()
                for st, k in kand:
                    r = ns["overgang"](vst, st, vseg, seg, S, teg)
                    c[regel[str(r)] if isinstance(r, int) else "ok"] += 1
                print("  van", " ".join(map(pn, vst)), dict(c))
            return
        vl, vseg = laag, seg
    print("geen blokkade")


if __name__ == "__main__":
    main(sys.argv[1])
