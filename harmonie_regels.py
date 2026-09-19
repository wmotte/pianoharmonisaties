#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Gedeelde module voor de formele harmonie-controle (controleer_harmonie.py) en -correctie
(corrigeer_harmonie.py) van de partituren in midi/.

Model: een partituur wordt gelezen als een reeks *verticalen* (elk tijdstip waarop een noot inzet, met alle
op dat moment klinkende noten, gesorteerd op toonhoogte). Stemmen worden op positie benoemd: B = laagste,
S = hoogste, daartussen T en A. Tussen twee opeenvolgende verticalen worden de stemmen gekoppeld (S<->S,
B<->B, binnenstemmen orde-behoudend met minimale verplaatsing) en daarop worden de klassieke regels van de
vierstemmige koraalzetting getoetst.

Codes:
  P5/P8/P1  open parallelle kwinten/octaven/priemen (AP5/AP8: door tegenbeweging of octaafwissel)
  H5/H8     verborgen kwint/octaaf in de buitenstemmen (S springt, B gelijkbewegend)
  KR        stemkruising (rechterhand onder linkerhand, of een stem kruist een liggende noot)
  OV        overlap (stem gaat voorbij de vorige toon van de buurstem)
  LT2       verdubbelde leidtoon
  LT        leidtoon in een buitenstem lost bij V->I niet stapsgewijs op naar de tonica
  S7        akkoordseptiem lost niet dalend (of liggend) op
  A2        overmatig melodisch interval of sprong > octaaf in een binnenstem
  LIG       ligging: meer dan een octaaf tussen S-A of A-T
  SPL       spelling van voortekens wijkt af van de akkoord-/toonsoortspelling
  OMV       buiten de zangomvang van S/A/T/B (alleen op verzoek)

`python harmonie_regels.py --test` draait een synthetische test met bekende fouten.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from music21 import chord, converter, interval, key, note, pitch, spanner, stream

from analyse_stijl import TEMPLATES, label_chord
from piano_notatie import logical_score_xml, place_high_bass_notes
from transcribe_piano import KEY_PROFILES, fifths_index, key_spell_pc, spell_vertical

DIR = Path(__file__).resolve().parent
RED, GREEN = "#E00000", "#00A000"
RANGES = {"S": (60, 81), "A": (55, 74), "T": (48, 67), "B": (40, 60)}  # c'-a'', g-d'', c-g', E-c'
SEVENTH = {"dom7": 10, "min7": 10, "maj7": 11, "m7b5": 10, "dim7": 9}
LETTER_STEP = {"maj": (0, 2, 4), "min": (0, 2, 4), "dom7": (0, 2, 4, 6), "maj7": (0, 2, 4, 6),
               "min7": (0, 2, 4, 6), "dim": (0, 2, 4), "dim7": (0, 2, 4, 6), "m7b5": (0, 2, 4, 6),
               "sus4": (0, 3, 4), "sus2": (0, 1, 4), "add9": (0, 1, 2, 4), "maj6": (0, 2, 4, 5),
               "min6": (0, 2, 4, 5), "madd9": (0, 1, 2, 4), "aug": (0, 2, 4)}
LETTERS = "CDEFGAB"
LABEL_MIN_SCORE = 2.0  # onder deze sjabloonscore is het akkoordlabel te onzeker voor spelling/septiemregels
UNMATCHED = 9  # kosten (halve tonen) voor een niet-gekoppelde binnenstem bij de stemkoppeling


@dataclass
class NoteRec:
    id: int
    obj: note.Note
    parent: chord.Chord | None
    staff: str  # "R" of "L"
    on: float  # absolute offset (quarterLength) in de part
    end: float
    measure: int
    beat: float
    shift: int = 0  # +12 onder een 8va
    orig: str = ""  # oorspronkelijke spelling (nameWithOctave, geschreven)
    codes: list = field(default_factory=list)

    @property
    def midi(self) -> int:
        return self.obj.pitch.midi + self.shift

    @property
    def spitch(self) -> pitch.Pitch:  # klinkende toonhoogte
        p = pitch.Pitch(self.obj.pitch.nameWithOctave)
        p.octave += self.shift // 12
        return p

    def set_midi(self, m: int):
        """Nieuwe klinkende toonhoogte; spelling wordt daarna door respell() gezet."""
        self.obj.pitch = pitch.Pitch(m - self.shift)


