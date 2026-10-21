"""Controleert de opmaak van de gerenderde partituren: per systeem (regel) hoe breed en hoeveel maten, en per
pagina hoeveel systemen.

Meldt systemen met één maat op de volle breedte (een maat die over de regel heen is geduwd), een te korte
laatste regel en
pagina's die niet in balans zijn (een pagina met twee of meer systemen meer dan de volgende, bijvoorbeeld
vijf regels op pagina 2 en drie op pagina 3). Alles komt uit MuseScores mpos-export van de .mscz: positie,
breedte en pagina per maat. maak_partituren.py gebruikt balans() om de pagina's uit te balanceren.

Gebruik: ../.venv/bin/python ../koele/opmaak.py ["musescore/<bestand>.mscz" ...]   (zonder argumenten: alle)
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()  # de liedmap
MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"


def systemen_per_pagina(mscz):
    """Per pagina een lijst systemen (maatindex van de eerste maat, aantal maten, breedte).
    Maatindex 0 = eerste maat van het stuk (ook een opmaat). Uit MuseScores mpos-export: één element per
    maat met x, y, breedte en pagina; zelfde y op dezelfde pagina = zelfde systeem."""
    with tempfile.TemporaryDirectory() as d:
        mpos = Path(d) / "maten.mpos"
        subprocess.run([MSCORE, "-o", str(mpos), str(mscz)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not mpos.exists():
            raise RuntimeError(f"MuseScore maakte geen mpos-export van {mscz}")
        tekst = mpos.read_text(encoding="utf-8")
    maten = sorted((int(m.group(1)), int(m.group(5)), float(m.group(3)), float(m.group(2)), float(m.group(4)))
                   for m in re.finditer(r'<element id="(\d+)" x="([^"]*)" y="([^"]*)" sx="([^"]*)"[^>]*page="(\d+)"',
                                        tekst))
    paginas, vorige = [], None
    for i, p, y, x, sx in maten:
        while len(paginas) <= p:
            paginas.append([])
        if (p, y) != vorige:
            paginas[p].append([i, 0, x, 0.0])
            vorige = (p, y)
        s = paginas[p][-1]
        s[1] += 1
        s[3] = x + sx - s[2]
    return [[(i, n, breed) for i, n, _, breed in p] for p in paginas]


def balans(paginas):
    """Evenwichtige verdeling van de systemen: een pagina krijgt hoogstens één systeem meer dan de volgende.
    Systemen schuiven alleen naar een latere pagina (de eerste pagina heeft het titelkader en is al vol
    gelegd door MuseScore; een latere pagina kan altijd evenveel systemen aan als een eerdere).
    Geeft de maatindexen waarmee pagina 2, 3, ... moeten beginnen, of [] als de verdeling al goed is."""
    tel = [len(p) for p in paginas]
    oud = list(tel)
    klaar = False
    while not klaar:
        klaar = True
        for i in range(len(tel) - 1):
            if tel[i] - tel[i + 1] >= 2:
                tel[i] -= 1
                tel[i + 1] += 1
                klaar = False
    if tel == oud:
        return []
    systemen = [s[0] for p in paginas for s in p]
    starts, k = [], 0
    for n in tel[:-1]:
        k += n
        starts.append(systemen[k])
    return starts


def controleer(mscz):
    paginas = systemen_per_pagina(mscz)
    meldingen = []
    tel = [len(p) for p in paginas]
    if any(a - b >= 2 for a, b in zip(tel, tel[1:])):
        meldingen.append("pagina's niet in balans: " + ", ".join(f"p{i} {n} regels" for i, n in enumerate(tel, 1)))
    vol = max(breed for p in paginas for _, _, breed in p)
    for pi, p in enumerate(paginas, 1):
        for si, (_, maten, breed) in enumerate(p, 1):
            laatste = pi == len(paginas) and si == len(p)
            if laatste and breed < 0.5 * vol:
                meldingen.append(f"p{pi} regel {si}: laatste regel kort ({breed / vol:.0%})")
            elif breed > 0.9 * vol and maten <= 1:
                meldingen.append(f"p{pi} regel {si}: één maat op volle breedte")
    return meldingen


def main(args):
    bestanden = [Path(a) for a in args] or sorted((ROOT / "musescore").glob("*.mscz"))
    for f in bestanden:
        if f.suffix == ".pdf":
            f = f.parent.parent / "musescore" / f"{f.stem}.mscz"
        m = controleer(f)
        print(f"{f.stem}: {'ok' if not m else '; '.join(m)}")


if __name__ == "__main__":
    main(sys.argv[1:])
