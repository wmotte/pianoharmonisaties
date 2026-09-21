"""Phrase plans, transformed motifs and variable piano textures for free sections."""

import math
import random
from collections import Counter
from dataclasses import replace
from itertools import pairwise

from .model import MODES, Event, Melody
from .profile import QUALITIES


def _phrase_ends(length, bar, source, rng):
    observed = [
        max(2, min(6, round(x))) for x in source.get("phrase_bars", []) if 2 <= x <= 8
    ]
    # Inferred phrase lengths are uncertain, so allow a one-bar extension or
    # contraction. One sparse source must not become another fixed loop.
    choices = (
        observed + [y for x in observed for y in (max(2, x - 1), min(6, x + 1))]
        if observed
        else [3, 4, 5]
    )
    ends, cursor = [], 0.0
    previous_spans = []
    while cursor < length:
        eligible = [
            x
            for x in choices
            if len(previous_spans) < 2 or previous_spans[-2:] != [x, x]
        ]
        chosen = rng.choice(eligible or choices)
        previous_spans.append(chosen)
        span = chosen * bar
        if length - cursor - span < 2 * bar:
            span = length - cursor
        cursor = min(length, cursor + span)
        ends.append(cursor)
    return ends


def _motif(rng):
    # A connected diatonic gesture, not an arpeggio index cycling forever.
    length = rng.choice((4, 5, 6))
    steps = [0]
    direction = rng.choice((-1, 1))
    for i in range(length - 1):
        move = rng.choices((0, 1, 2), weights=(1, 6, 2))[0]
        if i == length // 2:
            direction *= -1
        steps.append(max(-4, min(4, steps[-1] + direction * move)))
    if len(set(steps)) == 1:
        steps[1] = 1
    return steps


def _harmony_plan(melody, ends, bar, profile, source, rng, section, arrival_root=None):
    from .engine import chord_options

    scale = {(melody.tonic + x) % 12 for x in MODES[melody.mode]}
    options = [
        (r, q)
        for r, q in chord_options(melody)
        if q != "dim" and len({(r + x) % 12 for x in QUALITIES[q]} - scale) <= 1
    ]
    source_counts = Counter()
    source_hs = source.get("harmonies", [])
    if source_hs:
        for _, _, r, q in source_hs:
            source_counts[q] += 1
    counts = profile.get("mode_chords", {}).get(melody.mode, profile.get("chords", {}))
    transitions = profile.get("mode_transitions", {}).get(
        melody.mode, profile.get("transitions", {})
    )
    blocks, start = [], 0.0
    for pi, end in enumerate(ends):
        cursor = start
        while cursor < end - 1e-7:
            # The cadence expands, while the middle can move more quickly.
            remain = end - cursor
            span = min(
                remain,
                bar
                if remain <= bar
                else rng.choices((bar / 2, bar), weights=(3, 2))[0],
            )
            blocks.append((cursor, cursor + span, pi, remain <= bar))
            cursor += span
        start = end
    beam = [(0.0, [])]
    target_roots = [(melody.tonic + x) % 12 for x in (0, 7, 5, MODES[melody.mode][5])]
    cadence_targets = [rng.choice(target_roots) for _ in ends]
    for i in range(1, len(cadence_targets)):
        if cadence_targets[i] == cadence_targets[i - 1]:
            cadence_targets[i] = target_roots[
                (target_roots.index(cadence_targets[i]) + 1) % len(target_roots)
            ]
    # Prelude resolves into the first chorale harmony; the coda closes on I/i.
    cadence_targets[-1] = (
        ((melody.tonic if arrival_root is None else arrival_root) + 7) % 12
        if section == "Voorspel"
        else melody.tonic
    )
    if section == "Voorspel" and (cadence_targets[-1], "major") not in options:
        options.append((cadence_targets[-1], "major"))
    for bi, (a, b, pi, cadential) in enumerate(blocks):
        extensions = []
        for old, path in beam:
            for root, q in options:
                final = bi == len(blocks) - 1
                tonic_quality = "major" if MODES[melody.mode][2] == 4 else "minor"
                if final and (
                    root != cadence_targets[-1]
                    or q != (tonic_quality if section == "Naspel" else "major")
                ):
                    continue
                label = f"{(root - melody.tonic) % 12}:{q}"
                pcs = {(root + x) % 12 for x in QUALITIES[q]}
                cost = 0.55 * len(pcs - scale) + (
                    0 if q in ("major", "minor") else 0.45
                )
                cost -= 0.12 * math.log1p(counts.get(label, 0)) + 0.12 * math.log1p(
                    source_counts[q]
                )
                if bi == 0:
                    cost += 0 if root == melody.tonic else 1.4
                if cadential:
                    cost += 0 if root == cadence_targets[pi] else 1.0
                if path:
                    pr, pq = path[-1]
                    prev = f"{(pr - melody.tonic) % 12}:{pq}"
                    cost -= 0.2 * math.log1p(transitions.get(prev + ">" + label, 0))
                    if (root, q) == (pr, pq):
                        cost += 0.5
                    previous_pcs = {(pr + x) % 12 for x in QUALITIES[pq]}
                    cost += 0.12 * len(pcs - previous_pcs)
                    if len(path) >= 2 and (root, q) == path[-2]:
                        cost += 0.35
                    if (
                        len(path) >= 4
                        and path[-4:-2] == path[-2:]
                        and (root, q) == path[-2]
                    ):
                        cost += 2.5
                    if pq == "sus4" and not (
                        root == pr and q in ("major", "minor") or (root - pr) % 12 == 5
                    ):
                        cost += 0.9
                    if pq in ("dom7", "min7") and (root - pr) % 12 not in (5, 9):
                        cost += 0.5
                extensions.append(
                    (old + cost + rng.uniform(-0.45, 0.45), path + [(root, q)])
                )
        beam = sorted(extensions, key=lambda x: x[0])[:16]
    value, path = beam[0]
    return [
        (a, b, pi, cad, *ch) for (a, b, pi, cad), ch in zip(blocks, path)
    ], value / max(1, len(path))