@dataclass
class Vertical:
    on: float
    notes: list  # NoteRec, gesorteerd op klinkende toonhoogte
    measure: int
    beat: float
    key: key.Key
    label: tuple  # (root_pc, naam, score)
    slots: dict = field(default_factory=dict)  # slotnaam -> NoteRec (S, A, T, B); verdubbelingen apart
    doubles: dict = field(default_factory=dict)  # NoteRec.id -> slotnaam (verdubbeling van dat slot)

    def slot_of(self, rec: NoteRec):
        for s, r in self.slots.items():
            if r is rec:
                return s
        return self.doubles.get(rec.id)


class Score:
    """Ingelezen partituur met noot-records, verticalen en toonsoort per maat."""

    def __init__(self, path: Path):
        self.path = Path(path)
        logical_xml = logical_score_xml(self.path)
        self.cross_staff_layout = logical_xml is not None
        self.score = (converter.parseData(logical_xml, format='musicxml') if logical_xml is not None
                      else converter.parse(str(path)))
        self.parts = {"R": self.score.parts[0], "L": self.score.parts[1]}
        self.recs: list[NoteRec] = []
        self.ottava_ids: set[int] = set()
        self._collect()
        self.keys = self._keys_per_measure()
        self.verticals = self._verticals()
        for v in self.verticals:
            assign_slots(v)

    # ---- inlezen -------------------------------------------------------------------------------
    def _collect(self):
        nid = 0
        for staff, part in self.parts.items():
            shifted = set()
            for ott in part.recurse().getElementsByClass(spanner.Ottava):
                ott.fill(part)
                for el in ott.getSpannedElements():
                    shifted.add(id(el))
            for mm in part.getElementsByClass(stream.Measure):
                for el in mm.recurse().notes:
                    on = mm.offset + el.getOffsetInHierarchy(mm)
                    shift = 12 if id(el) in shifted else 0
                    beat = el.getOffsetInHierarchy(mm) + mm.paddingLeft + 1
                    for n in (el.notes if el.isChord else [el]):
                        rec = NoteRec(nid, n, el if el.isChord else None, staff, on, on + el.quarterLength,
                                      mm.number, beat, shift, n.pitch.nameWithOctave)
                        if shift:
                            self.ottava_ids.add(nid)
                        self.recs.append(rec)
                        nid += 1
        # gebonden noten: de vervolgnoot hoort bij dezelfde klank -> als één record met langere duur
        by_key = {}
        merged = []
        for rec in sorted(self.recs, key=lambda r: (r.staff, r.on)):
            tie = rec.obj.tie
            if tie is not None and tie.type in ("stop", "continue"):
                prev = by_key.get((rec.staff, rec.midi, rec.on))
                if prev is not None:
                    prev.end = max(prev.end, rec.end)
                    prev.tied = getattr(prev, "tied", []) + [rec]
                    by_key[(rec.staff, rec.midi, rec.end)] = prev
                    continue
            merged.append(rec)
            by_key[(rec.staff, rec.midi, rec.end)] = rec
        self.recs = merged

    def _keys_per_measure(self) -> dict:
        part = self.parts["R"]
        measures = list(part.getElementsByClass(stream.Measure))
        sig = {}
        cur = 0
        for mm in measures:
            for ks in mm.getElementsByClass(key.KeySignature):
                cur = ks.sharps
            sig[mm.number] = cur
        # per voortekening-segment majeur of mineur kiezen op de pitch-class-histogram (Krumhansl)
        keys = {}
        segs = []
        for mm in measures:
            if not segs or segs[-1][0] != sig[mm.number]:
                segs.append((sig[mm.number], [mm.number]))
            else:
                segs[-1][1].append(mm.number)
        for sharps, nums in segs:
            hist = np.zeros(12)
            for rec in self.recs:
                if rec.measure in nums:
                    hist[rec.midi % 12] += rec.end - rec.on
            best = None
            cands = [
                key.KeySignature(sharps).asKey("major"),
                key.KeySignature(sharps).asKey("minor"),
            ]
            dorian_pc = (2 + 7 * sharps) % 12
            dorian_name = pitch.Pitch(dorian_pc).name
            try:
                cands.append(key.Key(dorian_name, "dorian"))
            except Exception:
                pass
            for k in cands:
                prof = np.roll(KEY_PROFILES[k.mode], k.tonic.pitchClass)
                r = np.corrcoef(hist, prof)[0, 1] if hist.sum() and np.std(hist) > 0 else 0
                if best is None or r > best[0]:
                    best = (r, k)
            for n in nums:
                keys[n] = best[1]
        return keys

    def _verticals(self) -> list:
        onsets = sorted({rec.on for rec in self.recs})
        out = []
        for t in onsets:
            sounding = sorted([r for r in self.recs if r.on <= t < r.end - 1e-6], key=lambda r: r.midi)
            if not sounding:
                continue
            first = min(sounding, key=lambda r: r.on if r.on == t else 1e9)
            k = self.keys.get(first.measure, key.Key("C"))
            pcs = {r.midi % 12 for r in sounding}
            lab = label_chord(pcs, sounding[0].midi % 12)
            out.append(Vertical(t, sounding, first.measure, first.beat, k, lab))
        return out

    # ---- uitvoer -------------------------------------------------------------------------------
    def write(self, path: Path, title_suffix: str = ""):
        if title_suffix and self.score.metadata is not None:
            self.score.metadata.title = (self.score.metadata.title or "") + title_suffix
        path.parent.mkdir(exist_ok=True)
        self.score.write("musicxml", fp=str(path))
        txt = path.read_text().replace('<note print-object="no" print-spacing="yes">', "<note>")
        path.write_text(txt)
        if self.cross_staff_layout:
            place_high_bass_notes(path)


