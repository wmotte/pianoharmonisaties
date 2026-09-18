#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Stap 5: de zettingen in midi/ formeel kloppend maken. Melodie (hoogste noot van de rechterhand) en bas
(laagste noot van de linkerhand) blijven staan; de binnenstemmen worden opnieuw gezet met een Viterbi-
zoektocht over alle verticalen, die de regels uit harmonie_regels.py als kosten gebruikt (parallellen,
overlap, kruising, verdubbelde leidtoon, septiemoplossing, ligging) plus stemvoeringsvoorkeuren (kleine
stappen, terts aanwezig, grondtoon verdubbelen) en een straf per gewijzigde noot, zodat Koeles zetting zo
veel mogelijk intact blijft. Daarna wordt de spelling van alle noten op het akkoord/de toonsoort gezet.
Noten verhuizen niet van hand of stem; alleen de toonhoogte verandert.

Uitvoer per stuk:
  midi_gecorrigeerd/<stem>.musicxml   gewijzigde noten groen (tekst: 'was <oude noot>'), resterende fouten rood
  midi_gecorrigeerd/<stem>.txt        resterende meldingen
en harmonie_correctie.md / .json: per stuk en per code het aantal vóór -> na.

Gebruik:
  .venv/bin/python corrigeer_harmonie.py [--only "Psalm 85"] [--beam 12] [--force]
