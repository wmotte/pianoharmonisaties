"""Project individual transcription notes through an explicit time alignment."""

import math
from bisect import bisect_right
from dataclasses import replace
from itertools import pairwise


def project_notes(notes, anchors, *, grid=None):
    """Map each attack and release independently, without chord-duration pooling.

    Anchors are (source seconds, score quarters). They must cover every note.
    Cropping, tempo estimation and voice assignment belong to the caller.
    Optional grid snapping rejects vanished notes instead of inventing duration.
    """
    anchors = list(anchors)
    if len(anchors) < 2 or any(
        not all(math.isfinite(v) for v in pair) for pair in anchors
    ):
        raise ValueError("At least two finite timing anchors are required.")
    if any(b[0] <= a[0] or b[1] <= a[1] for a, b in pairwise(anchors)):
        raise ValueError("Timing anchors must increase in both coordinates.")
    if grid is not None and (not math.isfinite(grid) or grid <= 0):
        raise ValueError("The score grid must be positive and finite.")
    times = [a[0] for a in anchors]

    def mapped(t):
        if not math.isfinite(t) or t < times[0] or t > times[-1]:
            raise ValueError("A note endpoint is outside the timing anchors.")
        i = min(bisect_right(times, t) - 1, len(anchors) - 2)
        (a, x), (b, y) = anchors[i : i + 2]
        result = x + (t - a) / (b - a) * (y - x)
        return round(result / grid) * grid if grid is not None else result

    result = []
    for n in notes:
        if not math.isfinite(n.duration) or n.duration <= 0:
            raise ValueError("Source notes must have positive finite duration.")
        start, end = mapped(n.start), mapped(n.end)
        if end <= start:
            raise ValueError("Grid snapping would remove a source note.")
        result.append(replace(n, start=start, duration=end - start))
    return result