# ---- stemmen ---------------------------------------------------------------------------------------
def assign_slots(v: Vertical):
    """S/A/T/B op positie; unisono-verdubbelingen en extra noten (> 4) hangen als verdubbeling aan een slot."""
    distinct = []
    for r in v.notes:
        if distinct and distinct[-1][0] == r.midi:
            distinct[-1][1].append(r)
        else:
            distinct.append([r.midi, [r]])
    n = len(distinct)
    if n == 1:
        names = ["S" if v.notes[0].staff == "R" else "B"]
    elif n == 2:
        names = ["B", "S"]
    elif n == 3:
        names = ["B", "T", "S"]
    else:
        names = ["B", "T", "A", "S"]
    v.slots, v.doubles = {}, {}
    if n <= 4:
        for (m, recs), name in zip(distinct, names):
            v.slots[name] = recs[0]
            for extra in recs[1:]:
                v.doubles[extra.id] = name
        return
    # > 4 verschillende toonhoogtes: buitenste = B en S, de twee hoogste binnenste = T en A, rest verdubbeling
    v.slots["B"], v.slots["S"] = distinct[0][1][0], distinct[-1][1][0]
    inner = distinct[1:-1]
    v.slots["T"], v.slots["A"] = inner[-2][1][0], inner[-1][1][0]
    for m, recs in inner[:-2]:
        near = min(("B", "T", "A", "S"), key=lambda s: abs(v.slots[s].midi - m))
        for r in recs:
            v.doubles[r.id] = near
    for m, recs in distinct:
        for r in recs[1:]:
            if r.id not in v.doubles:
                v.doubles[r.id] = v.slot_of(recs[0])


