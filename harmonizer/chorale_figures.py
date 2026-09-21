"""Conservative fifth/octave accompaniment cells with separate bass anchors.

An anchor is a structural hypothesis, not a certified harmonic root. The
collector does not infer major/minor harmony from a two-pitch-class figure.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from itertools import pairwise
from statistics import median

from .model import Event
from .profile import QUALITIES


def cells(melody, arrangement):
    rows = []
    for i, (offset, num, den) in enumerate(melody.meters):
        stop = melody.meters[i + 1][0] if i + 1 < len(melody.meters) else melody.length
        bar = num * 4 / den
        lengths = sorted({bar, *([bar / 2] if num % 2 == 0 else [])})
        for length in lengths:
            start = offset
            while start + length <= stop + 1e-6:
                end = start + length
                notes = sorted(
                    [
                        n
                        for n in arrangement.notes
                        if n.role == "bass"
                        and n.start < end - 1e-6
                        and n.end > start + 1e-6
                    ],
                    key=lambda n: (n.start, n.pitch),
                )
                if len(notes) >= 3 and abs(notes[0].start - start) < 1e-6:
                    anchor = notes[0].pitch
                    offsets = {n.pitch - anchor for n in notes}
                    serial = all(a.end <= b.start + 1e-6 for a, b in pairwise(notes))
                    if (
                        serial
                        and {0, 7, 12} <= offsets
                        and offsets <= {0, 7, 12, 19, 24}
                    ):
                        top = [
                            n.pitch
                            for n in melody.notes
                            if n.start < end and n.end > start
                        ]
                        if top:
                            rows.append(
                                {
                                    "start": start,
                                    "end": end,
                                    "meter": [num, den],
                                    "length": length,
                                    "anchor": anchor,
                                    "quality": None,
                                    "kind": "fifth_octave",
                                    "register_gap": median(top) - anchor,
                                    "events": [
                                        (
                                            n.pitch - anchor,
                                            n.start - start,
                                            min(n.end, end) - start,
                                        )
                                        for n in notes
                                    ],
                                    "coverage": sum(
                                        min(n.end, end) - max(n.start, start)
                                        for n in notes
                                    )
                                    / length,
                                    "status": "structural_hypothesis",
                                }
                            )
                start = end
    return rows


def fit_figures(model, references):
    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError(
            "Figure training must exactly match the disclosed source identities."
        )
    result = deepcopy(model)
    result["decoder"] = "structural_figures_v1"
    result["accompaniment_cells"] = [
        dict(
            row,
            source_id=e["source_id"],
            group=e["group"],
            source_sha256=e.get("source_sha256"),
        )
        for e, m, a in references
        for row in cells(m, a)
    ]
    return result


def covers(intervals, start, end):
    position = start
    for a, b in sorted(intervals):
        if a > position + 1e-6:
            return False
        position = max(position, b)
    return position >= end - 1e-6


def apply_figure(arrangement, melody, start, pattern):
    end = start + pattern["length"]
    if pattern["coverage"] < 1 - 1e-6 or end > melody.length + 1e-6:
        return None
    # Only realize an already stable, root-position harmony. Do not re-harmonize
    # each arpeggio attack or manufacture a major third from an open fifth.
    harmony = [
        h for h in arrangement.harmony if h.start < end - 1e-6 and h.end > start + 1e-6
    ]
    if not harmony or len({(h.root, h.quality) for h in harmony}) != 1:
        return None
    if not covers([(h.start, h.end) for h in harmony], start, end):
        return None
    root, quality = harmony[0].root, harmony[0].quality
    if quality not in ("major", "minor", "dom7", "min7", "maj7"):
        return None
    notes = [
        n for n in arrangement.notes if n.start < end - 1e-6 and n.end > start + 1e-6
    ]
    left = [n for n in notes if n.role == "bass"]
    if not covers([(n.start, n.end) for n in left], start, end):
        return None
    if not left or any(
        min(n.pitch for n in left if n.start <= t + 1e-7 < n.end) % 12 != root
        for t in {
            start,
            *(n.start for n in left if n.start >= start),
            *(n.end for n in left if start < n.end < end),
        }
        if any(n.start <= t + 1e-7 < n.end for n in left)
    ):
        return None
    top = [n.pitch for n in melody.notes if n.start < end and n.end > start]
    if not top:
        return None
    target = median(top) - pattern["register_gap"]
    anchors = sorted(
        [p for p in range(28, 61) if p % 12 == root], key=lambda p: abs(p - target)
    )
    upper = [n for n in notes if n.role != "bass"]
    chosen = None
    for anchor in anchors:
        figure = [
            Event(anchor + p, start + a, b - a, 72, "bass")
            for p, a, b in pattern["events"]
        ]
        if all(
            n.pitch
            < min(
                (
                    u.pitch
                    for u in upper
                    if u.start < n.end - 1e-6 and u.end > n.start + 1e-6
                ),
                default=109,
            )
            for n in figure
        ):
            chosen = figure
            break
    if chosen is None:
        return None
    expected = {(root + p) % 12 for p in QUALITIES[quality]}
    if not expected <= {n.pitch % 12 for n in [*upper, *chosen]}:
        return None
    result = []
    for n in arrangement.notes:
        if n.role != "bass" or n.end <= start + 1e-6 or n.start >= end - 1e-6:
            result.append(n)
        else:
            if n.start < start - 1e-6:
                result.append(replace(n, duration=start - n.start))
            if n.end > end + 1e-6:
                result.append(replace(n, start=end, duration=n.end - end))
    result.extend(chosen)
    return replace(arrangement, notes=result), chosen[0].pitch


def generate(melody, model, seed=0, tempos=None):
    from .chorale_model import generate_chorale

    arrangement = generate_chorale(
        melody, dict(model, decoder="two_pass_bass_v1"), seed, tempos
    )
    trace = []
    for i, (offset, num, den) in enumerate(melody.meters):
        stop = melody.meters[i + 1][0] if i + 1 < len(melody.meters) else melody.length
        length = num * 4 / den / (2 if num % 2 == 0 else 1)
        start = offset
        while start + length <= stop + 1e-6:
            pool = [
                p
                for p in model["accompaniment_cells"]
                if p["meter"] == [num, den]
                and abs(p["length"] - length) < 1e-6
                and p["coverage"] >= 1 - 1e-6
            ]
            # One observed shape per meter, retained across eligible measures.
            target_register = median(n.pitch for n in melody.notes)
            pool.sort(
                key=lambda p: (
                    abs(p["anchor"] + p["register_gap"] - target_register),
                    p["source_id"],
                    p["start"],
                )
            )
            for pattern in pool:
                changed = apply_figure(arrangement, melody, start, pattern)
                if changed:
                    arrangement, anchor = changed
                    trace.append(
                        {
                            "start": start,
                            "end": start + length,
                            "anchor": anchor,
                            "source_id": pattern["source_id"],
                            "source_start": pattern["start"],
                        }
                    )
                    break
            start += length
    arrangement.diagnostics = dict(
        arrangement.diagnostics,
        decoder="structural_figures_v1",
        structural_figures=trace,
        scope="Stable root-position harmony only; explicit source fifth/octave cells; experimental texture realization.",
    )
    return arrangement
