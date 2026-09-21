"""Learn when and how accompaniment continues through an internal melody rest."""

import itertools
import math
from collections import Counter
from copy import deepcopy
from functools import lru_cache

from .model import Event


def gap_boundary(melody, start, end):
    """A boundary may mark release, the breath, or the next phrase's onset."""
    contains = lambda points: any(start - 1e-6 <= f <= end + 1e-6 for f in points)
    return contains(melody.phrases), contains(melody.fermatas)


def fit_continuity(model, references):
    from .chorale_gestures import beat_class

    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError(
            "Continuity training must match the disclosed source identities."
        )
    examples = []
    for entry, melody, arrangement in references:
        for previous, following in zip(melody.notes, melody.notes[1:]):
            start, end = previous.end, following.start
            if end - start < 1e-6:
                continue
            before = [
                n.pitch for n in arrangement.notes if n.start <= start - 1e-6 < n.end
            ]
            if not before:
                continue
            bass = min(before)
            notes = [
                (
                    n.pitch - bass,
                    max(0, n.start - start),
                    min(end, n.end) - start,
                    n.start < start - 1e-6,
                )
                for n in arrangement.notes
                if n.role != "melody" and n.start < end - 1e-6 and n.end > start + 1e-6
            ]
            examples.append(
                {
                    "source_id": entry["source_id"],
                    "group": entry["group"],
                    "mode": melody.mode,
                    "duration": end - start,
                    "previous_duration": previous.duration,
                    "melodic_step": following.pitch - previous.pitch,
                    "events": sorted(notes),
                    "start": start,
                    "rest_beat": beat_class(melody, start),
                    "phrase_end": gap_boundary(melody, start, end)[0],
                    "fermata": gap_boundary(melody, start, end)[1],
                }
            )
    result = deepcopy(model)
    result.update(
        decoder="phrase_continuity_v1",
        rest_contexts=examples,
        continuity_scope={
            "maximum_previous_duration": max(
                (e["previous_duration"] for e in examples), default=0
            ),
            "use_metric_context": True,
            "anchor_policy": "lower_boundary_bass",
            "bridge_hand": "left",
        },
    )
    return result


def choose_context(melody, previous, following, model, exclude_group=None):
    from .chorale_gestures import beat_class

    start, end = previous.end, following.start
    gap = end - start
    scope = model.get("continuity_scope", {})
    phrase_end, fermata = gap_boundary(melody, start, end)
    if gap < 1e-6 or fermata or (phrase_end and not scope.get("phrase_bridges")):
        return None
    _, numerator, denominator = next(
        m for m in reversed(melody.meters) if m[0] <= start + 1e-6
    )
    if gap >= numerator * 4 / denominator - 1e-6:
        return None
    eligible = [
        e
        for e in model.get("rest_contexts", [])
        if e["group"] != exclude_group
        and e["phrase_end"] == phrase_end
        and not e.get("fermata", e["phrase_end"])
    ]
    if phrase_end and len({e["group"] for e in eligible}) < 2:
        return None
    if (
        scope
        and previous.duration
        > max((e["previous_duration"] for e in eligible), default=0) + 1e-6
    ):
        return None
    nearest = {}
    query_context = None
    if scope.get("context_features"):
        from .chorale_rest_corpus import melodic_context

        query_context = melodic_context(melody, previous, following)
    for example in eligible:
        distance = abs(math.log2(gap / example["duration"]))
        distance += 0.45 * abs(
            math.log2(previous.duration / example["previous_duration"])
        )
        distance += 0.2 * (example["mode"] != melody.mode)
        if scope.get("use_metric_context"):
            distance += 0.6 * (example.get("rest_beat") != beat_class(melody, start))
        distance += 0.02 * min(
            12, abs(following.pitch - previous.pitch - example["melodic_step"])
        )
        if query_context and example.get("context"):
            observed = example["context"]
            distance += 0.2 * abs(
                math.log2(query_context["next_duration"] / observed["next_duration"])
            )
            if query_context["duration_ratio"] and observed["duration_ratio"]:
                distance += 0.25 * abs(
                    math.log2(
                        query_context["duration_ratio"] / observed["duration_ratio"]
                    )
                )
            size = min(
                len(query_context["preceding_steps"]), len(observed["preceding_steps"])
            )
            if size:
                distance += (
                    0.08
                    * sum(
                        min(12, abs(a - b))
                        for a, b in zip(
                            query_context["preceding_steps"][-size:],
                            observed["preceding_steps"][-size:],
                        )
                    )
                    / size
                )
        key = example["group"]
        if key not in nearest or distance < nearest[key][0]:
            nearest[key] = (distance, example)
    ranked = sorted(nearest.values(), key=lambda x: x[0])[:5]
    if phrase_end:
        ranked = [row for row in ranked if row[0] <= 1.75]
        if len(ranked) < 2:
            return None
    if not ranked or ranked[0][0] > 1.75:
        return None
    weight = sum(math.exp(-d) for d, _ in ranked)
    support = sum(math.exp(-d) for d, e in ranked if e["events"]) / weight
    if scope.get("class_balance"):
        groups = {e["group"] for e in eligible}
        prior = sum(
            sum(bool(e["events"]) for e in eligible if e["group"] == g)
            / sum(e["group"] == g for e in eligible)
            for g in groups
        ) / len(groups)
        if 0 < prior < 1:
            positive = support / prior
            negative = (1 - support) / (1 - prior)
            support = positive / (positive + negative)
    if support < 0.55:
        return None
    source = next(e for _, e in ranked if e["events"])
    return {
        "example": source,
        "support": support,
        "duration": min(gap, source["duration"]),
        "anchor_policy": scope.get("anchor_policy", "previous"),
        "preserve_distinct_classes": scope.get("preserve_distinct_classes", False),
    }