def pair_voices(v1: Vertical, v2: Vertical) -> list:
    """Koppeling van stemmen tussen twee verticalen: [(slot1, slot2, rec1, rec2)]; buitenstemmen vast,
    binnenstemmen orde-behoudend met minimale totale verplaatsing."""
    pairs = []
    for s in ("S", "B"):
        if s in v1.slots and s in v2.slots:
            pairs.append((s, s, v1.slots[s], v2.slots[s]))
    in1 = [s for s in ("T", "A") if s in v1.slots]
    in2 = [s for s in ("T", "A") if s in v2.slots]
    # orde-behoudende koppeling (DP over twee korte lijsten)
    a = [(s, v1.slots[s]) for s in in1]
    b = [(s, v2.slots[s]) for s in in2]
    best = (1e9, [])
    def rec(i, j, cost, acc):
        nonlocal best
        if i == len(a) or j == len(b):
            cost += UNMATCHED * ((len(a) - i) + (len(b) - j))
            if cost < best[0]:
                best = (cost, acc)
            return
        rec(i + 1, j + 1, cost + abs(a[i][1].midi - b[j][1].midi), acc + [(a[i][0], b[j][0], a[i][1], b[j][1])])
        rec(i + 1, j, cost + UNMATCHED, acc)
        rec(i, j + 1, cost + UNMATCHED, acc)
    rec(0, 0, 0, [])
    pairs.extend(best[1])
    return pairs


# ---- spelling --------------------------------------------------------------------------------------
def chord_spelling(v: Vertical) -> dict:
    """pitch class -> verwachte spelling (Pitch zonder octaaf) voor de akkoordtonen van het gelabelde akkoord,
    aangevuld met de toonsoortspelling voor de overige tonen."""
    tonic_idx = v.key.sharps  # midden van de kwintencirkel = de voortekening (mineur: de parallelle majeur)
    out = {pc: key_spell_pc(pc, v.key) for pc in range(12)}  # modus-bewust: mineur verhoogde 6e/7e als kruis
    # de klinkende tonen akkoord-/interval-bewust spellen (B-D#, niet B-Eb), net als stap 2
    out.update(spell_vertical([r.midi for r in v.notes], v.key))
    root_pc, name, score = v.label
    if score < LABEL_MIN_SCORE or name not in LETTER_STEP:
        return out
    tpl, steps = TEMPLATES[name], LETTER_STEP[name]
    best = None
    for letter in LETTERS:  # grondtoonspelling met zo min mogelijk voortekens over het hele akkoord
        base = pitch.Pitch(letter).pitchClass
        alter = (root_pc - base + 6) % 12 - 6
        if abs(alter) > 1:
            continue
        spelled = []
        for semi, step in zip(tpl, steps):
            L = LETTERS[(LETTERS.index(letter) + step) % 7]
            pc = (root_pc + semi) % 12
            a = (pc - pitch.Pitch(L).pitchClass + 6) % 12 - 6
            p = pitch.Pitch(L)
            if a:
                p.accidental = pitch.Accidental(a)
            spelled.append(p)
        n_acc = sum(abs(p.accidental.alter) for p in spelled if p.accidental)
        root_p = spelled[0]
        cost = (n_acc, abs(fifths_index(root_p) - tonic_idx) + (4 if root_p.accidental and root_p.accidental.alter < 0 else 0))
        if any(p.accidental and abs(p.accidental.alter) > 1 for p in spelled):
            continue
        if best is None or cost < best[0]:
            best = (cost, spelled)
    if best:
        for p in best[1]:
            out[p.pitchClass] = p
    return out


def expected_name(rec: NoteRec, v: Vertical, spelling: dict | None = None) -> str:
    spelling = spelling or chord_spelling(v)
    return spelling[rec.midi % 12].name


# ---- regels ----------------------------------------------------------------------------------------
def leading_tone_pc(k: key.Key) -> int:
    return (k.tonic.pitchClass + 11) % 12


