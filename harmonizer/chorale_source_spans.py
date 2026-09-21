"""Recover continuous source spans from mutually consistent overlapping crops."""

from collections import defaultdict
from copy import deepcopy
from statistics import median


def meter_timeline(meters, length):
    """Canonical active meter changes; redundant repeated signatures add no reset."""
    import math

    if not meters or meters[0][0] != 0 or not math.isfinite(length) or length <= 0:
        raise ValueError("A meter timeline must start at zero and have positive length")
    result = []
    previous = -1
    for start, numerator, denominator in meters:
        if (
            not all(math.isfinite(x) for x in (start, numerator, denominator))
            or start <= previous
            or numerator <= 0
            or denominator <= 0
            or numerator != int(numerator)
            or denominator != int(denominator)
        ):
            raise ValueError("Invalid or unordered meter change")
        previous = start
        if start < length and (
            not result or (numerator, denominator) != result[-1][1:]
        ):
            result.append((start, numerator, denominator))
    return result


def metered_spans(length, meters, phase=0):
    """Measure intervals without stretching, allowing changes at bar boundaries."""
    timeline = meter_timeline(meters, length)
    result = []
    for i, (start, numerator, denominator) in enumerate(timeline):
        end = timeline[i + 1][0] if i + 1 < len(timeline) else length
        bar = numerator * 4 / denominator
        initial_phase = phase if i == 0 else 0
        spans = list(measure_spans(end - start, bar, initial_phase))
        if i + 1 < len(timeline):
            elapsed = end - start + initial_phase
            if abs(elapsed / bar - round(elapsed / bar)) > 1e-7:
                raise ValueError("Meter change cuts an unfinished measure")
        result.extend((start + a, start + b) for a, b in spans)
    return result


def measure_spans(length, bar, phase=0):
    import math

    if (
        not all(math.isfinite(x) for x in (length, bar, phase))
        or length <= 0
        or bar <= 0
        or not 0 <= phase < bar
    ):
        raise ValueError("Invalid length, bar duration or metric phase")
    start = 0.0
    while start < length - 1e-7:
        end = min(length, start + (bar - phase if start == 0 else bar))
        yield start, end
        start = end


def _clip(events, start, end):
    return sorted(
        (p, max(a, start) - start, min(b, end) - start, role)
        for p, a, b, role in events
        if a < end and b > start
    )


def _union(events):
    lanes = defaultdict(list)
    for p, a, b, role in events:
        lanes[p, role].append((a, b))
    result = []
    for (pitch, role), intervals in lanes.items():
        merged = []
        for a, b in sorted(intervals):
            # Touching equal pitches can be genuine repeated attacks.
            if merged and a < merged[-1][1] - 1e-7:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        result.extend((pitch, a, b, role) for a, b in merged)
    return sorted(set(result))


def continuous_sources(donors):
    """Reconstruct only overlapping, same-version, same-meter source regions.

    The source clock has bar origin zero. Every original crop must be exactly
    recoverable from the union. Gaps and merely touching crops are not joined.
    """
    groups = defaultdict(list)
    for donor in donors:
        if len(donor["meters"]) != 1 or donor["meters"][0][0] != 0:
            raise ValueError("Reconstruction requires one score-local meter")
        bar = donor["meters"][0][1] * 4 / donor["meters"][0][2]
        if (
            abs(
                donor.get("metric_phase", donor["source_start"] % bar)
                - donor["source_start"] % bar
            )
            > 1e-7
        ):
            raise ValueError("Source phase conflicts with the common bar origin")
        groups[donor["source_id"]].append(donor)
    output = []
    for source_crops in groups.values():
        first = source_crops[0]
        for donor in source_crops:
            if any(
                donor[k] != first[k]
                for k in ("source_sha256", "tonic", "mode", "meters", "group")
            ):
                raise ValueError("Conflicting source versions or musical metadata")
        regions = []
        for donor in sorted(source_crops, key=lambda d: d["source_start"]):
            a, b = donor["source_start"], donor["source_start"] + donor["length"]
            if regions and a < regions[-1][1] - 1e-7:
                regions[-1][1] = max(regions[-1][1], b)
                regions[-1][2].append(donor)
            else:
                regions.append([a, b, [donor]])
        for start, end, crops in regions:
            events = []
            for donor in crops:
                offset = donor["source_start"]
                events += [
                    (p, a + offset, b + offset, role)
                    for p, a, b, role in donor["notes"]
                ]
                events += [
                    (p, a + offset, b + offset, "melody") for p, a, b in donor["melody"]
                ]
            union = _union(events)
            for donor in crops:
                expected = sorted(
                    [tuple(n) for n in donor["notes"]]
                    + [(p, a, b, "melody") for p, a, b in donor["melody"]]
                )
                if (
                    _clip(
                        union,
                        donor["source_start"],
                        donor["source_start"] + donor["length"],
                    )
                    != expected
                ):
                    raise ValueError(f"Source crops disagree: {donor['source_id']}")
            result = deepcopy(first)
            clipped = _clip(union, start, end)
            result.update(
                source_start=start,
                length=end - start,
                notes=sorted(
                    [n for n in clipped if n[3] != "melody"],
                    key=lambda n: (n[1], n[0], n[2]),
                ),
                melody=sorted(
                    [n[:3] for n in clipped if n[3] == "melody"], key=lambda n: n[1]
                ),
                reconstructed_crops=len(crops),
            )
            bar = first["meters"][0][1] * 4 / first["meters"][0][2]
            result["metric_phase"] = start % bar
            result["melody_register"] = median(n[0] for n in result["melody"])
            output.append(result)
    return output


def slice_source(source, start, end, *, clean_edges=True):
    """Take an unstretched span, optionally refusing cut accompaniment notes."""
    if not 0 <= start < end <= source["length"]:
        raise ValueError("Slice lies outside the verified source region")
    if clean_edges and any(
        a < t < b for _, a, b, _ in source["notes"] for t in (start, end)
    ):
        raise ValueError("Slice would cut an accompaniment note")
    result = deepcopy(source)
    melody = _clip([(p, a, b, "melody") for p, a, b in source["melody"]], start, end)
    if not melody:
        raise ValueError("Slice has no source melody")
    timeline = meter_timeline(source["meters"], source["length"])
    metered_spans(source["length"], timeline, source.get("metric_phase", 0))
    origin, numerator, denominator = next(
        m for m in reversed(timeline) if m[0] <= start
    )
    bar = numerator * 4 / denominator
    initial_phase = source.get("metric_phase", 0) if origin == 0 else 0
    result.update(
        source_start=source["source_start"] + start,
        length=end - start,
        notes=sorted(
            _clip(source["notes"], start, end), key=lambda n: (n[1], n[0], n[2])
        ),
        melody=sorted([n[:3] for n in melody], key=lambda n: n[1]),
        melody_register=median(n[0] for n in melody),
        meters=[(0, numerator, denominator)]
        + [(t - start, n, d) for t, n, d in timeline if start < t < end],
        metric_phase=(initial_phase + start - origin) % bar,
    )
    return result
