"""Checks on actual bass motion and coverage across gesture boundaries."""

from functools import lru_cache
from itertools import pairwise


def timeline_issues(accompaniment, melody, start, end):
    notes = [n for n in accompaniment if n.start < end and n.end > start]
    tops = [n for n in melody if n.start < end and n.end > start]
    times = sorted(
        {
            start,
            end,
            *(max(start, n.start) for n in notes + tops),
            *(min(end, n.end) for n in notes + tops),
        }
    )
    issues = set()
    previous_bass = None
    previous_outer = None
    for left, right in pairwise(times):
        pitches = [n.pitch for n in notes if n.start <= left + 1e-7 < n.end]
        top = next((n.pitch for n in tops if n.start <= left + 1e-7 < n.end), None)
        bass = min(pitches) if pitches else None
        if top is not None and bass is None:
            issues.add("unaccompanied_melody")
        if top is not None and pitches and max(pitches) >= top:
            issues.add("crossing")
        if bass is not None:
            if previous_bass is not None and abs(bass - previous_bass) > 12:
                issues.add("bass_leap")
            previous_bass = bass
        if top is not None and bass is not None:
            if previous_outer is not None:
                old_top, old_bass = previous_outer
                interval = (old_top - old_bass) % 12
                if (
                    interval in (0, 7)
                    and (top - bass) % 12 == interval
                    and (top - old_top) * (bass - old_bass) > 0
                ):
                    issues.add("outer_parallel")
            previous_outer = top, bass
        else:
            previous_outer = None
    return issues


@lru_cache(maxsize=16384)
def bass_route(top, events, require_coverage=True):
    times = sorted({0, 1, *(a for _, a, _, _ in events), *(b for _, _, b, _ in events)})
    route = []
    for start, end in pairwise(times):
        pitches = [top - o for o, a, b, _ in events if a <= start + 1e-7 < b]
        if not pitches:
            if require_coverage and end - start > 1e-7:
                return None
            continue
        if min(pitches) < 21 or max(pitches) >= top:
            return None
        bass = min(pitches)
        if not route or bass != route[-1]:
            route.append(bass)
    if any(abs(b - a) > 12 for a, b in pairwise(route)):
        return None
    return tuple(route)


def valid_extension(before, previous, current, events, rest_path):
    current_route = bass_route(current.pitch, tuple(map(tuple, events)))
    if not current_route:
        return False
    route = [before[0]] if before else []
    for anchor, rest_events, _ in rest_path:
        bridge_route = bass_route(anchor.pitch, tuple(map(tuple, rest_events)), False)
        if bridge_route is None:
            return False
        route.extend(bridge_route)
    route.extend(current_route)
    if any(abs(b - a) > 12 for a, b in pairwise(route)):
        return False
    if previous and before and abs(previous.end - current.start) < 1e-7:
        interval = (previous.pitch - before[0]) % 12
        if (
            interval in (0, 7)
            and (current.pitch - current_route[0]) % 12 == interval
            and (current.pitch - previous.pitch) * (current_route[0] - before[0]) > 0
        ):
            return False
    return True