def check(sc: Score, omvang: bool = False, *, include_ids: bool = False) -> list:
    """Alle regels toetsen; markeert rec.codes en geeft een lijst meldingen terug."""
    findings = []

    def add(rec: NoteRec, code: str, v: Vertical, detail: str):
        if code in rec.codes:
            return  # één melding per noot en code (bijv. liggende noot die maten lang te laag ligt)
        rec.codes.append(code)
        findings.append(dict(measure=v.measure, beat=v.beat, code=code, note=rec.spitch.nameWithOctave,
                             staff=rec.staff, detail=detail))
        if include_ids:
            findings[-1]["note_id"] = rec.id

    vs = sc.verticals
    for i, v in enumerate(vs):
        lt = leading_tone_pc(v.key)
        # --- kruising tussen de handen
        lows = [r for r in v.notes if r.staff == "L"]
        highs = [r for r in v.notes if r.staff == "R"]
        if lows and highs:
            top_l = max(lows, key=lambda r: r.midi)
            for r in highs:
                if r.midi < top_l.midi and r.on == v.on:
                    add(r, "KR", v, f"rechterhand {r.spitch.nameWithOctave} onder linkerhand {top_l.spitch.nameWithOctave}")
        # --- verdubbelde leidtoon
        lts = [r for r in v.notes if r.midi % 12 == lt]
        if len({r.midi for r in lts}) >= 2 or len(lts) >= 2:
            for r in lts:
                add(r, "LT2", v, "verdubbelde leidtoon")
        # --- ligging
        upper = [s for s in ("S", "A", "T") if s in v.slots]
        for up, low in zip(upper, upper[1:]):
            if v.slots[up].midi - v.slots[low].midi > 12 and (v.slots[low].on == v.on or v.slots[up].on == v.on):
                add(v.slots[low], "LIG", v, f"{up}-{low} meer dan een octaaf")
        # --- spelling
        spelling = chord_spelling(v)
        for r in v.notes:
            if r.on != v.on:
                continue
            p = r.spitch
            exp = spelling[p.pitchClass].name
            if p.accidental is not None and abs(p.accidental.alter) > 1:
                add(r, "SPL", v, f"dubbel voorteken, verwacht {exp}")
            elif p.name != exp:
                add(r, "SPL", v, f"verwacht {exp}")
        # --- omvang
        if omvang:
            for s, r in v.slots.items():
                lo, hi = RANGES[s]
                if r.on == v.on and not lo <= r.midi <= hi:
                    add(r, "OMV", v, f"{s} buiten {lo}-{hi}")
        if i == 0:
            continue
        # --- regels over de verbinding met de vorige verticaal
        v1 = vs[i - 1]
        if all(r.end < v.on - 1e-6 for r in v1.notes):
            continue  # algemene rust ertussen: geen stemvoeringsregels over de verbinding
        pairs = pair_voices(v1, v)
        moved = {s2: (r1.midi != r2.midi) for s1, s2, r1, r2 in pairs}
        # parallellen tussen elk paar gekoppelde stemmen
        for a in range(len(pairs)):
            for b in range(a + 1, len(pairs)):
                sa1, sa2, ra1, ra2 = pairs[a]
                sb1, sb2, rb1, rb2 = pairs[b]
                if ra1.midi == ra2.midi or rb1.midi == rb2.midi:
                    continue  # minstens één stem ligt: geen parallel
                (u1, l1), (u2, l2) = sorted([ra1.midi, rb1.midi], reverse=True), sorted([ra2.midi, rb2.midi], reverse=True)
                i1, i2 = u1 - l1, u2 - l2
                if i1 % 12 == 7 and i2 % 12 == 7:
                    code = "P5" if i1 == i2 else "AP5"
                elif i1 % 12 == 0 and i2 % 12 == 0:
                    if i1 == 0 and i2 == 0:
                        code = "P1"
                    else:
                        code = "P8" if i1 == i2 else "AP8"
                    # octaafverdubbeling van de bas in de linkerhand is pianistisch en telt niet
                    if {sa2, sb2} == {"B", "T"} and ra2.staff == "L" and rb2.staff == "L" and i2 == 12 and i1 == 12:
                        continue
                else:
                    continue
                for r in (ra2, rb2):
                    add(r, code, v, f"{sa2}-{sb2}: {ra1.spitch.name}/{rb1.spitch.name} -> {ra2.spitch.name}/{rb2.spitch.name}")
        # verborgen kwint/octaaf in de buitenstemmen
        if "S" in v1.slots and "S" in v.slots and "B" in v1.slots and "B" in v.slots:
            s1, s2, b1, b2 = v1.slots["S"].midi, v.slots["S"].midi, v1.slots["B"].midi, v.slots["B"].midi
            ds, db = s2 - s1, b2 - b1
            if ds and db and np.sign(ds) == np.sign(db) and abs(ds) > 2:
                i2 = (s2 - b2) % 12
                if i2 in (7, 0) and not ((s1 - b1) % 12 == i2):
                    code = "H5" if i2 == 7 else "H8"
                    for r in (v.slots["S"], v.slots["B"]):
                        add(r, code, v, f"S springt {ds:+d}, B {db:+d}")
        # overlap en kruising van een liggende noot
        order = [s for s in ("B", "T", "A", "S") if s in v.slots]
        prev_slot = {r2.id: (s1, r1) for s1, s2, r1, r2 in pairs}
        for lo, hi in zip(order, order[1:]):
            r_lo, r_hi = v.slots[lo], v.slots[hi]
            p_lo, p_hi = prev_slot.get(r_lo.id), prev_slot.get(r_hi.id)
            moved_lo = p_lo is not None and p_lo[1].midi != r_lo.midi and r_lo.on == v.on
            moved_hi = p_hi is not None and p_hi[1].midi != r_hi.midi and r_hi.on == v.on
            if moved_lo and p_hi and r_lo.midi > p_hi[1].midi:
                add(r_lo, "OV", v, f"{lo} boven vorige {hi} ({p_hi[1].spitch.nameWithOctave})")
            if moved_hi and p_lo and r_hi.midi < p_lo[1].midi:
                add(r_hi, "OV", v, f"{hi} onder vorige {lo} ({p_lo[1].spitch.nameWithOctave})")
        for s1, s2, r1, r2 in pairs:
            if r2.on != v.on or r1.midi == r2.midi:
                continue
            for h in v.notes:  # liggende noten die door deze stem gekruist worden
                if h.on < v.on and h is not r2 and h in v1.notes and (r1.midi < h.midi) != (r2.midi < h.midi) and r2.midi != h.midi:
                    add(r2, "KR", v, f"{s2} kruist liggende {h.spitch.nameWithOctave}")
        # leidtoon in buitenstem bij V(7)/vii -> I
        root1, name1, sc1 = v1.label
        root2, name2, sc2 = v.label
        ton = v.key.tonic.pitchClass
        if sc1 >= LABEL_MIN_SCORE and sc2 >= LABEL_MIN_SCORE and root2 == ton and root1 in ((ton + 7) % 12, (ton + 11) % 12):
            for s1, s2, r1, r2 in pairs:
                if s1 in ("S", "B") and r1.midi % 12 == lt and r2.midi - r1.midi not in (1, 0):
                    add(r1, "LT", v1, f"leidtoon in {s1} gaat naar {r2.spitch.nameWithOctave}")
        # septiem lost dalend op
        if sc1 >= LABEL_MIN_SCORE and name1 in SEVENTH and root2 != root1:
            sev = (root1 + SEVENTH[name1]) % 12
            for s1, s2, r1, r2 in pairs:
                if r1.midi % 12 == sev and r2.midi - r1.midi not in (0, -1, -2):
                    add(r1, "S7", v1, f"septiem in {s1} gaat naar {r2.spitch.nameWithOctave}")
        # melodische intervallen in binnenstemmen
        for s1, s2, r1, r2 in pairs:
            if s2 in ("A", "T") and r2.on == v.on and r1.midi != r2.midi:
                iv = interval.Interval(r1.spitch, r2.spitch)
                if abs(r2.midi - r1.midi) > 12 or iv.simpleName in ("A2", "A4", "A5", "A6", "d3", "d4", "d7"):
                    add(r2, "A2", v, f"{s2}: {r1.spitch.name}->{r2.spitch.name} ({iv.simpleName}, {r2.midi - r1.midi:+d})")
    return findings


