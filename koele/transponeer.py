"""Transponeert een bron (bron/<naam>.py) in place: noten, akkoorden en toonsoort.

Gebruik: ../.venv/bin/python ../koele/transponeer.py <naam> <interval> <toonaard> <toonsoort>
    bijv.  ../koele/transponeer.py psalm_134 M2 F -1     (Es -> F)
           ../koele/transponeer.py psalm_134 -m2 D 2     (Es -> D)

Interval in music21-notatie (M2, -m2, P4, ...). Werkt regel voor regel: noten worden alleen in
stemvelden (melodie, tegenstem, "1".."4") omgezet, akkoordsymbolen alleen in "akkoorden"; tekst blijft
ongemoeid. Maak eerst een back-up in tmp/.
"""
import re
import sys
from pathlib import Path

from music21 import interval, pitch

ROOT = Path.cwd()  # de liedmap
STEMMEN = ("melodie", "tegenstem", "1", "2", "3", "4")
NOOT = re.compile(r"(?<![A-Za-z])([A-G])([#bn]?)(-?\d)(?=[/~^ |\"]|$)")
AKKOORD = re.compile(r"(?<![A-Za-z#])([A-G])([#b]?)(?=[a-z0-9/:]|$)")


def naam(p):
    return p.name.replace("-", "b")


def zet_noot(m, iv):
    p = pitch.Pitch(m.group(1) + m.group(2).replace("b", "-").replace("n", "") + m.group(3))
    q = iv.transposePitch(p)
    voorteken = q.accidental.modifier.replace("-", "b") if q.accidental and q.accidental.alter else ""
    return f"{q.step}{voorteken}{q.octave}"


def zet_grond(m, iv):
    p = pitch.Pitch(m.group(1) + m.group(2).replace("b", "-") + "4")
    return naam(iv.transposePitch(p))


def main(bron, iv_naam, toonaard, toonsoort):
    iv = interval.Interval(iv_naam)
    pad = ROOT / "bron" / f"{bron}.py"
    uit, veld = [], None
    for regel in pad.read_text().splitlines(keepends=True):
        sleutel = re.match(r'\s*"([^"]+)":', regel)
        if sleutel:
            veld = sleutel.group(1)
        elif re.match(r"\s*[}\]]", regel) or re.match(r"\s*[A-Z_0-9]+ = ", regel):
            veld = None
        if re.match(r"\s*[A-Z_0-9]+ = ", regel):
            veld = "melodie"  # module-constanten zijn melodiefragmenten
        if veld == "toonsoort":
            regel = re.sub(r'"toonsoort": -?\d+', f'"toonsoort": {toonsoort}', regel)
        elif veld == "toonaard":
            regel = re.sub(r'"toonaard": "[^"]*"', f'"toonaard": "{toonaard}"', regel)
        elif veld in STEMMEN:
            regel = re.sub(r'"[^"]*"', lambda s: NOOT.sub(lambda m: zet_noot(m, iv), s.group(0))
                           if s.group(0) != f'"{veld}"' else s.group(0), regel)
        elif veld == "akkoorden":
            regel = re.sub(r'"[^"]*"', lambda s: AKKOORD.sub(lambda m: zet_grond(m, iv), s.group(0))
                           if s.group(0) != '"akkoorden"' else s.group(0), regel)
        uit.append(regel)
    pad.write_text("".join(uit))


if __name__ == "__main__":
    main(*sys.argv[1:])
