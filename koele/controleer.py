"""Controleer de pianozetting en de tegenstem van de bronnen in bron/*.py.

1. Pianozetting (sopraan, alt, tenor, bas) met harmonie_regels.check uit de repo:
   parallellen, verborgen kwinten/octaven, leidtoon, septiem, none, overlap, kruising, ligging, spelling.
   De zachte codes uit harmonie_regels.ZACHT (verdubbelde terts, kale kwint, verborgen parallel
   tegen een stapsgewijze bas, none, verminderde naar reine kwint, overlap) zijn stijlkeuzes of
   'niet absolute' regels en gaan naar de waarschuwingen (LET OP); zetter.py sluit overlap zelf al uit.
2. Per stem (op naam, niet op toonhoogte) parallelle kwinten en octaven tussen alle paren, inclusief
   de tegenstem tegen elke pianostem, en kruising van de tegenstem onder de melodie.
3. Dissonanten van de tegenstem: een tegenstemnoot die op zijn inzet een kleine secunde of grote
   septiem vormt met een pianonoot (waarschuwing: doorgangs- en wisselnoten kunnen terecht zijn).
4. Leidtoon in de tegenstem: de tegenstem is de hoogste stem, dus de terts van een majeurakkoord dat
   naar het akkoord een kwart hoger gaat (V -> I, ook tussendominanten) moet stapsgewijs omhoog of
   blijven liggen (Hooning 5e: afspringen alleen in een middenstem). Waarschuwing.

Gebruik (vanuit de liedmap): ../.venv/bin/python ../koele/controleer.py [naam ...]
Afsluitcode 1 als er meldingen uit stap 1 of 2 zijn.
"""

import sys
import warnings
from fractions import Fraction
from pathlib import Path

warnings.filterwarnings("ignore")
HIER = Path(__file__).resolve().parent
REPO = HIER.parent
sys.path[:0] = [str(REPO), str(HIER)]

from music21 import key, pitch  # noqa: E402

import maak_partituren as mp  # noqa: E402
from harmonie_regels import ZACHT, Score, check  # noqa: E402

STAP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(p):
    stap, alter, octaaf = p
    return 12 * (octaaf + 1) + STAP[stap] + alter


def tijdlijnen(stuk):
    """Per stemnaam een lijst (inzet, einde, midi, maatnummer, tel); overbonden noten samengevoegd."""
    uit = {}
    t0 = Fraction(0)
    nummer = 0 if stuk["secties"][0].get("opmaat") else 1
    for sec in stuk["secties"]:
        ks = key.KeySignature(sec["toonsoort"])
        stemmen, maatsoorten, lengtes = mp.sectie_maten(stuk, sec, ks)
        for s, maten in stemmen.items():
            lijst = uit.setdefault(s, [])
            t = t0
            vorig_tie = False
            for i, maat in enumerate(maten):
                tm = t
                for soort, p, dur, mods in maat["elems"]:
                    if soort == "noot":
                        m = midi(p)
                        if vorig_tie and lijst and lijst[-1][2] == m and lijst[-1][1] == t:
                            lijst[-1] = (lijst[-1][0], t + dur, m, lijst[-1][3], lijst[-1][4])
                        else:
                            lijst.append((t, t + dur, m, nummer + i, float(t - tm) + 1))
                        vorig_tie = "~" in mods
                    else:
                        vorig_tie = False
                    t += dur
        t0 += sum(lengtes)
        nummer += len(lengtes)
    return uit


def klinkt(lijst, t):
    for on, end, m, maat, tel in lijst:
        if on <= t < end:
            return on, m, maat, tel
    return None


def stemcontrole(stuk):
    lijnen = tijdlijnen(stuk)
    namen = [s for s in ("tegenstem", "1", "2", "3", "4") if s in lijnen]
    inzetten = sorted({n[0] for s in namen for n in lijnen[s]})
    meldingen, waarschuwingen = [], []
    vorige = None
    for t in inzetten:
        nu = {s: klinkt(lijnen[s], t) for s in namen}
        if vorige:
            for a in range(len(namen)):
                for b in range(a + 1, len(namen)):
                    sa, sb = namen[a], namen[b]
                    if {sa, sb} == {"tegenstem", "1"}:
                        continue  # melodie en tegenstem komen uit de bron
                    if not all((vorige[sa], vorige[sb], nu[sa], nu[sb])):
                        continue
                    if vorige[sa][1] == nu[sa][1] or vorige[sb][1] == nu[sb][1]:
                        continue
                    i1 = abs(vorige[sa][1] - vorige[sb][1])
                    i2 = abs(nu[sa][1] - nu[sb][1])
                    for iv, naam in ((7, "kwinten"), (0, "octaven")):
                        if i1 % 12 == iv and i2 % 12 == iv:
                            if naam == "octaven" and i1 == 0 and i2 == 0:
                                naam = "priemen"
                            m, tel = nu[sa][2], nu[sa][3]
                            meldingen.append(f"maat {m} tel {tel:g}: parallelle {naam} {stemnaam(sa)}-{stemnaam(sb)} "
                                             f"({pn(vorige[sa][1])}/{pn(vorige[sb][1])} -> {pn(nu[sa][1])}/{pn(nu[sb][1])})")
        if "tegenstem" in namen and nu["tegenstem"] and nu["tegenstem"][0] == t:
            tg = nu["tegenstem"][1]
            m, tel = nu["tegenstem"][2], nu["tegenstem"][3]
            for s in ("1", "2", "3", "4"):
                if nu.get(s) and abs(tg - nu[s][1]) % 12 in (1, 11):
                    waarschuwingen.append(f"maat {m} tel {tel:g}: tegenstem {pn(tg)} wrijft met {stemnaam(s)} {pn(nu[s][1])}")
        vorige = nu
    return meldingen, waarschuwingen


