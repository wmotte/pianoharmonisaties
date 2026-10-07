"""Controleert de opmaak van de PDF's: per systeem (regel) hoe breed en hoeveel maten.

Meldt systemen met weinig maten op de volle breedte (lege uitgerekte regels) en een te korte laatste regel.

Gebruik: ../.venv/bin/python ../koele/opmaak.py ["pdf/<bestand>.pdf" ...]   (zonder argumenten: alle PDF's)
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path.cwd()  # de liedmap
DPI = 50


def systemen(png):
    """Lijst (y, breedte, maten) per systeem: notenbalken = rijen met een lange donkere lijn."""
    im = Image.open(png).convert("L")
    w, h = im.size
    px = im.load()
    rijen = []
    for y in range(h):
        x0 = next((x for x in range(w) if px[x, y] < 128), None)
        if x0 is None:
            continue
        x1 = next(x for x in range(w - 1, -1, -1) if px[x, y] < 128)
        donker = sum(1 for x in range(x0, x1 + 1) if px[x, y] < 128)
        if x1 - x0 > w * 0.2 and donker > 0.9 * (x1 - x0):
            rijen.append((y, x0, x1))
    # balklijnen groeperen tot systemen (grote verticale sprong = nieuw systeem)
    groepen = []
    for r in rijen:
        if groepen and r[0] - groepen[-1][-1][0] < DPI * 0.9:
            groepen[-1].append(r)
        else:
            groepen.append([r])
    uit = []
    for g in groepen:
        x0, x1 = min(r[1] for r in g), max(r[2] for r in g)
        ys = sorted({r[0] for r in g})
        # onderste notenbalk: de laatste 5 lijnen (dikke lijnen kunnen 2 pixelrijen beslaan)
        lijnen = []
        for y in ys:
            if not lijnen or y - lijnen[-1] > 1:
                lijnen.append(y)
        ys = lijnen[-5:]
        # maatstrepen: kolommen die over de hele hoogte van die balk donker zijn
        strepen, vorige = 0, -10
        for x in range(x0 + 2, x1 + 1):
            if all(px[x, y] < 128 for y in range(min(ys), max(ys) + 1, 2)) and x - vorige > 3:
                strepen += 1
                vorige = x
        uit.append((min(ys), x1 - x0, strepen))
    return uit, w


def controleer(pdf):
    meldingen = []
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", str(DPI), "-png", str(pdf), f"{d}/p"], check=True)
        paginas = sorted(Path(d).glob("p-*.png"))
        vol = None
        for pi, png in enumerate(paginas, 1):
            sys_, w = systemen(png)
            vol = vol or max((b for _, b, _ in sys_), default=w)
            for si, (y, breed, maten) in enumerate(sys_, 1):
                laatste = pi == len(paginas) and si == len(sys_)
                if laatste and breed < 0.5 * vol:
                    meldingen.append(f"p{pi} regel {si}: laatste regel kort ({breed / vol:.0%})")
                elif breed > 0.9 * vol and maten <= 2:
                    meldingen.append(f"p{pi} regel {si}: {maten} maat/maten op volle breedte")
    return meldingen


def main(args):
    pdfs = [Path(a) for a in args] or sorted((ROOT / "pdf").glob("*.pdf"))
    for pdf in pdfs:
        m = controleer(pdf)
        print(f"{pdf.stem}: {'ok' if not m else '; '.join(m)}")


if __name__ == "__main__":
    main(sys.argv[1:])
