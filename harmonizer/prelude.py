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


def _harmony_plan(melody, ends, bar, profile, source, rng, section, arrival_root=None, terminal_quality=None):
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
    if section == "Naspel" and terminal_quality and (melody.tonic, terminal_quality) not in options:
        options.append((melody.tonic, terminal_quality))
    for bi, (a, b, pi, cadential) in enumerate(blocks):
        extensions = []
        for old, path in beam:
            for root, q in options:
                final = bi == len(blocks) - 1
                tonic_quality = terminal_quality or ("major" if MODES[melody.mode][2] == 4 else "minor")
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


def free_section(melody, length, section, seed=0, profile=None, settings=None, material=None):
    from .thematic import free_section as compose

    return compose(melody, length, section, seed, profile, settings, material)


def free_accompaniment(harmonies, melody, plan, profile):
    if "accompaniment" in plan:
        return [Event(**n) for n in plan["accompaniment"]]

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
