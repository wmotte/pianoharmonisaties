"""Corpus-constrained octave choices with fixed harmony, rhythm and melody."""

import math
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from itertools import pairwise, product
from statistics import median

from .chorale_hand_plan import assign_hands
from .chorale_model import _hand_split, _layout
from .chorale_register import gap_distribution, register_distance
from .chorale_review import musical_checks
from .model import MODES


def signature(notes):
    return Counter((n.pitch % 12, n.start, n.end, n.role) for n in notes)


def timeline(notes):
    times = sorted({t for n in notes for t in (n.start, n.end)})
    result = []
    for a, b in pairwise(times):
        active = [n for n in notes if n.start <= a < n.end]
        acc = [n.pitch for n in active if n.role != "melody"]
        tops = [n.pitch for n in active if n.role == "melody"]
        result.append((a, b, min(acc) if acc else None, sorted(acc), tops))
    return result


def motion(notes):
    previous = None
    movements = []
    for a, b, bass, acc, tops in timeline(notes):
        if bass is not None and previous is not None and bass != previous:
            movements.append(abs(bass - previous))
        previous = bass
    return sum(max(0, x - 7) ** 2 for x in movements), sum(movements)


def refine_octaves(old, melody, profiles, training_ids, *, exclude_group=None):
    """Return a copy and disclose every accepted octave change and source pool."""
    seen = set()
    for profile in profiles:
        identity = profile["source_id"]
        if identity not in training_ids or identity in seen:
            raise ValueError(
                "Register profiles must have distinct disclosed training identities"
            )
        seen.add(identity)
        if profile["mode"] not in MODES or not math.isfinite(
            profile["melody_register"]
        ):
            raise ValueError("Invalid register profile context")
        weights = profile["gap_distribution"]
        if (
            not weights
            or any(
                not str(k).lstrip("-").isdigit()
                or int(k) < 0
                or not math.isfinite(v)
                or v < 0
                for k, v in weights.items()
            )
            or abs(sum(weights.values()) - 1) > 1e-6
        ):
            raise ValueError(
                "Register density must be a normalized nonnegative distribution"
            )
    notes = list(old.notes)
    decisions = []
    original_checks = musical_checks(old, melody)
    pool = sorted(
        [
            p
            for p in profiles
            if p["mode"] == melody.mode and p["group"] != exclude_group
        ],
        key=lambda p: abs(p["melody_register"] - median(n.pitch for n in melody.notes)),
    )[:3]
    density = {}
    for p in pool:
        for gap, weight in p["gap_distribution"].items():
            density[int(gap)] = density.get(int(gap), 0) + weight / len(pool)

    def distances(candidate, start, end):
        acc = [n for n in candidate if n.role != "melody"]
        observed = [
            gap_distribution(acc, melody.notes, a, b)
            for a, b in [(0, melody.length), (start, end)]
        ]
        if not density or any(not distribution for distribution in observed):
            return None
        return [register_distance(density, distribution) for distribution in observed]

    for boundary in melody.phrases[:-1]:
        if not any(abs(n.end - boundary) < 1e-6 for n in melody.notes) or not any(
            abs(n.start - boundary) < 1e-6 for n in melody.notes
        ):
            continue
        before = [
            n.pitch
            for n in notes
            if n.role != "melody" and n.start <= boundary - 1e-6 < n.end
        ]
        after = [
            n.pitch
            for n in notes
            if n.role != "melody" and n.start <= boundary + 1e-6 < n.end
        ]
        if not before or not after or abs(min(after) - min(before)) <= 7:
            continue
        candidates = [
            i
            for i, n in enumerate(notes)
            if n.role == "bass"
            and n.start >= boundary
            and all(
                n.pitch < x.pitch
                for j, x in enumerate(notes)
                if j != i and x.role != "melody" and x.start < n.end and x.end > n.start
            )
        ]
        indices = sorted(candidates, key=lambda i: notes[i].start)[:3]
        if not indices or abs(notes[indices[0]].start - boundary) > 1e-6:
            continue
        baseline_timeline = timeline(notes)
        best = (motion(notes), 0, notes, None)
        for shifts in product((-12, 0, 12), repeat=len(indices)):
            trial = list(notes)
            for i, shift in zip(indices, shifts):
                trial[i] = replace(trial[i], pitch=trial[i].pitch + shift)
            if any(not 21 <= n.pitch <= 108 for n in trial):
                continue
            tt = timeline(trial)
            if any(
                (bass is None) != (oldbass is None)
                or (bass is not None and bass % 12 != oldbass % 12)
                or (
                    tops
                    and (
                        not acc
                        or max(acc) >= tops[0]
                        or _hand_split(acc, tops[0]) is None
                    )
                )
                for (_, _, bass, acc, tops), (_, _, oldbass, _, _) in zip(
                    tt, baseline_timeline
                )
            ):
                continue
            changed = [i for i in indices if notes[i].pitch != trial[i].pitch]
            if not changed or not pool:
                continue
            lo = min(notes[i].start for i in changed)
            hi = max(notes[i].end for i in changed)
            old_dist = distances(notes, lo, hi)
            new_dist = distances(trial, lo, hi)
            if old_dist is None or new_dist is None:
                continue
            if any(b > a + 1e-12 for a, b in zip(old_dist, new_dist)):
                continue
            cost = motion(trial)
            changes = sum(s != 0 for s in shifts)
            if (cost, changes) >= (best[0], best[1]):
                continue
            candidate = _layout(melody, trial, [], 0, 0, old.tempos)
            checks = musical_checks(candidate, melody)
            if any(
                checks[k] > original_checks[k] + 1e-7
                for k in [
                    "crossing_time_fraction",
                    "bass_leaps_over_octave",
                    "outer_parallel_perfects",
                    "unaccompanied_melody_time_fraction",
                ]
            ):
                continue
            hands = assign_hands(trial)
            if hands is None:
                continue
            best = (cost, changes, trial, shifts)
        if best[3] is not None:
            decisions.append(
                {
                    "boundary": boundary,
                    "before_motion": motion(notes),
                    "after_motion": best[0],
                    "changes": [
                        {
                            "index": i,
                            "from": notes[i].pitch,
                            "to": best[2][i].pitch,
                            "start": notes[i].start,
                            "end": notes[i].end,
                        }
                        for i in indices
                        if notes[i].pitch != best[2][i].pitch
                    ],
                }
            )
            notes = best[2]
    assert signature(notes) == signature(old.notes)
    assert [n for n in notes if n.role == "melody"] == [
        n for n in old.notes if n.role == "melody"
    ]

    diagnostics = deepcopy(old.diagnostics)
    diagnostics["octave_register"] = {
        "source_ids": [p["source_id"] for p in pool],
        "source_groups": [p["group"] for p in pool],
        "decisions": decisions,
        "changed": notes != old.notes,
        "scope": "Octaves only; unchanged pitch classes, bass pitch class, melody and event timing",
    }
    if not decisions:
        return replace(old, diagnostics=diagnostics)
    notes = sorted(notes, key=lambda n: (n.start, n.pitch))
    diagnostics["hands"] = assign_hands(notes)
    diagnostics["search_score_scope"] = (
        "Before octave refinement; not a musical quality score"
    )
    return replace(old, notes=notes, harmony=[], diagnostics=diagnostics)
