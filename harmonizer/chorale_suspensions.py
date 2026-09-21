"""Conditional preparation/resolution evidence across adjacent phrase windows."""

from .chorale_arpeggio_evidence import arpeggio_evidence
from .chorale_harmony_audit import VOCABULARY
from .chorale_harmony_evidence import chord_candidates


def accompaniment_core(notes, start, end):
    evidence = arpeggio_evidence(notes, start, end)
    ornaments = {item["index"] for item in evidence["ornaments"]}
    pcs = {
        n.pitch % 12
        for i, n in enumerate(notes)
        if i not in ornaments and n.role != "melody" and n.start < end and n.end > start
    }
    exact = [
        (root, quality)
        for root, quality in chord_candidates(pcs)
        if pcs == {(root + p) % 12 for p in VOCABULARY[quality]}
    ]
    # The first version only handles triad cores. A union of two successive
    # triads must not become an invented seventh-chord preparation.
    return (
        exact[0]
        if len(exact) == 1 and exact[0][1] in ("major", "minor", "dim")
        else None
    )


def prepared_suspensions(melody, notes, previous_start, boundary, end):
    """Require explicit harmonic cores on both sides and a held downward step.

    Cores may rely on traced arpeggio ornaments, so the result is conditional
    evidence for a soft cost adjustment. It never overrides a feasibility gate.
    """
    previous = accompaniment_core(notes, previous_start, boundary)
    current = accompaniment_core(notes, boundary, end)
    if previous is None or current is None:
        return []
    old_pcs = {(previous[0] + p) % 12 for p in VOCABULARY[previous[1]]}
    new_pcs = {(current[0] + p) % 12 for p in VOCABULARY[current[1]]}
    result = []
    for index, (held, after) in enumerate(zip(melody.notes, melody.notes[1:])):
        if not previous_start <= held.start <= boundary - 0.5:
            continue
        if not boundary < held.end <= min(end, boundary + 2) + 1e-7:
            continue
        if abs(after.start - held.end) > 1e-7 or after.start >= end:
            continue
        if held.pitch - after.pitch not in (1, 2):
            continue
        if any(
            held.start < t <= after.start for t in [*melody.phrases, *melody.fermatas]
        ):
            continue
        if held.pitch % 12 not in old_pcs or held.pitch % 12 in new_pcs:
            continue
        sounding_during_preparation = {held.pitch % 12} | {
            n.pitch % 12
            for n in notes
            if n.role != "melody" and n.start < boundary and n.end > held.start
        }
        if not old_pcs <= sounding_during_preparation:
            continue
        if after.pitch % 12 not in new_pcs:
            continue
        result.append(
            {
                "melody_index": index,
                "resolution_index": index + 1,
                "preparation_core": previous,
                "resolution_core": current,
            }
        )
    return result