# ---- markeren en rapport --------------------------------------------------------------------------
def mark(sc: Score, changed: dict | None = None):
    """Rode kleur + lyric-label voor foute noten; groen voor gewijzigde noten (changed: id -> oude naam)."""
    changed = changed or {}
    labels = defaultdict(list)
    for rec in sc.recs:
        objs = [rec.obj] + [t.obj for t in getattr(rec, "tied", [])]
        if rec.codes:
            for o in objs:
                o.style.color = RED
            labels[id(rec.parent or rec.obj)].append((rec.parent or rec.obj, "/".join(rec.codes)))
        elif rec.id in changed:
            for o in objs:
                o.style.color = GREEN
            labels[id(rec.parent or rec.obj)].append((rec.parent or rec.obj, f"was {changed[rec.id]}"))
    for items in labels.values():
        el = items[0][0]
        el.lyric = ", ".join(dict.fromkeys(t for _, t in items))


def summary(findings: list, n_vert: int) -> dict:
    c = Counter(f["code"] for f in findings)
    return dict(n_verticalen=n_vert, totaal=len(findings), per_100=round(100 * len(findings) / max(1, n_vert), 1),
                codes=dict(c.most_common()))


def report_lines(findings: list) -> list:
    findings = sorted(findings, key=lambda f: (f["measure"], f["beat"], f["code"]))
    return [f"maat {f['measure']:>4} tel {f['beat']:<5g} | {f['code']:<4} | {f['staff']} {f['note']:<5} | {f['detail']}"
            for f in findings]