"""
import argparse
import itertools
import json
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

from music21 import pitch  # noqa: E402

from analyse_stijl import TEMPLATES, label_chord  # noqa: E402
from harmonie_regels import (DIR, LABEL_MIN_SCORE, SEVENTH, UNMATCHED, Score, assign_slots, chord_spelling,  # noqa: E402
                             check, leading_tone_pc, mark, report_lines, summary)

OUT = DIR / "midi_gecorrigeerd"
W = dict(P5=3.0, P8=3.0, P1=3.0, AP=2.0, OV=0.5, KR=1.5, S7=1.5, A2=1.0, LIG=2.0, LT2=3.0, HAND=1.0,
         THIRD=2.0, ROOT=1.0, DBL3=0.5, UNIS=0.3, SAME=6.0, STEP=0.15, CHANGE=1.0, DIST=0.05)


# ---- kostenfuncties op eenvoudige tupels (id, midi, staff) ------------------------------------------------
def positions(notes):
    """Gesorteerde lijst van verschillende toonhoogtes -> [(midi, [ids])], en de slotvolgorde B..S."""
    d = []
    for i, m, st in sorted(notes, key=lambda x: x[1]):
        if d and d[-1][0] == m:
            d[-1][1].append(i)
        else:
            d.append([m, [i]])
    return d


def pair_positions(p1, p2):
    """Zelfde koppeling als harmonie_regels.pair_voices, op positielijsten: [(m1, m2, ids1, ids2)]."""
    if not p1 or not p2:
        return []
    pairs = []
    if len(p1) == 1 or len(p2) == 1:  # één noot: koppel aan de dichtstbijzijnde positie aan de andere kant
        a = p1[0] if len(p1) == 1 else min(p1, key=lambda x: abs(x[0] - p2[0][0]))
        b = p2[0] if len(p2) == 1 else min(p2, key=lambda x: abs(x[0] - p1[0][0]))
        return [(a[0], b[0], a[1], b[1])]
    pairs.append((p1[0][0], p2[0][0], p1[0][1], p2[0][1]))  # B
    pairs.append((p1[-1][0], p2[-1][0], p1[-1][1], p2[-1][1]))  # S
    a, b = p1[1:-1], p2[1:-1]
    best = [1e9, []]

    def rec(i, j, cost, acc):
        if cost >= best[0]:
            return
        if i == len(a) or j == len(b):
            cost += UNMATCHED * ((len(a) - i) + (len(b) - j))
            if cost < best[0]:
                best[0], best[1] = cost, acc
            return
        rec(i + 1, j + 1, cost + abs(a[i][0] - b[j][0]), acc + [(a[i][0], b[j][0], a[i][1], b[j][1])])
        rec(i + 1, j, cost + UNMATCHED, acc)
        rec(i, j + 1, cost + UNMATCHED, acc)
    rec(0, 0, 0, [])
    return pairs + best[1]


def vertical_cost(notes, lt_pc, label, orig_pcs, decided, new_ids):
    """notes: [(id, midi, staff)]; kosten van de verticaal zelf."""
    cost = 0.0
    pos = positions(notes)
    staff = {i: st for i, _, st in notes}
    upper = pos[-3:] if len(pos) >= 4 else pos[-2:]
    for (hi, ids_hi), (lo, ids_lo) in zip(upper[::-1], upper[::-1][1:]):  # ligging: alleen binnen één hand en
        if hi - lo > 12 and any(i in new_ids for i in ids_hi + ids_lo) and \
                staff[ids_hi[0]] == staff[ids_lo[0]]:  # alleen bij een nieuwe noot (afstand tussen de handen is pianistisch)
            cost += W["LIG"]
    pcs = Counter(m % 12 for _, m, _ in notes)
    if pcs[lt_pc] >= 2:
        cost += W["LT2"]
    top_l = max((m for _, m, st in notes if st == "L"), default=None)
    if top_l is not None and any(m < top_l for _, m, st in notes if st == "R"):
        cost += W["HAND"]
    root, name, score = label
    if score >= LABEL_MIN_SCORE and name in TEMPLATES:
        tpl = TEMPLATES[name]
        third = (root + tpl[1]) % 12 if name not in ("sus4", "sus2") else None
        if third is not None and third in orig_pcs and pcs[third] == 0:
            cost += W["THIRD"]
        if root in orig_pcs and pcs[root] == 0:
            cost += W["ROOT"]
        if third is not None and pcs[third] >= 2 and name in ("maj", "dom7", "maj7"):
            cost += W["DBL3"]
    if len(pos) >= 2:
        for m, ids in (pos[0], pos[-1]):
            if len(ids) > 1 and any(i in decided for i in ids):
                cost += W["UNIS"]
    same = Counter((m, st) for _, m, st in notes)  # twee keer dezelfde toon in één hand: onnoteerbaar
    cost += W["SAME"] * sum(c - 1 for c in same.values() if c > 1)
    return cost


def transition_cost(prev, cur, prev_label, orig_by_id, decided, new_ids):
    """prev/cur: [(id, midi, staff)]; kosten van de verbinding."""
    cost = 0.0
    p1, p2 = positions(prev), positions(cur)
    pairs = pair_positions(p1, p2)
    # parallellen
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            m1a, m2a, _, ida2 = pairs[a]
            m1b, m2b, _, idb2 = pairs[b]
            if m1a == m2a or m1b == m2b:
                continue
            i1, i2 = abs(m1a - m1b), abs(m2a - m2b)
            if i1 % 12 == 7 and i2 % 12 == 7:
                cost += W["P5"] if i1 == i2 else W["AP"]
            elif i1 % 12 == 0 and i2 % 12 == 0:
                st = {s for i, m, s in cur if i in ida2 + idb2}
                if i1 == 12 and i2 == 12 and st == {"L"} and min(m2a, m2b) == p2[0][0]:
                    continue  # basoctaaf in de linkerhand
                cost += W["P1"] if i1 == 0 else (W["P8"] if i1 == i2 else W["AP"])
    # overlap en kruising van liggende noten
    order = sorted(pairs, key=lambda x: x[1])
    for (m1lo, m2lo, _, idlo), (m1hi, m2hi, _, idhi) in zip(order, order[1:]):
        if m2lo != m1lo and m2lo > m1hi:
            cost += W["OV"]
        if m2hi != m1hi and m2hi < m1lo:
            cost += W["OV"]
    held = [(i, m) for i, m, s in cur if i not in new_ids]
    for m1, m2, ids1, ids2 in pairs:
        if m1 == m2:
            continue
        for hid, hm in held:
            if hid not in ids2 and (m1 < hm) != (m2 < hm) and m2 != hm:
                cost += W["KR"]
    # septiem en melodische intervallen in gewijzigde binnenstemmen
    root1, name1, sc1 = prev_label
    for m1, m2, ids1, ids2 in pairs:
        if sc1 >= LABEL_MIN_SCORE and name1 in SEVENTH and m1 % 12 == (root1 + SEVENTH[name1]) % 12 and m2 - m1 not in (0, -1, -2):
            cost += W["S7"]
        d = abs(m2 - m1)
        if (d > 12 or d == 6) and any(i in decided for i in ids2):
            cost += W["A2"]
        if any(i in decided for i in ids2):
            cost += W["STEP"] * d
    for i, m, s in cur:
        if i in new_ids and m != orig_by_id[i]:
            cost += W["CHANGE"] + W["DIST"] * abs(m - orig_by_id[i])
    return cost


# ---- Viterbi over de verticalen -----------------------------------------------------------------------------
def revoice(sc: Score, beam: int = 12) -> dict:
    """Kiest nieuwe toonhoogtes voor de binnenstemmen; geeft {rec.id: nieuwe midi} voor gewijzigde noten."""
    vs = sc.verticals
    orig = {r.id: r.midi for r in sc.recs}
    by_id = {r.id: r for r in sc.recs}
    # welke noten worden 'beslist' (binnenstem bij hun inzet), welke liggen vast (S/B bij hun inzet)
    decided = set()
    for v in vs:
        outer = {v.slots[s].id for s in ("S", "B") if s in v.slots}
        for r in v.notes:
            if r.on == v.on and r.id not in outer:
                decided.add(r.id)
    # kandidaten per besliste noot
    cands = {}
    for v in vs:
        root, name, score = v.label
        chord_pcs = {(root + x) % 12 for x in TEMPLATES[name]} if score >= LABEL_MIN_SCORE else {r.midi % 12 for r in v.notes}
        lo = v.slots["B"].midi if "B" in v.slots else None
        hi = v.slots["S"].midi if "S" in v.slots else None
        for r in v.notes:
            if r.on != v.on or r.id not in decided:
                continue
            l = lo if lo is not None else hi - 19
            h = hi if hi is not None else lo + 19
            if r.staff == "R":
                l = max(l, (hi if hi is not None else h) - 12)
            else:
                h = min(h, (lo if lo is not None else l) + 15)
            cs = {m for m in range(l, h + 1) if m % 12 in chord_pcs or m == r.midi}
            cs.add(r.midi)
            # hooguit 8 kandidaten, de dichtstbijzijnde bij het origineel
            cands[r.id] = sorted(cs, key=lambda m: abs(m - r.midi))[:8]
    # Viterbi met bundel
    states = [({}, 0.0, None)]  # (toewijzing id->midi van klinkende besliste noten, kosten, backpointer)
    history = []

    def prev_notes(pv, assign):
        return [(r.id, assign.get(r.id, orig[r.id]) if r.id in decided else r.midi, r.staff) for r in pv.notes]

    for vi, v in enumerate(vs):
        lt = leading_tone_pc(v.key)
        orig_pcs = {r.midi % 12 for r in v.notes}
        sounding = [r.id for r in v.notes]
        new_ids = [r.id for r in v.notes if r.on == v.on and r.id in decided]
        fixed = [(r.id, r.midi, r.staff) for r in v.notes if r.id not in decided]
        held_ids = [i for i in sounding if i in decided and i not in new_ids]
        combos = list(itertools.product(*[cands[i] for i in new_ids])) if new_ids else [()]
        gap = vi > 0 and all(r.end < v.on - 1e-6 for r in vs[vi - 1].notes)
        new_states = {}
        for si, (assign, cost0, _) in enumerate(states):
            held = {i: assign.get(i, orig[i]) for i in held_ids}
            for combo in combos:
                cur_assign = dict(held)
                cur_assign.update(zip(new_ids, combo))
                cur = fixed + [(i, m, by_id[i].staff) for i, m in cur_assign.items()]
                c = cost0 + vertical_cost(cur, lt, v.label, orig_pcs, decided, set(new_ids))
                if vi > 0 and not gap:
                    c += transition_cost(prev_notes(vs[vi - 1], assign), cur, vs[vi - 1].label, orig, decided, set(new_ids))
                else:
                    c += sum(W["CHANGE"] for i in new_ids if cur_assign[i] != orig[i])
                key_ = tuple(sorted(cur_assign.items()))
                if key_ not in new_states or c < new_states[key_][1]:
                    new_states[key_] = (cur_assign, c, si)
        ranked = sorted(new_states.values(), key=lambda x: x[1])[:beam]
        history.append(ranked)
        states = ranked
    # terugvolgen
    result = {}
    bi = 0
    for ranked in reversed(history):
        assign, cost, back = ranked[bi]
        for i, m in assign.items():
            result.setdefault(i, m)
        bi = back if back is not None else 0
    return {i: m for i, m in result.items() if m != orig[i]}


def respell(sc: Score) -> int:
    """Spelling van alle noten op de akkoord-/toonsoortspelling zetten; geeft het aantal hergespelde noten."""
    n = 0
    for v in sc.verticals:
        spelling = chord_spelling(v)
        for r in v.notes:
            if r.on != v.on:
                continue
            exp = spelling[r.midi % 12]
            for obj in [r.obj] + [t.obj for t in getattr(r, "tied", [])]:
                if obj.pitch.name != exp.name:
                    q = pitch.Pitch(exp.name)
                    q.octave = obj.pitch.octave
                    while q.midi < obj.pitch.midi - 6:
                        q.octave += 1
                    while q.midi > obj.pitch.midi + 6:
                        q.octave -= 1
                    obj.pitch = q
                    n += 1
    return n


def apply(sc: Score, changes: dict):
    by_id = {r.id: r for r in sc.recs}
    for i, m in changes.items():
        r = by_id[i]
        r.set_midi(m)
        for t in getattr(r, "tied", []):
            t.set_midi(m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="alleen stukken waarvan de bestandsnaam dit bevat")
    ap.add_argument("--beam", type=int, default=12, help="bundelbreedte van de zoektocht")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    files = sorted((DIR / "midi").glob("*.musicxml"))
    if args.only:
        files = [f for f in files if args.only in f.name]
    jpath = DIR / "harmonie_correctie.json"
    results = json.loads(jpath.read_text()) if jpath.exists() else {}
    stems = {f.stem for f in (DIR / "midi").glob("*.musicxml")}
    results = {k: v for k, v in results.items() if k in stems}  # verdwenen stukken niet blijven meeslepen
    for f in files:
        out_xml = OUT / f.name
        if not args.force and out_xml.exists() and out_xml.stat().st_mtime > f.stat().st_mtime and f.stem in results:
            continue
        sc = Score(f)
        before = summary(check(sc), len(sc.verticals))
        for r in sc.recs:
            r.codes.clear()
        orig_names = {r.id: r.spitch.nameWithOctave for r in sc.recs}
        changes = revoice(sc, beam=args.beam)
        apply(sc, changes)
        for v in sc.verticals:  # records zijn dezelfde objecten; alleen volgorde, labels en slots bijwerken
            v.notes.sort(key=lambda r: r.midi)
            v.label = label_chord({r.midi % 12 for r in v.notes}, v.notes[0].midi % 12)
            assign_slots(v)
        n_spel = respell(sc)
        findings = check(sc)
        after = summary(findings, len(sc.verticals))
        mark(sc, {i: orig_names[i] for i in changes})
        for part in sc.parts.values():
            part.makeAccidentals(inPlace=True, overrideStatus=True, cautionaryPitchClass=False)
        sc.write(out_xml, " – gecorrigeerd")
        (OUT / f"{f.stem}.txt").write_text("\n".join(report_lines(findings)) + "\n")
        n_notes = len(sc.recs)
        results[f.stem] = dict(noten=n_notes, gewijzigd=len(changes), hergespeld=n_spel, voor=before, na=after)
        print(f"{f.stem[:55]:55s} noten={n_notes:5d} gewijzigd={len(changes):4d} ({100 * len(changes) / n_notes:4.1f}%) "
              f"hergespeld={n_spel:3d} fouten {before['totaal']:4d} -> {after['totaal']:4d}")
        jpath.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    write_md(results)


def write_md(results: dict):
    codes = Counter()
    for r in results.values():
        codes.update(r["voor"]["codes"])
        codes.update(r["na"]["codes"])
    codes = [c for c, _ in codes.most_common()]
    tot_b, tot_a = Counter(), Counter()
    for r in results.values():
        tot_b.update(r["voor"]["codes"])
        tot_a.update(r["na"]["codes"])
    lines = ["# Formele harmonie-correctie", "",
             "Melodie en bas ongewijzigd; binnenstemmen opnieuw gezet en spelling gecorrigeerd. Per code: aantal "
             "meldingen vóór -> na. Wat overblijft zit vrijwel altijd in de buitenstemmen zelf (verborgen/open "
             "parallellen tussen melodie en bas, leidtoon in de melodie), of is een transcriptie-artefact.", "",
             "## Totaal", "", "| code | vóór | na |", "|---|---|---|"]
    for c in codes:
        lines.append(f"| {c} | {tot_b[c]} | {tot_a[c]} |")
    lines += ["", "## Per stuk", "", "| stuk | noten | gewijzigd | hergespeld | meldingen vóór | na | " + " | ".join(codes) + " |",
              "|---|---|---|---|---|---|" + "---|" * len(codes)]
    for stem, r in sorted(results.items()):
        lines.append(f"| {stem[:45]} | {r['noten']} | {r['gewijzigd']} | {r['hergespeld']} | {r['voor']['totaal']} | {r['na']['totaal']} | "
                     + " | ".join(f"{r['voor']['codes'].get(c, 0)}→{r['na']['codes'].get(c, 0)}" for c in codes) + " |")
    (DIR / "harmonie_correctie.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