@lru_cache(maxsize=8192)
def _distinct_projection(allowed, bass, source_events):
    """Closest joint projection retaining distinct simultaneous pitch classes."""
    offsets = sorted({o for o, _, _, _ in source_events})
    simultaneous = {
        (min(o, p), max(o, p))
        for o, a, b, _ in source_events
        for p, c, d, _ in source_events
        if max(a, c) < min(b, d) - 1e-7
    }
    conflicts = {
        (min(o, p), max(o, p))
        for o, a, b, _ in source_events
        for p, c, d, _ in source_events
        if o % 12 != p % 12 and max(a, c) < min(b, d) - 1e-7
    }
    domains = [sorted(allowed, key=lambda p: (abs(p - bass - o), p)) for o in offsets]
    best_cost, best = math.inf, None

    def visit(index, chosen, cost):
        nonlocal best_cost, best
        if cost >= best_cost:
            return
        if index == len(offsets):
            best_cost, best = cost, tuple(chosen)
            return
        offset = offsets[index]
        for pitch in domains[index]:
            if any(
                ((old, offset) in conflicts and pitch % 12 == previous % 12)
                or ((old, offset) in simultaneous and abs(pitch - previous) > 12)
                for old, previous in zip(offsets[:index], chosen)
            ):
                continue
            visit(index + 1, chosen + [pitch], cost + abs(pitch - bass - offset))

    visit(0, [], 0)
    return tuple(zip(offsets, best)) if best is not None else None