# ---- test ------------------------------------------------------------------------------------------
def _test():
    """Kleine vierstemmige zetting met bekende fouten."""
    from music21 import metadata, meter
    s = stream.Score()
    R, L = stream.PartStaff(), stream.PartStaff()
    for p in (R, L):
        p.insert(0, meter.TimeSignature("4/4"))
        p.insert(0, key.KeySignature(0))
    # maat 1: C  -> D-  (parallelle kwinten T-B: c/g -> d/a; en octaven S-B c'/c -> d'/d)
    # maat 2: G7 -> C   met septiem (f) die omhoog gaat, leidtoon (b) in S naar g, verdubbelde leidtoon
    # maat 3: A-akkoord met des (moet cis zijn); maat 4: kruising (L boven R)
    def add(part, offset, ps, ql=2.0):
        el = chord.Chord(ps, quarterLength=ql) if len(ps) > 1 else note.Note(ps[0], quarterLength=ql)
        part.insert(offset, el)
    add(R, 0, ["E4", "C5"]); add(L, 0, ["C3", "G3"])
    add(R, 2, ["F4", "D5"]); add(L, 2, ["D3", "A3"])
    add(R, 4, ["F4", "B4"]); add(L, 4, ["G2", "B3"])  # G7 met verdubbelde leidtoon
    add(R, 6, ["G4", "C5"]); add(L, 6, ["C3", "E3"])  # septiem f -> g (omhoog)
    add(R, 8, ["D-4", "E4"]); add(L, 8, ["A2", "E3"])  # A-majeur: des i.p.v. cis
    add(R, 10, ["E4", "A4"]); add(L, 10, ["A2", "C#3"])
    add(R, 12, ["C4", "E4"]); add(L, 12, ["G3", "E4"])  # E4 in L, C4 in R: kruising
    add(R, 14, ["D4", "B4"]); add(L, 14, ["G2", "G3"])  # G -> C met leidtoon in S naar g
    add(R, 16, ["E4", "G4"]); add(L, 16, ["C3", "E3"])
    for p in (R, L):
        p.makeMeasures(inPlace=True)
        s.insert(0, p)
    s.metadata = metadata.Metadata(title="test")
    tmp = DIR / "_test_harmonie.musicxml"
    s.write("musicxml", fp=str(tmp))
    sc = Score(tmp)
    f = check(sc)
    tmp.unlink()
    codes = Counter(x["code"] for x in f)
    for line in report_lines(f):
        print(line)
    expect = {"P5", "P8", "LT2", "S7", "LT", "SPL", "KR"}
    missing = expect - set(codes)
    print("gevonden:", dict(codes), "| ontbreekt:", missing or "-")
    return not missing


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(0 if _test() else 1)