def free_section(
    melody, length, section, seed=0, profile=None, settings=None, material=None
):
    from .engine import Harmony, voice

    profile = profile or {}
    settings = settings or {"meter": [4, 4], "quarter_bpm": melody.bpm, "source": {}}
    rng = random.Random(seed)
    if length < 2:
        raise ValueError("Een vrij vormdeel vereist minstens twee kwartnoottellen.")
    num, den = settings["meter"]
    bar = num * 4 / den
    source = settings.get("source", {})
    ends = _phrase_ends(length, bar, source, rng)
    motifs = material or [_motif(rng), _motif(rng)]
    harmonic, score = _harmony_plan(
        melody, ends, bar, profile, source, rng, section, settings.get("arrival_root")
    )
    scale = [p for p in range(48, 97) if (p - melody.tonic) % 12 in MODES[melody.mode]]
    plan = []
    start = 0.0
    for i, end in enumerate(ends):
        development = (
            "statement"
            if i == 0
            else "return"
            if i == len(ends) - 1
            else rng.choice(("sequence", "expansion", "answer"))
        )
        family = 0 if development in ("statement", "return") else i % 2
        center = 71 + round(8 * math.sin(math.pi * i / max(1, len(ends) - 1)))
        if section == "Naspel":
            center = 75 - round(9 * i / max(1, len(ends) - 1))
        plan.append(
            {
                "start": start,
                "end": end,
                "function": development,
                "motif": family,
                "center": center,
                "density": 2 if i == 0 else 4 if i == len(ends) - 2 else 3,
                "pedal_point": i == 0 or development == "return",
            }
        )
        start = end
    # Short optional quotations are a minority of the section; independent motifs
    # supply the main material. Do not change rhythm every two beats by a loop.
    references = []
    quote_phrase = (
        rng.randrange(1, len(plan)) if section == "Voorspel" and len(plan) > 2 else None
    )
    top, harmonies = [], []
    previous = None
    previous_top = None
    resolution = None
    for a, b, pi, cadential, root, quality in harmonic:
        phrase = plan[pi]
        contour = motifs[phrase["motif"]]
        if phrase["function"] == "answer":
            contour = [-x for x in contour]
        pcs = {(root + x) % 12 for x in QUALITIES[quality]}
        center = phrase["center"]
        chordtones = [p for p in scale if p % 12 in pcs and 60 <= p <= 88]
        anchor = min(
            chordtones,
            key=lambda p: (
                abs(p - center) + (0.35 * abs(p - previous_top) if previous_top else 0)
            ),
        )
        anchor_index = scale.index(anchor)
        rhythm_values = [
            float(x)
            for x in source.get("rhythm_counts", {})
            if float(x) in (0.5, 1, 1.5, 2)
        ] or [0.5, 1, 2]
        weights = [
            math.sqrt(source.get("rhythm_counts", {}).get(str(x), 1))
            for x in rhythm_values
        ]
        # One rhythm per motif family is shared across its transformations.
        rr = random.Random(seed + phrase["motif"] * 137)
        pattern = rr.choices(rhythm_values, weights=weights, k=len(contour))
        if phrase["function"] == "expansion" or section == "Naspel":
            pattern = [min(3, x * 2) for x in pattern]
        cursor = a
        note_index = round((a - phrase["start"]) * 2) % len(contour)
        quote = pi == quote_phrase and a == phrase["start"]
        if quote:
            references.append({"start": a, "end": min(b, a + 2), "notes": 3})
        while cursor < b - 1e-7:
            final = b == length
            remaining = b - cursor
            duration = (
                remaining
                if final
                else min(remaining, pattern[note_index % len(pattern)])
            )
            desired = scale[
                max(
                    0,
                    min(
                        len(scale) - 1,
                        anchor_index + contour[note_index % len(contour)],
                    ),
                )
            ]
            if quote and cursor < a + 2:
                fragment = melody.notes[: min(5, len(melody.notes))]
                quote_index = min(round((cursor - a) * 2), len(fragment) - 1)
                displacement = fragment[quote_index].pitch - fragment[0].pitch
                desired = min(scale, key=lambda p: abs(p - anchor - displacement))
                duration = min(0.5 if cursor - a < 1 else 1, remaining, a + 2 - cursor)
            strong = abs((cursor - phrase["start"]) % bar) < 1e-7 or cursor == a
            if final:
                desired = min(
                    chordtones,
                    key=lambda p: abs(
                        p - (melody.notes[0].pitch + 5 if section == "Voorspel" else 65)
                    ),
                )
            elif resolution is not None:
                desired = min(chordtones, key=lambda p: abs(p - resolution))
                resolution = None
            elif strong or remaining <= duration or cadential:
                desired = min(
                    chordtones,
                    key=lambda p: (
                        abs(p - desired)
                        + (0.4 * abs(p - previous_top) if previous_top else 0)
                    ),
                )
            else:
                # A neighbour is permitted only when the next step resolves to a
                # chord tone. Keep the line connected and within the hand span.
                desired = min(chordtones, key=lambda p: abs(p - desired))
                if (
                    previous_top in chordtones
                    and duration <= 1
                    and remaining > duration
                    and rng.random() < 0.25
                ):
                    neighbors = [p for p in scale if abs(p - previous_top) in (1, 2)]
                    if neighbors:
                        desired = min(neighbors, key=lambda p: abs(p - desired))
                        if desired % 12 not in pcs:
                            resolution = previous_top
            bass, inner, _cost = voice(
                root,
                quality,
                desired,
                previous,
                melody.tonic,
                profile,
                root_position=final,
            )
            if bass is None:
                raise ValueError("Geen speelbare ligging voor vrij vormdeel.")
            h = Harmony(cursor, cursor + duration, root, quality, bass, inner)
            top.append(Event(desired, cursor, duration, role="motif"))
            harmonies.append(h)
            previous, previous_top = h, desired
            cursor += duration
            note_index += 1
    result = Melody(
        top,
        length,
        [(0, num, den)],
        ends,
        melody.tonic,
        melody.mode,
        settings["quarter_bpm"],
    )
    result.validate()
    for reference in references:
        reference["notes"] = sum(
            reference["start"] <= n.start < reference["end"] for n in top
        )
    return (
        result,
        harmonies,
        score,
        {
            "approach": "phrase_motif_development",
            "phrases": plan,
            "motifs": motifs,
            "melodic_references": references,
            "reference_beats": sum(x["end"] - x["start"] for x in references),
            "reference_fraction": sum(x["end"] - x["start"] for x in references)
            / length,
            "source_id": source.get("source_id"),
            "source_sha256": source.get("source_sha256"),
            "source_reviewed": source.get("reviewed", False),
            "settings": {k: v for k, v in settings.items() if k != "source"},
        },
    )


