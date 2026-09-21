"""Explicit harmonic targets for already fixed melody windows."""

from dataclasses import replace
from itertools import pairwise

from .model import Event


def revoice_targets(
    events,
    melody,
    targets,
    start,
    end,
    *,
    immutable_ids=(),
    allow_completion=False,
    partial_validator=None,
):
    """Redistribute existing notes over explicit chords, without adding attacks.

    Notes already sounding before a target begins are retained. Newly starting
    notes keep their full original duration, including a tail beyond the target.
    A partial validator sees assigned notes and notes that cannot be changed by
    later targets. It must tolerate missing identities. It is also applied to
    each final path, including when there are no overlapping targets.
    """
    from .chorale_phrase_transfer import _local_loss

    beam = [(0, list(events))]
    for target_index, target in enumerate(targets):
        left, right = max(start, target["start"]), min(end, target["end"])
        if left >= right:
            continue
        identities = [
            i for i, n in events if left <= n.start < right and i not in immutable_ids
        ]
        future_ids = {
            i
            for i, n in events
            if i not in immutable_ids
            and any(
                max(start, t["start"]) <= n.start < min(end, t["end"])
                for t in targets[target_index + 1 :]
            )
        }
        for step, identity in enumerate(identities):
            pending = set(identities[step + 1 :])
            proposals = []
            for cost, path in beam:
                position = next(j for j, (i, _) in enumerate(path) if i == identity)
                note = path[position][1]
                for pitch in range(
                    max(21, note.pitch - 12), min(108, note.pitch + 12) + 1
                ):
                    if pitch % 12 not in target["pitch_classes"]:
                        continue
                    variant = list(path)
                    variant[position] = (identity, replace(note, pitch=pitch))
                    # Unassigned pitches are placeholders, not constraints on
                    # this partial voicing. A simultaneous bass/tenor shift can
                    # otherwise be rejected because the other note has not moved.
                    fixed = [
                        (i, n) for i, n in variant if i not in pending | future_ids
                    ]
                    if _local_loss([n for _, n in fixed], melody, start, end) < float(
                        "inf"
                    ) and (partial_validator is None or partial_validator(fixed)):
                        proposals.append((cost + abs(pitch - note.pitch), variant))
            beam = sorted(proposals, key=lambda x: x[0])[:24]
        beam = [
            (cost, path)
            for cost, path in beam
            if compatible_targets(
                path,
                melody,
                [target],
                start,
                end,
                require_complete=not allow_completion,
            )
            and (
                partial_validator is None
                or partial_validator([(i, n) for i, n in path if i not in future_ids])
            )
        ]
    return [
        path for _, path in beam if partial_validator is None or partial_validator(path)
    ]


def arrival_hypotheses(note, melody, model):
    """Offer observed modal chord types containing the arrival melody tone.

    These are alternatives, not an inference that the arrival must be tonic.
    Counts describe corpus support, not a calibrated conditional probability.
    """
    from .chorale_phrases import CHORDS

    result = []
    for label, count in model.get("phrase_chords", {}).get(melody.mode, {}).items():
        degree, quality = label.split(":")
        if quality not in CHORDS or count <= 0:
            continue
        root = (melody.tonic + int(degree)) % 12
        pcs = [(root + p) % 12 for p in CHORDS[quality]]
        if note.pitch % 12 not in pcs:
            continue
        result.append(
            {
                "start": note.start,
                "end": note.end,
                "root": root,
                "quality": quality,
                "pitch_classes": pcs,
                "required": [root, pcs[1]],
                "corpus_count": count,
            }
        )
    return sorted(result, key=lambda x: (-x["corpus_count"], x["root"], x["quality"]))


def complete_targets(events, melody, targets, start, end):
    """Add missing required chord tones, preserving every existing donor note."""
    from .chorale_phrase_transfer import _local_loss

    beam = [(0, list(events))]
    for k, target in enumerate(targets):
        left, right = max(start, target["start"]), min(end, target["end"])
        if left >= right:
            continue
        original = [n for _, n in events] + list(melody.notes)
        times = sorted(
            {
                left,
                right,
                *(n.start for n in original if left < n.start < right),
                *(n.end for n in original if left < n.end < right),
            }
        )
        for a, b in pairwise(times):
            next_beam = []
            for cost, path in beam:
                active = [
                    n
                    for n in [*(n for _, n in path), *melody.notes]
                    if n.start <= a + 1e-7 < n.end
                ]
                pcs = {n.pitch % 12 for n in active}
                if not pcs <= set(target["pitch_classes"]):
                    continue
                top = next(
                    (n.pitch for n in melody.notes if n.start <= a + 1e-7 < n.end), None
                )
                missing = sorted(set(target["required"]) - pcs)
                candidates = [(cost, path)]
                for pc in missing:
                    extended = []
                    if top is None:
                        candidates = []
                        break
                    for oldcost, oldpath in candidates:
                        for pitch in range(max(21, top - 24), top):
                            if pitch % 12 != pc:
                                continue
                            proposal = [
                                *oldpath,
                                (-1 - 12 * k - pc, Event(pitch, a, b - a, 72, "inner")),
                            ]
                            if _local_loss(
                                [n for _, n in proposal], melody, start, end
                            ) < float("inf"):
                                extended.append(
                                    (oldcost + abs(top - pitch - 7), proposal)
                                )
                    candidates = sorted(extended, key=lambda x: x[0])[:12]
                next_beam.extend(candidates)
            beam = sorted(next_beam, key=lambda x: x[0])[:12]
    return [path for _, path in beam]


def compatible_targets(events, melody, targets, start, end, *, require_complete=True):
    for target in targets:
        left, right = max(start, target["start"]), min(end, target["end"])
        if left >= right:
            continue
        notes = [n for _, n in events] + list(melody.notes)
        times = sorted(
            {
                left,
                right,
                *(n.start for n in notes if left < n.start < right),
                *(n.end for n in notes if left < n.end < right),
            }
        )
        for a, b in pairwise(times):
            sounding = [n.pitch for n in notes if n.start <= a + 1e-7 < n.end]
            pcs = {p % 12 for p in sounding}
            for field, active in (
                ("arrival_bass", abs(a - target["start"]) < 1e-7),
                ("terminal_bass", abs(b - target["end"]) < 1e-7),
            ):
                if (
                    active
                    and field in target
                    and (not sounding or min(sounding) % 12 != target[field])
                ):
                    return False
            if not pcs <= set(target["pitch_classes"]) or (
                require_complete and not set(target["required"]) <= pcs
            ):
                return False
    return True