def bridge(previous, following, before, after, context):
    """Project a learned rest figure onto the current harmony during beam search."""
    if context is None or not before or not after:
        return [], 0.0
    if context.get("anchor_policy") == "connected_boundary_bass":
        choices = []
        base = min(before[0], after[0])
        for anchor in (base, base - 12, base + 12):
            if not 21 <= anchor < min(previous.pitch, following.pitch):
                continue
            events, cost = bridge(
                previous,
                following,
                before,
                after,
                dict(context, anchor_policy="previous", anchor_override=anchor),
            )
            if not events:
                continue
            times = sorted({a for _, a, _, _ in events} | {b for _, _, b, _ in events})
            route = [before[0]]
            for t in times:
                active = [
                    previous.pitch - p for p, a, b, _ in events if a <= t + 1e-7 < b
                ]
                if active:
                    route.append(min(active))
            route.append(after[0])
            moves = [abs(b - a) for a, b in itertools.pairwise(route)]
            if max(moves, default=0) > 12:
                continue
            # Preserve an already feasible historical projection and its cost.
            # Penalizing all motion here rewards static accompaniment elsewhere
            # in the beam, beyond the register defect this policy addresses.
            if anchor == base:
                return events, cost
            choices.append((max(moves, default=0), sum(moves), cost, events))
        if not choices:
            return [], math.inf
        _, _, cost, events = min(choices, key=lambda item: item[:3])
        return events, cost
    start = previous.end
    ceiling = min(previous.pitch, following.pitch)
    pcs = {p % 12 for p in [*before, previous.pitch]}
    bass = (
        min(before[0], after[0])
        if context.get("anchor_policy") == "lower_boundary_bass"
        else before[0]
    )
    bass = context.get("anchor_override", bass)
    allowed = [
        p for p in range(max(21, bass - 5), min(ceiling, bass + 13)) if p % 12 in pcs
    ]
    if not allowed:
        return [], 0.0
    projection = None
    if context.get("preserve_distinct_classes"):
        source_events = tuple(
            (offset, a, min(b, context["duration"]), held)
            for offset, a, b, held in context["example"]["events"]
            if a < min(b, context["duration"]) - 1e-6
        )
        projected = _distinct_projection(tuple(allowed), bass, source_events)
        if projected is None:
            return [], math.inf
        projection = dict(projected)
    events = []
    held_origins = set()
    for offset, a, b, held in context["example"]["events"]:
        b = min(b, context["duration"])
        if a >= b - 1e-6:
            continue
        pitch = (
            projection[offset]
            if projection is not None
            else min(
                allowed, key=lambda p: (abs(p - (bass + offset)), abs(p - after[0]))
            )
        )
        events.append(Event(pitch, start + a, b - a, 72, "bass"))
        if held and a == 0:
            held_origins.add(pitch)
    # Projection can collapse distinct source pitches onto one pitch. Unite
    # overlapping intervals rather than emitting ambiguous MIDI unisons.
    merged = []
    for pitch in sorted({e.pitch for e in events}):
        lane = []
        for event in sorted(
            (e for e in events if e.pitch == pitch), key=lambda e: e.start
        ):
            if lane and event.start < lane[-1].end - 1e-6:
                old = lane.pop()
                event = Event(
                    pitch, old.start, max(old.end, event.end) - old.start, 72, "bass"
                )
            lane.append(event)
        merged.extend(lane)
    if not merged:
        return [], 0.0
    # Reject a projected figure that would need an oversized left-hand chord.
    for t in {e.start for e in merged}:
        active = [e.pitch for e in merged if e.start <= t + 1e-7 < e.end]
        if max(active) - min(active) > 12:
            return [], 0.0
    cost = 0.025 * abs(min(merged, key=lambda e: -e.end).pitch - after[0])
    duration = following.start - start
    normalized = [
        (
            previous.pitch - e.pitch,
            (e.start - start) / duration,
            (e.end - start) / duration,
            e.start == start and e.pitch in before and e.pitch in held_origins,
        )
        for e in merged
    ]
    return normalized, cost


def compare_rest_support(reference, generated, melody):
    times = sorted(
        {t for a in (reference, generated) for n in a.notes for t in (n.start, n.end)}
    )
    result = {
        "reference_quarters": 0.0,
        "generated_quarters": 0.0,
        "matched_quarters": 0.0,
        "missing_quarters": 0.0,
        "extra_quarters": 0.0,
    }
    for start, end in itertools.pairwise(times):
        if any(n.start <= start + 1e-7 < n.end for n in melody.notes):
            continue
        original = any(
            n.role != "melody" and n.start <= start + 1e-7 < n.end
            for n in reference.notes
        )
        new = any(
            n.role != "melody" and n.start <= start + 1e-7 < n.end
            for n in generated.notes
        )
        duration = end - start
        result["reference_quarters"] += duration * original
        result["generated_quarters"] += duration * new
        result["matched_quarters"] += duration * (original and new)
        result["missing_quarters"] += duration * (original and not new)
        result["extra_quarters"] += duration * (new and not original)
    return result


def cross_validate_continuity(model, references):
    rows = []
    for entry, melody, arrangement in references:
        for previous, following in zip(melody.notes, melody.notes[1:]):
            if following.start - previous.end < 1e-6:
                continue
            actual = any(
                n.role != "melody"
                and n.start < following.start - 1e-6
                and n.end > previous.end + 1e-6
                for n in arrangement.notes
            )
            context = choose_context(
                melody, previous, following, model, exclude_group=entry["group"]
            )
            rows.append(
                {
                    "group": entry["group"],
                    "start": previous.end,
                    "actual_support": actual,
                    "predicted_support": context is not None,
                    "donor": context["example"]["group"] if context else None,
                }
            )
    outcomes = {
        "true_support": (True, True),
        "correct_silence": (False, False),
        "missed_support": (True, False),
        "false_fill": (False, True),
    }
    return {
        "method": "leave_one_source_group_out",
        "cases": rows,
        "counts": {
            k: sum((r["actual_support"], r["predicted_support"]) == v for r in rows)
            for k, v in outcomes.items()
        },
    }
