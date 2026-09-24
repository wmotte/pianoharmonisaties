"""Welke akkoordtonen verdwijnen bij een reductie, en zijn dat vultonen of kleurtonen?

    .venv/bin/python .agents/skills/vierstemmig-reduceren/scripts/kleurtonen.py origineel.musicxml reductie.musicxml

Het venster is een tel. Een toon telt als aanwezig in de reductie als hij daar *ergens binnen die tel*
klinkt, in welke stem ook: twee tonen na elkaar suggereren samen ook het akkoord. Het akkoordlabel komt
uit alle tonen van het origineel in die tel die minstens een halve tel klinken (doorgangstonen tellen
niet mee). Wat in de reductie ontbreekt, krijgt een categorie:

    KERN   grondtoon, terts, septiem
    VUL    reine kwint
    KLEUR  al het andere: verminderde/overmatige kwint, verminderde septiem, none, sext, kwart
"""
import sys
from pathlib import Path

from music21 import converter

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from analyse_stijl import TEMPLATES, label_chord  # noqa: E402

NAMES = {0: "grondtoon", 1: "kleine none", 2: "none", 3: "terts", 4: "terts", 5: "kwart", 6: "verminderde kwint",
         7: "kwint", 8: "overmatige kwint/kleine sext", 9: "sext", 10: "septiem", 11: "grote septiem"}
MIN_SCORE = 2.0  # zelfde drempel als harmonie_regels.LABEL_MIN_SCORE


def verticals(path):
    """[(t0, t1, maat, tel, pcs, namen, baspc)] uit de akkoordreductie van de partituur."""
    out = []
    for m in converter.parse(path).chordify().getElementsByClass("Measure"):
        for c in m.notes:
            t0 = float(m.offset + c.offset)
            out.append((t0, t0 + float(c.quarterLength), m.number, float(c.offset) + 1,
                        {p.pitchClass for p in c.pitches}, {p.pitchClass: p.name.replace('-', '♭') for p in c.pitches},
                        c.bass().pitchClass))
    return out


def category(iv):
    """Grondtoon, terts en septiem dragen het akkoord; de reine kwint is vulling; al het andere is kleur."""
    return "VUL" if iv == 7 else "KERN" if iv in (0, 3, 4, 10, 11) else "KLEUR"


def beats(vs):
    """{(maat, tel, absolute tel): [(t0, t1, pcs, namen, baspc)]}, verticalen geknipt op de tel."""
    out = {}
    for t0, t1, mnum, b, pcs, names, bass in vs:
        mstart, t = t0 - (b - 1), t0
        while t < t1 - 1e-9:
            k = int(t + 1e-9)
            e = min(t1, k + 1.0)
            out.setdefault((mnum, int(t - mstart + 1e-9) + 1, k), []).append((t, e, pcs, names, bass))
            t = e
    return out


def main(orig, red):
    ob, rb = beats(verticals(orig)), beats(verticals(red))
    rpcs = {k[2]: set().union(*[x[2] for x in v]) for k, v in rb.items()}
    counts = {"KLEUR": 0, "KERN": 0, "VUL": 0}
    prev = set()
    for (mnum, tel, idx), vs in sorted(ob.items(), key=lambda kv: kv[0][2]):
        dur, spell = {}, {}
        for t0, t1, pcs, names, _ in vs:
            for pc in pcs:
                dur[pc] = dur.get(pc, 0) + t1 - t0
                spell[pc] = names[pc]
        core = {pc for pc, d in dur.items() if d >= 0.5}
        root, name, sc = label_chord(core, vs[0][4])
        if sc < MIN_SCORE:
            prev = set()
            continue
        tpl = {(root + x) % 12 for x in TEMPLATES[name]}
        tones = core | (tpl & set(dur))
        cur = set()
        for pc in sorted(tones - rpcs.get(idx, set()), key=lambda pc: (pc - root) % 12):
            iv = (pc - root) % 12
            cat = category(iv)
            key = (root, name, pc)
            cur.add(key)
            if key in prev:  # zelfde verlies als de vorige tel: niet herhalen
                continue
            counts[cat] += 1
            nm = "verminderde septiem" if (name, iv) == ("dim7", 9) else NAMES[iv]
            print(f"m{mnum} tel {tel}\t{cat}\t{spell[pc]} ({nm}) valt weg in {name} op {spell.get(root, root)}")
        prev = cur
    print(counts)


if __name__ == "__main__":
    main(*sys.argv[1:3])
