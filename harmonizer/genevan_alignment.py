"""Audit a converted melody against a separately sourced Genevan pitch sequence.

The LilyPond reader intentionally accepts only the small monophonic subset used
by the inspected melody definitions. It rejects unsupported notation.
"""

import re
from collections import Counter
from itertools import pairwise

from .model import Event

LETTERS = "cdefgab"
NATURAL = (0, 2, 4, 5, 7, 9, 11)
TOKEN = re.compile(r"([a-gr])(is|es|s)?([,']*)(1|2|4|8|16)?(\.)?")


def read_melody(text):
    from dataclasses import replace

    found = re.search(r"mel\s*=\s*\\relative\s+([a-g][,']*)\s*\{", text)
    if not found:
        raise ValueError("No supported relative melody block.")
    initial = found.group(1)
    begin = found.end()
    depth, stop = 1, begin
    while stop < len(text) and depth:
        depth += (text[stop] == "{") - (text[stop] == "}")
        stop += 1
    if depth:
        raise ValueError("Unclosed melody block.")
    body = re.sub(r"%[^\n]*", "", text[begin : stop - 1])
    body = re.sub(r"([{}])", r" \1 ", body).replace("(", " ").replace(")", " ")
    tokens = body.split()
    octave = 3 + initial.count("'") - initial.count(",")
    previous = octave * 7 + LETTERS.index(initial[0])
    duration, time, notes = 1.0, 0.0, []

    def consume(position, nested=False):
        nonlocal previous, duration, time
        while position < len(tokens):
            raw = tokens[position]
            position += 1
            if raw == "}":
                if not nested:
                    raise ValueError("Unexpected closing brace.")
                return position
            if raw == r"\breathe":
                continue
            if raw == r"\repeat":
                if tokens[position : position + 3] not in (
                    ["volta", "2", "{"],
                    ["unfold", "2", "{"],
                ):
                    raise ValueError("Only twofold volta or unfold repeats are supported.")
                onset, index = time, len(notes)
                position = consume(position + 3, True)
                length = time - onset
                phrase = notes[index:]
                notes.extend(replace(n, start=n.start + length) for n in phrase)
                time += length
                continue
            token = TOKEN.fullmatch(raw)
            if not token:
                raise ValueError(f"Unsupported melody token: {raw}")
            letter, accidental, marks, value, dot = token.groups()
            if value:
                duration = 4 / int(value) * (1.5 if dot else 1)
            elif dot:
                raise ValueError("A dot without a duration is unsupported.")
            if letter == "r":
                if accidental or marks:
                    raise ValueError("Invalid rest.")
            else:
                index = LETTERS.index(letter)
                degree = (previous // 7) * 7 + index
                while degree - previous > 3:
                    degree -= 7
                while previous - degree > 3:
                    degree += 7
                degree += 7 * (marks.count("'") - marks.count(","))
                shift = (
                    1 if accidental == "is" else -1 if accidental in ("es", "s") else 0
                )
                notes.append(
                    Event(
                        12 * (degree // 7 + 1) + NATURAL[index] + shift, time, duration
                    )
                )
                previous = degree
            time += duration
        if nested:
            raise ValueError("Unclosed repeat.")
        return position

    consume(0)
    return notes


def read_key(text):
    from .model import MODES

    found = re.search(r"\\key\s+([a-g])(is|es|s)?\s+\\([a-z]+)", text)
    if not found or found[3] not in MODES:
        raise ValueError("No supported modal key declaration.")
    letter, accidental, mode = found.groups()
    shift = 1 if accidental == "is" else -1 if accidental else 0
    return (NATURAL[LETTERS.index(letter)] + shift) % 12, mode


def align(canonical, observed):
    """Global edit alignment. Missing canonical notes remain explicit omissions."""

    def run(transpose):
        table = [[None] * (len(observed) + 1) for _ in range(len(canonical) + 1)]
        table[0][0] = (0, None)
        for i in range(len(canonical) + 1):
            for j in range(len(observed) + 1):
                if not i and not j:
                    continue
                choices = []
                if i:
                    choices.append((table[i - 1][j][0] + 2, "missing"))
                if j:
                    choices.append((table[i][j - 1][0] + 1, "extra"))
                if i and j:
                    diff = observed[j - 1].pitch - (canonical[i - 1].pitch + transpose)
                    cost = 0 if diff == 0 else 0.5 if abs(diff) == 12 else 2.5
                    choices.append(
                        (
                            table[i - 1][j - 1][0] + cost,
                            "match"
                            if cost == 0
                            else "octave"
                            if cost == 0.5
                            else "mismatch",
                        )
                    )
                table[i][j] = min(choices, key=lambda x: x[0])
        i, j = len(canonical), len(observed)
        path = []
        while i or j:
            kind = table[i][j][1]
            path.append(
                {
                    "kind": kind,
                    "canonical_index": i - 1 if kind != "extra" else None,
                    "observed_index": j - 1 if kind != "missing" else None,
                }
            )
            if kind != "extra":
                i -= 1
            if kind != "missing":
                j -= 1
        return {
            "cost": table[-1][-1][0],
            "transpose": transpose,
            "alignment": list(reversed(path)),
        }

    best = min(
        (run(t) for t in range(-24, 25)), key=lambda r: (r["cost"], abs(r["transpose"]))
    )
    best["counts"] = dict(Counter(r["kind"] for r in best["alignment"]))
    best["canonical_notes"] = len(canonical)
    best["observed_notes"] = len(observed)
    best["status"] = "audit_only_no_source_notes_changed"
    return best


def relabel(melody, arrangement, canonical, tonic, mode):
    """Correct roles only after a complete pitch-sequence match; keep every note."""
    result = align(canonical, melody.notes)
    if result["counts"].get("match", 0) != len(canonical):
        raise ValueError(
            "Canonical melody is incomplete or differs in pitch; review required."
        )
    return _apply_alignment(melody, arrangement, result, tonic, mode)


def _apply_alignment(melody, arrangement, result, tonic, mode):
    from dataclasses import replace

    selected = [
        melody.notes[row["observed_index"]]
        for row in result["alignment"]
        if row["kind"] == "match"
    ]
    keys = {(n.pitch, n.start, n.end) for n in selected}
    fermatas = [
        t for t in melody.fermatas if any(abs(n.end - t) < 1e-6 for n in selected)
    ]
    corrected = replace(
        melody,
        notes=selected,
        tonic=(tonic + result["transpose"]) % 12,
        mode=mode,
        fermatas=fermatas,
        phrases=sorted(set(fermatas + [melody.length])),
    )
    corrected.validate()
    notes = [
        replace(
            n,
            role="melody"
            if (n.pitch, n.start, n.end) in keys
            else "inner"
            if n.role == "melody"
            else n.role,
        )
        for n in arrangement.notes
    ]
    assert Counter((n.pitch, n.start, n.end) for n in notes) == Counter(
        (n.pitch, n.start, n.end) for n in arrangement.notes
    )
    a = replace(
        arrangement,
        notes=notes,
        tonic=corrected.tonic,
        mode=mode,
        phrases=corrected.phrases,
        fermatas=fermatas,
    )
    return corrected, a, result


def complete_source_path(canonical, observed, *, allow_overlaps=False, bounds=None):
    """Find a complete non-overlapping exact-pitch path through source notes.

    This is an audit alternative to the highest-note heuristic. Timing guides
    the choice between existing notes but is never rewritten. Failure stays
    explicit rather than becoming a fabricated canonical note.
    """
    if not canonical or not observed:
        return None
    best = None
    allowed = [
        (i, n)
        for i, n in enumerate(observed)
        if bounds is None or bounds[0] <= n.start < n.end <= bounds[1]
    ]
    for transpose in sorted(
        {
            n.pitch - canonical[0].pitch
            for _, n in allowed
            if -24 <= n.pitch - canonical[0].pitch <= 24
        }
    ):
        layers = [
            [i for i, n in allowed if n.pitch == c.pitch + transpose] for c in canonical
        ]
        if any(not layer for layer in layers):
            continue
        for first in layers[0]:
            for scale in (0.5, 1, 2):
                offset = observed[first].start - canonical[0].start * scale
                states = {first: (0.0, [first])}
                for c, layer in zip(canonical[1:], layers[1:]):
                    following = {}
                    for j in layer:
                        eligible = [
                            (cost, path)
                            for i, (cost, path) in states.items()
                            if (
                                observed[i].start < observed[j].start - 1e-7
                                if allow_overlaps
                                else observed[i].end <= observed[j].start + 1e-7
                            )
                        ]
                        if not eligible:
                            continue
                        cost, path = min(eligible, key=lambda item: item[0])
                        following[j] = (
                            cost + abs(observed[j].start - (offset + c.start * scale)),
                            path + [j],
                        )
                    states = following
                    if not states:
                        break
                if states:
                    cost, path = min(states.values(), key=lambda item: item[0])
                    candidate = {
                        "transpose": transpose,
                        "timing_scale_hint": scale,
                        "timing_offset_hint": offset,
                        "mean_onset_deviation": cost / len(canonical),
                        "observed_indices": path,
                        "overlaps": [
                            {
                                "previous_index": i,
                                "next_index": j,
                                "quarters": observed[i].end - observed[j].start,
                            }
                            for i, j in pairwise(path)
                            if observed[i].end > observed[j].start + 1e-7
                        ],
                        "search_bounds": bounds,
                        "selected_span": [
                            observed[path[0]].start,
                            observed[path[-1]].end,
                        ],
                        "maximum_source_rest": max(
                            (
                                observed[j].start - observed[i].end
                                for i, j in pairwise(path)
                            ),
                            default=0,
                        ),
                        "status": "complete_pitch_path_requires_review",
                    }
                    if (
                        best is None
                        or candidate["mean_onset_deviation"]
                        < best["mean_onset_deviation"]
                    ):
                        best = candidate
    return best


def align_excerpt(canonical, observed):
    """Match all observed notes against a contiguous portion of the known tune.

    Unobserved canonical prefix/suffix are free. Missing notes inside the chosen
    portion are penalized. This is a diagnostic, not automatic certification.
    """
    if not canonical or not observed:
        raise ValueError("Both melody sequences are required.")
    candidates = []
    for transpose in range(-24, 25):
        table = [[(0, None)] * (len(observed) + 1) for _ in range(len(canonical) + 1)]
        for j in range(1, len(observed) + 1):
            table[0][j] = (j, "extra")
        for i, c in enumerate(canonical, 1):
            for j, n in enumerate(observed, 1):
                diff = n.pitch - c.pitch - transpose
                mismatch = 0 if diff == 0 else 0.5 if abs(diff) == 12 else 2.5
                choices = [
                    (
                        table[i - 1][j - 1][0] + mismatch,
                        "match"
                        if mismatch == 0
                        else "octave"
                        if mismatch == 0.5
                        else "mismatch",
                    ),
                    (table[i - 1][j][0] + 2, "missing"),
                    (table[i][j - 1][0] + 1, "extra"),
                ]
                table[i][j] = min(choices, key=lambda x: x[0])
        i = min(range(1, len(canonical) + 1), key=lambda i: table[i][-1][0])
        cost = table[i][-1][0]
        j = len(observed)
        path = []
        while j:
            kind = table[i][j][1]
            path.append(
                {
                    "kind": kind,
                    "canonical_index": i - 1 if kind != "extra" else None,
                    "observed_index": j - 1 if kind != "missing" else None,
                }
            )
            if kind != "extra":
                i -= 1
            if kind != "missing":
                j -= 1
        path.reverse()
        candidates.append(
            {
                "cost": cost,
                "transpose": transpose,
                "alignment": path,
                "counts": dict(Counter(x["kind"] for x in path)),
            }
        )
    return min(candidates, key=lambda row: (row["cost"], abs(row["transpose"])))


def relabel_excerpt(melody, arrangement, canonical, tonic, mode, *, minimum_notes=8):
    """Require pitch and constant onset correspondence before reassigning roles.

    This conservative automatic route rejects a nonmelodic prefix and any
    omitted, changed or octave-shifted canonical tone inside the matched span.
    """
    result = align_excerpt(canonical, melody.notes)
    if any(result["counts"].get(kind, 0) for kind in ("missing", "mismatch", "octave")):
        raise ValueError("Incomplete or differing canonical excerpt.")
    matches = [row for row in result["alignment"] if row["kind"] == "match"]
    if len(matches) < minimum_notes or matches[0]["observed_index"] != 0:
        raise ValueError(
            "Insufficient correspondence or an unconfirmed leading region."
        )
    timing = None
    for scale in (0.5, 1, 2):
        offsets = [
            melody.notes[row["observed_index"]].start
            - canonical[row["canonical_index"]].start * scale
            for row in matches
        ]
        if max(offsets) - min(offsets) < 1e-6:
            timing = {"scale": scale, "offset": offsets[0]}
            break
    if timing is None:
        raise ValueError("Pitch matches do not form a consistent rhythmic excerpt.")
    result["timing_correspondence"] = timing
    result["canonical_range"] = [
        matches[0]["canonical_index"],
        matches[-1]["canonical_index"] + 1,
    ]
    result["scope"] = "Pitch and onset correspondence; source release times retained."
    return _apply_alignment(melody, arrangement, result, tonic, mode)