def tegenstem_leidtonen(stuk):
    """Waarschuwingen: leidtoon in de tegenstem (terts van een majeurakkoord vóór V -> I) die niet
    stapsgewijs omhoog oplost of blijft liggen."""
    if not any("tegenstem" in sec and "akkoorden" in sec for sec in stuk["secties"]):
        return []
    import zetter
    teg = zetter.tijdlijn(stuk, "tegenstem")
    segs = [s for s in zetter.segmenten(stuk) if s["akk"] is not None]
    uit = []
    for a, b in zip(segs, segs[1:]):
        akk, volg = a["akk"], b["akk"]
        if not (akk.majeur and (volg.root - akk.root) % 12 == 5 and b["on"] == a["end"]):
            continue
        n1, n2 = zetter.klinkt(teg, b["on"], voor=True), zetter.klinkt(teg, b["on"])
        if n1 is None or n2 is None or n1 % 12 != akk.terts or n2 - n1 in (0, 1):
            continue
        maat, tel = _maat_tel(stuk, b["on"])
        uit.append(f"maat {maat} tel {tel:g}: leidtoon {pn(n1)} in tegenstem ({a['sym']} -> {b['sym']}) "
                   f"gaat naar {pn(n2)}, verwacht {pn(n1 + 1)}")
    return uit


def _maat_tel(stuk, t):
    """Absolute tijd -> (maatnummer, tel) zoals de partituur telt."""
    t0 = Fraction(0)
    nummer = 0 if stuk["secties"][0].get("opmaat") else 1
    for sec in stuk["secties"]:
        _, _, lengtes = mp.sectie_maten(stuk, sec, key.KeySignature(sec["toonsoort"]))
        for i, L in enumerate(lengtes):
            if t0 <= t < t0 + L:
                return nummer + i, float(t - t0) + 1
            t0 += L
        nummer += len(lengtes)
    return nummer, 1.0


def stemnaam(s):
    return {"tegenstem": "tegenstem", "1": "S", "2": "A", "3": "T", "4": "B"}[s]


def pn(m):
    return pitch.Pitch(midi=m).nameWithOctave


def controleer_bron(b):
    """Regelcontrole (harmonie_regels) en stemcontrole van één bron: (regels, meldingen, waarschuwingen)."""
    tmp = mp.ROOT / "tmp" / "controle"
    tmp.mkdir(parents=True, exist_ok=True)
    stuk = mp.laad(b)
    xml = tmp / f"{b.stem}_piano.musicxml"
    mp.bouw(stuk, met_zang=False).write("musicxml", fp=xml)
    alle = check(Score(xml))
    regels = [f for f in alle if f["code"] not in ZACHT]
    meldingen, waarschuwingen = stemcontrole(stuk)
    waarschuwingen += tegenstem_leidtonen(stuk)
    waarschuwingen += [f"maat {f['measure']} tel {f['beat']:g}: {f['code']} {f['note']} ({f['staff']}): {f['detail']}"
                       for f in alle if f["code"] in ZACHT]
    return regels, meldingen, waarschuwingen


def main(namen):
    bronnen = sorted((mp.ROOT / "bron").glob("*.py"))
    if namen:
        bronnen = [b for b in bronnen if b.stem in namen]
    fout = False
    for b in bronnen:
        regels, meldingen, waarschuwingen = controleer_bron(b)
        print(f"== {b.stem}: {len(regels)} regelmeldingen, {len(meldingen)} stemmeldingen, "
              f"{len(waarschuwingen)} waarschuwingen")
        for f in regels:
            print(f"  REGEL maat {f['measure']} tel {f['beat']:g} {f['code']} {f['note']} ({f['staff']}): {f['detail']}")
        for m in meldingen:
            print(f"  STEM  {m}")
        for w in waarschuwingen:
            print(f"  LET OP {w}")
        fout |= bool(regels or meldingen)
    sys.exit(1 if fout else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
