"""Set-valued harmony evidence without fabricating missing pitches."""

from itertools import pairwise

from .chorale_harmony_audit import VOCABULARY


def chord_candidates(pitch_classes):
    observed = set(pitch_classes)
    if len(observed) < 2:
        return []
    exact, partial = [], []
    for root in range(12):
        for quality, intervals in VOCABULARY.items():
            pcs = {(root + p) % 12 for p in intervals}
            if observed == pcs:
                exact.append((root, quality))
            elif observed < pcs:
                partial.append((root, quality))
    return exact or partial


def arrival_evidence(notes, start, end):
    if end <= start:
        raise ValueError("Harmony evidence needs a positive interval.")
    relevant = [n for n in notes if n.start < end and n.end > start]
    times = sorted(
        {
            start,
            end,
            *(max(start, n.start) for n in relevant),
            *(min(end, n.end) for n in relevant),
        }
    )
    snapshots, basses = [], []
    for a, _ in pairwise(times):
        sounding = [n.pitch for n in relevant if n.start <= a + 1e-7 < n.end]
        snapshots.append(frozenset(p % 12 for p in sounding))
        basses.append(min(sounding) % 12 if sounding else None)
    observed = snapshots[0]
    status = "stationary"
    if len(set(snapshots)) > 1:
        initial = [n for n in relevant if n.start <= start + 1e-7 < n.end]
        if not initial or any(n.end < end - 1e-7 for n in initial):
            return {
                "status": "changing_or_unresolved",
                "candidates": [],
                "pitch_classes": sorted(set().union(*snapshots)),
                "bass_at_onset": basses[0],
            }
        observed = set().union(*snapshots)
        status = "held_completion"
    candidates = chord_candidates(observed)
    exact = [
        c
        for c in candidates
        if set(observed) == {(c[0] + p) % 12 for p in VOCABULARY[c[1]]}
    ]
    return {
        "status": status
        if exact
        else "ambiguous"
        if candidates
        else "insufficient_or_outside_vocabulary",
        "candidates": candidates,
        "pitch_classes": sorted(observed),
        "bass_at_onset": basses[0],
        "stable_bass": len(set(basses)) == 1,
        "complete_pitch_class_evidence": bool(exact),
    }
