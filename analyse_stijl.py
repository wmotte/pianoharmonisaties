#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Stijlanalyse van de transcripties in midi/ (+ midi_raw/): wat doet Gerrit Koele in voorspel, koraal
(hoofdspel), tussenspel en naspel, en hoe harmoniseert hij?

Per stuk:
  - secties uit de textuur per maat (koraal = homofoon, weinig achtsten; vrij = achtsten-figuren)
  - harmonie per tel via sjabloon-herkenning (drieklanken, septiemen, sus, add9) -> trap t.o.v. de lokale
    toonsoort, omkering, harmonisch ritme, progressie-bigrammen, cadensen bij fermates/sectie-einden
  - bas: beweging (stap/sprong/octaaf/liggend), orgelpunten, octaafverdubbeling, grondligging
  - rechterhand: akkoordgrootte, melodieligging, citeert het voorspel de koraalmelodie?
  - uit de ruwe MIDI: pedaalgebruik, legato, gebroken akkoorden, rit. aan het slot, dynamiek per sectie
Uitvoer: stijlanalyse.json (alle cijfers) en een samenvatting op stdout.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pretty_midi
from music21 import converter, expressions, note, chord, stream

DIR = Path(__file__).resolve().parent
COMPILATIONS = ("Bekende christelijke hymnes", "8 Psalmen", "Pianomuziek voor de lijdenstijd",
                "kerstliederen", "Kerstliederen", "Beautiful Christmas")

TEMPLATES = {  # naam: (pitch-classes t.o.v. grondtoon)
    "maj": (0, 4, 7), "min": (0, 3, 7), "dom7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "min7": (0, 3, 7, 10),
    "dim": (0, 3, 6), "dim7": (0, 3, 6, 9), "m7b5": (0, 3, 6, 10), "sus4": (0, 5, 7), "sus2": (0, 2, 7),
    "add9": (0, 2, 4, 7), "maj6": (0, 4, 7, 9), "min6": (0, 3, 7, 9), "madd9": (0, 2, 3, 7), "aug": (0, 4, 8),
}
DEGREES_MAJ = {0: "I", 1: "bII", 2: "II", 3: "bIII", 4: "III", 5: "IV", 6: "#IV", 7: "V", 8: "bVI", 9: "VI",
               10: "bVII", 11: "VII"}
DEGREES_MIN = {0: "i", 1: "bII", 2: "ii", 3: "III", 4: "#III", 5: "iv", 6: "#iv", 7: "V", 8: "VI", 9: "#VI",
               10: "VII", 11: "#VII"}


def label_chord(pcs, bass_pc, weights=None):
    """Beste sjabloon voor een verzameling pitch-classes -> (root_pc, naam, score)."""
    pcs = set(pcs)
    best = None
    for root in range(12):
        for name, tpl in TEMPLATES.items():
            t = {(root + x) % 12 for x in tpl}
            hit = len(pcs & t)
            score = hit - 0.6 * len(pcs - t) - 0.7 * len(t - pcs) + (0.4 if bass_pc == root else 0)
            if len(tpl) == 3:
                score += 0.1  # eenvoud
            if best is None or score > best[2]:
                best = (root, name, score)
    return best


def degree(root_pc, key_obj):
    rel = (root_pc - key_obj.tonic.pitchClass) % 12
    return (DEGREES_MAJ if key_obj.mode == "major" else DEGREES_MIN)[rel]


def repeated_beats(melody, W=16, thr=0.8, min_lag=32):
    """Per tel: komt de melodische intervalreeks van W tellen elders (op >= min_lag afstand) bijna letterlijk
    terug? Verzen (coupletten) herhalen de melodie; voor-/tussen-/naspel niet."""
    m = np.array(melody, dtype=float)
    d = np.diff(m)
    d[np.isnan(d)] = 99  # rust/onbekend
    n = len(d)
    rep = np.zeros(n + 1, dtype=bool)
    if n < W + min_lag:
        return rep
    kern = np.ones(W)
    for lag in range(min_lag, n - W):
        eq = (d[:-lag] == d[lag:]).astype(float)
        hits = np.convolve(eq, kern, mode="valid") / W  # hits[t] = overeenkomst venster t..t+W met t+lag..
        ok = np.where(hits >= thr)[0]
        for t in ok:
            rep[t:t + W + 1] = True
            rep[t + lag:t + lag + W + 1] = True
    return rep


