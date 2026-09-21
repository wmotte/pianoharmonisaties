"""Experimental whole-line voicing with fixed bass, melody and rhythm."""

import math
from dataclasses import replace
from itertools import pairwise

from .chorale_phrase_transfer import _local_loss
from .chorale_targets import compatible_targets
from .model import MODES


def _pitch_bounds(note, fixed, melody, *, right_hand=True):
    """Intersect register and outer-voice bounds over the full note duration."""
    lower, upper = max(21, note.pitch - 12), min(108, note.pitch + 12)
    for n in fixed:
        if n.start < note.end and n.end > note.start:
            lower = max(lower, n.pitch + 1)
    for n in melody.notes:
        if n.start < note.end and n.end > note.start:
            if right_hand:
                lower = max(lower, n.pitch - 12)
            upper = min(upper, n.pitch - 1)
    return lower, upper


def revoice_inner_line(
    notes, melody, targets, *, protected_indices=(), source_contexts=()
):
    """Return a least-cost monophonic inner line, or None if infeasible.

    This opt-in experiment reuses the existing local consonance cost and adds
    movement (0.08 per semitone) and displacement (0.03 per semitone) costs.
    It does not infer voice identities in a polyphonic hand or add attacks.
    Explicitly protected source-note identities retain their original pitch.
    Aligned source contexts can supply automatically verified protections.
    """
    from .chorale_source_protection import source_supported_resolutions

    evidence = source_supported_resolutions(notes, source_contexts)
    protected_indices = [
        *protected_indices,
        *(i for e in evidence for i in e["protected_indices"]),
    ]
    protected_indices = frozenset(protected_indices)
    if any(
        not isinstance(i, int) or not 0 <= i < len(notes) for i in protected_indices
    ):
        raise ValueError("Protected note identity is outside the input")
    indices = sorted(
        (i for i, n in enumerate(notes) if n.role == "inner"),
        key=lambda i: notes[i].start,
    )
    if not indices:
        valid = compatible_targets(
            list(enumerate(n for n in notes if n.role != "melody")),
            melody,
            targets,
            0,
            melody.length,
        )
        return list(notes) if valid else None
    if any(notes[a].end > notes[b].start + 1e-7 for a, b in pairwise(indices)):
        raise ValueError("Inner role must be a single nonoverlapping voice")
    fixed = [n for n in notes if n.role not in ("inner", "melody")]
    pcs = {(melody.tonic + p) % 12 for p in MODES[melody.mode]}

    def transition(left, right, original_left, original_right):
        if abs(left.end - right.start) > 1e-7:
            return 0.0
        if original_left.pitch != original_right.pitch and left.pitch == right.pitch:
            return math.inf
        if abs(right.pitch - left.pitch) > max(
            7, abs(original_right.pitch - original_left.pitch)
        ):
            return math.inf
        t = right.start
        for lane, perfect in ((fixed, (0, 7)), (melody.notes, (0, 5))):
            before = [n.pitch for n in lane if n.start < t <= n.end]
            after = [n.pitch for n in lane if n.start <= t < n.end]
            if not before or not after:
                continue
            a, b = min(before), min(after)
            interval = (left.pitch - a) % 12
            if (
                interval in perfect
                and interval == (right.pitch - b) % 12
                and (right.pitch - left.pitch) * (b - a) > 0
            ):
                return math.inf
        return 0.08 * abs(right.pitch - left.pitch)

    layers = []
    for index in indices:
        original = notes[index]
        layer = []
        lower, upper = _pitch_bounds(original, fixed, melody)
        for pitch in range(lower, upper + 1):
            if index in protected_indices and pitch != original.pitch:
                continue
            if pitch != original.pitch and pitch % 12 not in pcs:
                continue
            note = replace(original, pitch=pitch)
            accompaniment = fixed + [note]
            if any(
                n.pitch >= pitch and n.start < note.end and n.end > note.start
                for n in fixed
            ):
                continue
            if not compatible_targets(
                list(enumerate(accompaniment)), melody, targets, note.start, note.end
            ):
                continue
            cost = (
                _local_loss(
                    accompaniment,
                    melody,
                    note.start,
                    note.end,
                    contextual_ornaments=True,
                )
                * note.duration
            )
            cost += 0.03 * abs(pitch - original.pitch)
            if math.isfinite(cost):
                layer.append((note, cost))
        if not layer:
            return None
        layers.append(layer)
    paths = [(cost, [note]) for note, cost in layers[0]]
    for k, layer in enumerate(layers[1:], 1):
        following = []
        for note, cost in layer:
            options = [
                (
                    score
                    + cost
                    + transition(
                        path[-1], note, notes[indices[k - 1]], notes[indices[k]]
                    ),
                    path,
                )
                for score, path in paths
            ]
            score, path = min(options, key=lambda x: x[0])
            if math.isfinite(score):
                following.append((score, path + [note]))
        if not following:
            return None
        paths = following
    _, best = min(paths, key=lambda x: x[0])
    result = list(notes)
    for index, note in zip(indices, best):
        result[index] = note
    if not compatible_targets(
        list(enumerate(n for n in result if n.role != "melody")),
        melody,
        targets,
        0,
        melody.length,
    ):
        return None
    return result