def free_accompaniment(harmonies, melody, plan, profile):
    from .engine import accompaniment

    full = accompaniment(harmonies, melody, 0, profile)
    result = []
    final_start = harmonies[-1].start
    for n in full:
        # Split sustained notes at phrase boundaries before selecting texture.
        boundaries = sorted(
            {
                n.start,
                n.end,
                *(p["start"] for p in plan["phrases"] if n.start < p["start"] < n.end),
                *([final_start] if n.start < final_start < n.end else []),
            }
        )
        for a, b in pairwise(boundaries):
            phrase = next(p for p in plan["phrases"] if p["start"] <= a < p["end"])
            density = 4 if a >= final_start else phrase["density"]
            if n.role == "tenor" and density < 4 or n.role == "alto" and density < 3:
                continue
            # An occasional written broken entry, never the final chord.
            broken = (
                phrase["function"] == "expansion"
                and a == phrase["start"]
                and b - a >= 2
                and a < final_start
            )
            delay = (
                (1.0 if n.role == "alto" else 0.5 if n.role == "tenor" else 0)
                if broken
                else 0
            )
            result.append(replace(n, start=a + delay, duration=b - a - delay))
    # Sustain a consonant tonic/dominant bass beneath the opening phrase if all
    # upper notes permit it. This never forces a dissonant pedal into the score.
    for phrase in plan["phrases"]:
        if not phrase["pedal_point"] or phrase["end"] == melody.length:
            continue
        basses = [
            n
            for n in result
            if n.role == "bass" and phrase["start"] <= n.start < phrase["end"]
        ]
        if not basses:
            continue
        pedal = basses[0].pitch
        hs = [h for h in harmonies if phrase["start"] <= h.start < phrase["end"]]
        if all(
            pedal % 12 in {(h.root + x) % 12 for x in QUALITIES[h.quality]} for h in hs
        ) and all(
            pedal < n.pitch <= pedal + 12
            for n in result
            if n.role == "tenor" and n.start < phrase["end"] and n.end > phrase["start"]
        ):
            result = [n for n in result if n not in basses]
            result.append(
                Event(
                    pedal, phrase["start"], phrase["end"] - phrase["start"], 62, "bass"
                )
            )
    return result