def section_labels(bars_feat, fermata_bars, melody, beats_per_bar, thr8=0.33, min_run=4):
    """Secties: maten waarvan de melodie elders in het stuk terugkomt zijn koraal (couplet); de rest is vrij.
    Zonder herhaling (één couplet): knippen bij fermates en het deel met de minste achtsten is het koraal.
    Benoemen: eerste vrije deel = voorspel, laatste = naspel, ertussen = tussenspel."""
    n = len(bars_feat)
    rep = repeated_beats(melody)
    lab = []
    for b in range(n):
        seg = rep[b * beats_per_bar:(b + 1) * beats_per_bar]
        lab.append("K" if len(seg) and seg.mean() >= 0.5 else "V")
    if "K" not in lab:  # geen herhaling: fermate-segmenten, minste achtsten = koraal
        cuts = sorted({b + 1 for b in fermata_bars if b + 1 < n} | {i + 1 for i, f in enumerate(bars_feat) if f["n_on"] == 0 and i + 1 < n})
        edges = [0] + cuts + [n]
        segs = [(i, j, float(np.mean([bars_feat[b]["frac8"] for b in range(i, j) if bars_feat[b]["n_on"] > 0] or [1])))
                for i, j in zip(edges, edges[1:])]
        if len(segs) >= 2:
            i, j, _ = min(segs, key=lambda x: (x[2], -(x[1] - x[0])))
            for b in range(i, j):
                lab[b] = "K"
    # runs, korte runs opslokken
    runs = []
    i = 0
    while i < n:
        j = i
        while j < n and lab[j] == lab[i]:
            j += 1
        runs.append([lab[i], i, j])
        i = j
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k, (l, i, j) in enumerate(runs):
            if j - i < min_run and not (k == 0 and l == "V") and not (k == len(runs) - 1 and l == "V"):
                nb = k - 1 if k > 0 else k + 1
                runs[nb][1], runs[nb][2] = min(runs[nb][1], i), max(runs[nb][2], j)
                del runs[k]
                changed = True
                break
    merged = []
    for r in runs:
        if merged and merged[-1][0] == r[0]:
            merged[-1][2] = r[2]
        else:
            merged.append(r)
    out = []
    ks = [m for m, r in enumerate(merged) if r[0] == "K"]
    for m, (l, i, j) in enumerate(merged):
        if l == "K":
            name = f"koraal{ks.index(m) + 1}"
        elif m == 0:
            name = "voorspel"
        elif m == len(merged) - 1:
            name = "naspel"
        else:
            name = "tussenspel"
        out.append((name, i, j))
    return out


def ngrams(seq, n=5):
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)}


