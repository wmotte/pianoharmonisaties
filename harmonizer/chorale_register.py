"""Duration-weighted melody-to-accompaniment register comparisons."""

from collections import defaultdict
from itertools import pairwise


def exposure_penalty(note, events, settings):
    """Charge register-tail exposure in actual quarter-note time.

    Bounds are corpus quantiles of melody-to-bass distance. This is a soft
    search preference, not a pitch restriction or a musical quality score.
    """
    if settings is None:
        return 0.0
    import math

    lower, upper = settings["gap_quantiles"]
    weight = settings["weight"]
    if not all(math.isfinite(x) for x in (lower, upper, weight)) or not (
        0 <= lower <= upper and weight >= 0
    ):
        raise ValueError("Invalid register exposure bounds or weight")
    times = sorted({0, 1, *(a for _, a, _, _ in events), *(b for _, _, b, _ in events)})
    cost = 0.0
    for start, end in pairwise(times):
        offsets = [o for o, a, b, _ in events if a <= start < b]
        if offsets:
            gap = max(offsets)
            excess = max(0, lower - gap, gap - upper)
            cost += (end - start) * note.duration * excess * weight
    return cost


def gap_distribution(accompaniment, melody, start, end):
    notes = [n for n in [*accompaniment, *melody] if n.start < end and n.end > start]
    times = sorted(
        {
            start,
            end,
            *(max(start, n.start) for n in notes),
            *(min(end, n.end) for n in notes),
        }
    )
    weights = defaultdict(float)
    for a, b in pairwise(times):
        top = next((n.pitch for n in melody if n.start <= a + 1e-7 < n.end), None)
        bass = min(
            (n.pitch for n in accompaniment if n.start <= a + 1e-7 < n.end),
            default=None,
        )
        if top is not None and bass is not None:
            weights[top - bass] += b - a
    total = sum(weights.values())
    return {gap: weight / total for gap, weight in weights.items()} if total else {}


def register_distance(source, target):
    """Exact one-dimensional Wasserstein distance, expressed in octaves.

    Empty profiles contain no register evidence and contribute no preference.
    This describes relative register, not a musical quality grade.
    """
    points = sorted(source.keys() | target.keys())
    if not source or not target:
        return 0.0
    difference = distance = 0.0
    for a, b in pairwise(points):
        difference += source.get(a, 0) - target.get(a, 0)
        distance += abs(difference) * (b - a)
    return distance / 12