def analyse(xml_path: Path, raw_path: Path):
    s = converter.parse(str(xml_path))
    R, L = s.parts[0], s.parts[1]
    measures_R = list(R.getElementsByClass(stream.Measure))
    measures_L = list(L.getElementsByClass(stream.Measure))
    n_bars = len(measures_R)
    ts = measures_R[0].timeSignature or R.recurse().getElementsByClass("TimeSignature")[0]
    beats_per_bar = ts.numerator
    tempo_marks = list(R.recurse().getElementsByClass("MetronomeMark"))
    bpm = tempo_marks[0].number if tempo_marks else None

    # toonsoort per maat (KeySignature -> Key via analyse van dat deel)
    key_by_bar, cur = [], None
    for mm in measures_R:
        if mm.keySignature is not None:
            cur = mm.keySignature
        key_by_bar.append(cur)
    seg_keys = {}
    for ksig in {id(k): k for k in key_by_bar if k is not None}.values():
        idx = [i for i, k in enumerate(key_by_bar) if k is ksig]
        part = s.measures(idx[0] + 1, idx[-1] + 1)
        try:
            k_obj = part.analyze("key")
            if k_obj.sharps != ksig.sharps:  # kies de majeur/mineur met deze voortekening die het best past
                k_obj = max([k_obj.getRelativeMajor() if k_obj.mode == "minor" else k_obj.getRelativeMinor()],
                            key=lambda k: k.sharps == ksig.sharps)
        except Exception:
            k_obj = ksig.asKey()
        seg_keys[id(ksig)] = k_obj
    keys_bar = [seg_keys[id(k)] for k in key_by_bar]

    # per maat: textuur
    feats = []
    for mR, mL in zip(measures_R, measures_L):
        ons = []
        for mm in (mR, mL):
            for el in mm.recurse().notes:
                if el.tie is not None and el.tie.type in ("stop", "continue"):
                    continue
                ons.append((float(el.offset), float(el.quarterLength), len(el.pitches), [p.midi for p in el.pitches]))
        n_on = len(ons)
        frac8 = np.mean([d < 1.0 for _, d, _, _ in ons]) if ons else 0.0
        # akkoordgrootte: aantal verschillende noten die op een tel samen beginnen (beide handen)
        by_off = defaultdict(int)
        for o, _, n, _ in ons:
            by_off[o] += n
        chord_size = np.mean(list(by_off.values())) if by_off else 0.0
        feats.append(dict(n_on=n_on, frac8=float(frac8), chord_size=float(chord_size)))

    # harmonie per tel via chordify
    ch = s.chordify()
    chords_by_beat = {}  # (bar_idx, beat) -> Chord
    for mm in ch.getElementsByClass(stream.Measure):
        bi = mm.number - 1
        sounding = list(mm.recurse().getElementsByClass(chord.Chord))
        for b in range(beats_per_bar):
            cand = [c for c in sounding if c.offset <= b < c.offset + c.quarterLength]
            if cand:
                chords_by_beat[(bi, b)] = cand[-1]
    labels = {}  # (bar, beat) -> dict
    for (bi, b), c in chords_by_beat.items():
        pcs = sorted({p.pitchClass for p in c.pitches})
        if len(pcs) < 2:
            continue
        bass = min(c.pitches, key=lambda p: p.midi).pitchClass
        root, name, score = label_chord(pcs, bass)
        k_obj = keys_bar[bi]
        inv = (bass - root) % 12
        inv_name = {0: "grond", 3: "1e", 4: "1e", 7: "2e", 10: "3e", 11: "3e"}.get(inv, "anders")
        labels[(bi, b)] = dict(root=root, name=name, deg=degree(root, k_obj), inv=inv_name,
                               n=len(c.pitches), score=score, low=min(p.midi for p in c.pitches),
                               high=max(p.midi for p in c.pitches))

    # sectie-statistieken
    sec_stats = []
    fermata_bars = set()
    for mm in measures_R + measures_L:
        for el in mm.recurse().notes:
            if any(isinstance(e, expressions.Fermata) for e in el.expressions):
                fermata_bars.add(mm.number - 1)
    melody = [labels[(bi, b)]["high"] if (bi, b) in labels else np.nan for bi in range(n_bars) for b in range(beats_per_bar)]
    sections = section_labels(feats, fermata_bars, melody, beats_per_bar)
    dyn_by_bar = {}
    for mm in measures_R:
        for d in mm.getElementsByClass("Dynamic"):
            dyn_by_bar[mm.number - 1] = d.value
    for name, i, j in sections:
        labs = [labels[(bi, b)] for bi in range(i, j) for b in range(beats_per_bar) if (bi, b) in labels]
        seq = []
        for l in labs:
            tag = l["deg"] + ("7" if l["name"] in ("dom7", "min7", "maj7", "m7b5", "dim7") else "") + \
                  ("sus" if l["name"].startswith("sus") else "")
            if not seq or seq[-1] != tag:
                seq.append(tag)
        vel = [el.volume.velocity for mm in measures_R[i:j] for el in mm.recurse().notes if el.volume.velocity]
        rh_top = [max(p.midi for p in el.pitches) for mm in measures_R[i:j] for el in mm.recurse().notes]
        lh_low = [min(p.midi for p in el.pitches) for mm in measures_L[i:j] for el in mm.recurse().notes]
        rh_sizes = [len(el.pitches) for mm in measures_R[i:j] for el in mm.recurse().notes]
        lh_sizes = [len(el.pitches) for mm in measures_L[i:j] for el in mm.recurse().notes]
        lh_on = [len([el for el in mm.recurse().notes if not (el.tie and el.tie.type != "start")]) for mm in measures_L[i:j]]
        # melodie (bovenstem RH) als intervalreeks
        mel = []
        for mm in measures_R[i:j]:
            for el in mm.recurse().notes:
                if el.tie is not None and el.tie.type != "start":
                    continue
                mel.append(max(p.midi for p in el.pitches))
        intervals = [b - a for a, b in zip(mel, mel[1:])]
        sec_stats.append(dict(
            name=name, start=i, end=j, bars=j - i,
            frac8=float(np.mean([feats[b]["frac8"] for b in range(i, j)])),
            chord_size=float(np.mean([feats[b]["chord_size"] for b in range(i, j)])),
            rh_size=float(np.mean(rh_sizes)) if rh_sizes else 0, lh_size=float(np.mean(lh_sizes)) if lh_sizes else 0,
            lh_onsets_per_bar=float(np.mean(lh_on)) if lh_on else 0,
            vel=float(np.mean(vel)) if vel else np.nan,
            rh_top_mean=float(np.mean(rh_top)) if rh_top else np.nan, rh_top_max=max(rh_top) if rh_top else None,
            lh_low_mean=float(np.mean(lh_low)) if lh_low else np.nan, lh_low_min=min(lh_low) if lh_low else None,
            first_chords=seq[:3], last_chords=seq[-4:], chord_changes_per_bar=len(seq) / max(1, j - i),
            degrees=Counter(l["deg"] for l in labs), qualities=Counter(l["name"] for l in labs),
            inversions=Counter(l["inv"] for l in labs),
            bigrams=Counter(zip(seq, seq[1:])),
            fermata_at_end=any(b in fermata_bars for b in range(max(i, j - 2), j)),
            dynamics=[dyn_by_bar[b] for b in range(i, j) if b in dyn_by_bar],
            intervals=intervals, melody=mel,
        ))

    # citeert voorspel/naspel de koraalmelodie? (5-grammen van intervallen)
    koraal = [x for x in sec_stats if x["name"].startswith("koraal")]
    kor_ngr = set().union(*[ngrams(x["intervals"]) for x in koraal]) if koraal else set()
    for x in sec_stats:
        if not x["name"].startswith("koraal"):
            g = ngrams(x["intervals"])
            x["quote_frac"] = len(g & kor_ngr) / len(g) if g and kor_ngr else None

    # cadensen bij fermates (laatste 2 verschillende akkoorden vóór/op de fermatemaat)
    cadences = []
    for fb in sorted(fermata_bars):
        seq = []
        for bi in range(max(0, fb - 1), fb + 1):
            for b in range(beats_per_bar):
                l = labels.get((bi, b))
                if l:
                    tag = l["deg"] + ("7" if l["name"] == "dom7" else "")
                    if not seq or seq[-1][0] != tag:
                        seq.append((tag, l["inv"]))
        if len(seq) >= 2:
            cadences.append((seq[-2][0], seq[-1][0], seq[-1][1]))

    # bas: beweging
    bass_seq = [labels[(bi, b)]["low"] for bi in range(n_bars) for b in range(beats_per_bar) if (bi, b) in labels]
    moves = Counter()
    for a, b in zip(bass_seq, bass_seq[1:]):
        d = abs(b - a)
        moves["liggend" if d == 0 else "stap" if d <= 2 else "octaaf" if d % 12 == 0 else "sprong"] += 1
    # orgelpunt: zelfde bas >= 4 tellen
    pedal_points, run = 0, 1
    for a, b in zip(bass_seq, bass_seq[1:]):
        run = run + 1 if a == b else 1
        if run == 4:
            pedal_points += 1
    # octaafverdubbeling in LH
    lh_oct = 0
    lh_chords = 0
    for mm in measures_L:
        for el in mm.recurse().notes:
            if len(el.pitches) >= 2:
                lh_chords += 1
                ps = sorted(p.midi for p in el.pitches)
                if any((b - a) == 12 for a in ps for b in ps):
                    lh_oct += 1
    # melodie verdubbeld in octaven in RH?
    rh_oct = rh_chords = 0
    for mm in measures_R:
        for el in mm.recurse().notes:
            if len(el.pitches) >= 2:
                rh_chords += 1
                ps = sorted(p.midi for p in el.pitches)
                if ps[-1] - ps[0] == 12 or any(ps[-1] - p == 12 for p in ps):
                    rh_oct += 1

    # ruwe MIDI: pedaal, legato, gebroken akkoorden, rit.
    pm = pretty_midi.PrettyMIDI(str(raw_path))
    notes = sorted((n for i in pm.instruments for n in i.notes), key=lambda n: n.start)
    end = max(n.end for n in notes)
    cc = sorted((c for i in pm.instruments for c in i.control_changes if c.number == 64), key=lambda c: c.time)
    down_time, down, t_prev = 0.0, False, 0.0
    for c in cc:
        if down:
            down_time += c.time - t_prev
        down, t_prev = c.value >= 64, c.time
    pedal_frac = down_time / end if cc else None
    pedal_changes_per_min = sum(1 for c in cc if c.value >= 64) / (end / 60) if cc else None
    # gebroken akkoorden: groepjes noten binnen 120 ms met spreiding > 30 ms
    onsets = np.array([n.start for n in notes])
    spread, groups = 0, 0
    i = 0
    while i < len(onsets):
        j = i
        while j + 1 < len(onsets) and onsets[j + 1] - onsets[i] < 0.12:
            j += 1
        if j - i >= 2:
            groups += 1
            if onsets[j] - onsets[i] > 0.03:
                spread += 1
        i = j + 1
    arpeggio_frac = spread / groups if groups else None
    # legato: duur / afstand tot volgende noot in hetzelfde register
    ratios = []
    for a, b in zip(notes, notes[1:]):
        gap = b.start - a.start
        if 0.1 < gap < 2.0:
            ratios.append(min(2.0, (a.end - a.start) / gap))
    legato = float(np.median(ratios)) if ratios else None
    # rit. aan het slot: tempo laatste 8 tellen t.o.v. mediaan (via onsets in laatste 10 s vs. bpm)
    rit = None
    if bpm:
        beat = 60 / bpm
        last = [n for n in notes if n.start > end - 8 * beat * 1.5]
        first_last = min(n.start for n in last) if last else None
        # onsetgroepen tellen in het laatste stuk en vergelijken met verwachte tellen
        rit = None
    vel_all = [n.velocity for n in notes]
    # tempo-curve uit de audio: rit. aan het slot en bij fermates
    import librosa
    mp3 = DIR / "mp3" / f"{xml_path.stem}.mp3"
    rit_end = rit_fermata = None
    if mp3.exists():
        audio, sr = librosa.load(str(mp3), sr=22050, mono=True)
        _, bt = librosa.beat.beat_track(y=audio, sr=sr, units="time", trim=False)
        bt = np.asarray(bt)
        if len(bt) > 20:
            per = np.diff(bt)
            med = np.median(per)
            rit_end = float(np.mean(per[-6:]) / med)  # > 1 = langzamer aan het slot
    # begin en slot
    first_bar_chords = [labels[(0, b)] for b in range(beats_per_bar) if (0, b) in labels]
    last_lab = [labels[(bi, b)] for bi in range(n_bars - 2, n_bars) for b in range(beats_per_bar) if (bi, b) in labels]
    final = last_lab[-1] if last_lab else None
    final_seq = []
    for bi in range(max(0, n_bars - 4), n_bars):
        for b in range(beats_per_bar):
            l = labels.get((bi, b))
            if l:
                tag = l["deg"] + ("7" if l["name"] == "dom7" else "")
                if not final_seq or final_seq[-1] != tag:
                    final_seq.append(tag)
    rh_top_all = [max(p.midi for p in el.pitches) for mm in measures_R for el in mm.recurse().notes]
    last_rh = [max(p.midi for p in el.pitches) for mm in measures_R[-2:] for el in mm.recurse().notes]
    first_rh = [len(el.pitches) for mm in measures_R[:4] for el in mm.recurse().notes]
    ottavas = len(list(R.getElementsByClass("Ottava")))

    return dict(
        title=xml_path.stem, bars=n_bars, bpm=bpm, meter=f"{ts.numerator}/{ts.denominator}",
        keys=[str(k) for k in dict.fromkeys(str(k) for k in keys_bar)],
        key_changes=len({str(k) for k in keys_bar}) - 1,
        duration_s=float(end), sections=sec_stats, cadences=cadences,
        bass_moves=moves, pedal_points_per_100bars=100 * pedal_points / n_bars,
        lh_octave_frac=lh_oct / lh_chords if lh_chords else None, rh_octave_frac=rh_oct / rh_chords if rh_chords else None,
        pedal_frac=pedal_frac, pedal_changes_per_min=pedal_changes_per_min, arpeggio_frac=arpeggio_frac,
        legato=legato, vel_mean=float(np.mean(vel_all)), vel_std=float(np.std(vel_all)),
        degrees=Counter(l["deg"] for l in labels.values()), qualities=Counter(l["name"] for l in labels.values()),
        inversions=Counter(l["inv"] for l in labels.values()),
        labels=labels, fermata_bars=sorted(fermata_bars), rit_end=rit_end,
        first_chord=first_bar_chords[0]["deg"] + "/" + first_bar_chords[0]["inv"] if first_bar_chords else None,
        first_chord_quality=first_bar_chords[0]["name"] if first_bar_chords else None,
        final_chord=(final["deg"] + "/" + final["inv"]) if final else None, final_quality=final["name"] if final else None,
        final_n=final["n"] if final else None, final_seq=final_seq[-4:],
        final_top_rel=(max(last_rh) - max(rh_top_all)) if last_rh else None, rh_top_max=max(rh_top_all) if rh_top_all else None,
        first_rh_size=float(np.mean(first_rh)) if first_rh else None, ottavas=ottavas,
        n_fermatas=len(fermata_bars), dynamics_marks=[dyn_by_bar[b] for b in sorted(dyn_by_bar)],
    )


def main():
    out = []
    files = sorted((DIR / "midi").glob("*.musicxml"))
    for x in files:
        raw = DIR / "midi_raw" / f"{x.stem}.transkun.mid"
        if not raw.exists():
            continue
        try:
            r = analyse(x, raw)
            r["compilation"] = any(c in x.stem for c in COMPILATIONS)
            out.append(r)
            print(f"{x.stem[:60]:60s} maten={r['bars']:4d} secties={[ (s['name'], s['bars']) for s in r['sections']]}")
        except Exception as e:
            print("FOUT", x.stem, repr(e))
    def conv(o):
        if isinstance(o, Counter):
            return {str(k): v for k, v in o.items()}
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, dict):
            return {str(k): conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple, set)):
            return [conv(v) for v in o]
        return o
    (DIR / "stijlanalyse.json").write_text(json.dumps([conv({k: v for k, v in r.items() if k != "labels"}) for r in out],
                                                       ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
