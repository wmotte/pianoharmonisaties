"""Experimental two-pass planning over corpus-supported accompaniment options.

Pass one scores only soprano/bass timelines. Pass two selects inner voices while
keeping that bass timeline fixed. Candidate coverage still comes from gestures.
"""

import math
from collections import defaultdict
from dataclasses import replace
from itertools import pairwise

from .chorale_gestures import _active, _options, beat_class
from .chorale_model import _hand_split, _layout
from .chorale_phrase_transfer import global_path
from .chorale_phrases import options as phrase_options
from .chorale_phrases import ordered_motion, register_gap
from .engine import Harmony
from .model import Event
from .profile import identify_chord


def bass_timeline(events):
    """Lowest sounding line, preserving actual reattacks and source ties."""
    times = sorted({0, 1, *(a for _, a, _, _ in events), *(b for _, _, b, _ in events)})
    result = []
    last_identity = None
    for a, b in pairwise(times):
        active = [(i, e) for i, e in enumerate(events) if e[1] <= a + 1e-7 < e[2]]
        if not active:
            last_identity = None
            continue
        identity, (offset, start, _, held) = max(active, key=lambda item: item[1][0])
        if result and identity == last_identity:
            p, x, _, tied = result[-1]
            result[-1] = (p, x, b, tied)
        else:
            result.append((offset, a, b, held if abs(start - a) < 1e-7 else True))
        last_identity = identity
    return tuple(result)


def _moving(bass):
    return any(a > 1e-7 for _, a, _, _ in bass)


def activity_options(note, melody, model, choices):
    """Apply an optional empirical prior for internal bass attacks.

    Exact rhythmic contexts only, with add-one smoothing. This is a search
    preference, not a quality metric or a requirement to add notes.
    """
    if note.duration < 2:
        return choices
    pool = [
        g
        for g in model["gestures"]
        if g["mode"] == melody.mode
        and g["degree"] == (note.pitch - melody.tonic) % 12
        and abs(g["duration"] - note.duration) < 1e-7
        and g["beat"] == beat_class(melody, note.start)
    ]
    total = sum(g["count"] for g in pool)
    if not total:
        return choices
    moving = sum(g["count"] for g in pool if _moving(bass_timeline(g["events"])))
    return [
        (
            events,
            cost
            - math.log(
                ((moving if _moving(bass_timeline(events)) else total - moving) + 1)
                / (total + 2)
            ),
            identity,
        )
        for events, cost, identity in choices
    ]


def bass_local(n, bass, melody, model, gap):
    pool = [
        g
        for g in model["gestures"]
        if g["mode"] == melody.mode
        and g["degree"] == (n.pitch - melody.tonic) % 12
        and abs(g["duration"] - n.duration) < 1e-6
        and g["beat"] == beat_class(melody, n.start)
    ]
    # A rhythm prior is learned independently of inner-voice voicing costs.
    total = sum(g["count"] for g in pool)
    matching = sum(
        g["count"] for g in pool if _moving(bass_timeline(g["events"])) == _moving(bass)
    )
    cost = -0.35 * math.log((matching + 1) / (total + 2))
    for offset, a, b, _ in bass:
        interval = offset % 12
        cost += (b - a) * (
            0.025 * abs(offset - gap) + 0.8 * (interval in (1, 2, 6, 10, 11))
        )
    cost += 0.8 * (1 - sum(b - a for _, a, b, _ in bass))
    for (p, _, end, _), (q, start, _, _) in pairwise(bass):
        if abs(end - start) < 1e-6:
            leap = abs(p - q)
            cost += 0.04 * leap + 0.25 * max(0, leap - 7)
    return cost


def bass_connection(old, new):
    _, previous, before, _ = old
    _, following, after, _ = new
    if (
        not before
        or not after
        or abs(previous.end - following.start) > 1e-6
        or abs(before[-1][2] - 1) > 1e-6
        or abs(after[0][1]) > 1e-6
    ):
        return 0.0
    p = previous.pitch - before[-1][0]
    q = following.pitch - after[0][0]
    leap = abs(q - p)
    # No inner-voice or chord-frequency reward can compensate this gate.
    if (
        (previous.pitch - p) % 12 in (0, 7)
        and (previous.pitch - p) % 12 == (following.pitch - q) % 12
        and (q - p) * (following.pitch - previous.pitch) > 0
    ):
        return math.inf
    cost = 0.045 * leap + 0.25 * max(0, leap - 7)
    cost -= 0.08 * ((q - p) * (following.pitch - previous.pitch) < 0)
    cost += 0.25 * (_moving(before) != _moving(after))
    return cost


def inner_connection(old, new):
    _, previous, old_events, _ = old
    _, following, events, _ = new
    if abs(previous.end - following.start) > 1e-6:
        return 0.0
    before = _active(old_events, 1 - 1e-6, previous.pitch)
    after = _active(events, 0, following.pitch)
    if not before or not after:
        return 0.0
    return 0.075 * ordered_motion(before[1:], after[1:])


def plan(melody, model):
    from .chorale_cadences import planned_options, propose

    gap = register_gap(melody, model)
    goals = [propose(melody, end, model) for end in melody.fermatas]
    layers = []
    for n in melody.notes:
        options = phrase_options(n, melody, model, _options(n, melody, model), gap)
        if model.get("chromatic_context") and model.get(
            "functional_chromatic_approach"
        ):
            from .chorale_chromatic import leading_options

            approaches = leading_options(n, melody, gap)
            if approaches:
                options = approaches
        options = planned_options(n, melody, model, options, goals)
        goal = next((g for g in goals if g and abs(g["end"] - n.end) < 1e-6), None)
        groups = defaultdict(list)
        for events, local, identity in options:
            if goal:
                chord = identify_chord([n.pitch, *_active(events, 1 - 1e-6, n.pitch)])
                if not chord or ((chord[0] - melody.tonic) % 12, chord[1]) != (
                    goal["root_degree"],
                    goal["quality"],
                ):
                    continue
            groups[bass_timeline(events)].append((local, n, events, identity))
        layers.append(
            [
                (bass_local(n, bass, melody, model, gap), n, bass, choices)
                for bass, choices in groups.items()
            ]
        )
    first = global_path(layers, bass_connection)
    if first is None:
        return None
    bass_cost, route = first
    second = global_path([state[3] for state in route], inner_connection)
    if second is None:
        return None
    inner_cost, chosen = second
    return (
        [(n, events, identity) for _, n, events, identity in chosen],
        bass_cost,
        inner_cost,
        goals,
    )


def render(melody, model, path, seed, tempos):
    from .chorale_continuity import bridge, choose_context

    expanded = []
    for i, (n, events, identity) in enumerate(path):
        if i:
            previous, old_events, _ = path[i - 1]
            context = choose_context(melody, previous, n, model)
            before = _active(old_events, 1 - 1e-6, previous.pitch)
            after = _active(events, 0, n.pitch)
            if context and before and after:
                rest, _ = bridge(previous, n, before, after, context)
                if rest:
                    expanded.append(
                        (
                            Event(
                                previous.pitch,
                                previous.end,
                                n.start - previous.end,
                                72,
                                "bridge",
                            ),
                            rest,
                            -4,
                        )
                    )
        expanded.append((n, events, identity))
    lanes = defaultdict(list)
    harmony = []
    for n, events, _ in expanded:
        for offset, a, b, held in sorted(events, key=lambda e: (e[1], -e[0])):
            pitch = n.pitch - offset
            start, end = n.start + a * n.duration, n.start + b * n.duration
            ps = _active(events, a, n.pitch)
            split = _hand_split(ps, n.pitch)
            role = "bass" if pitch in ps[:split] or n.role == "bridge" else "inner"
            lane = lanes[pitch]
            connect = held or (
                a == 0 and (pitch > ps[0] or beat_class(melody, start) != "bar")
            )
            if (
                connect
                and lane
                and lane[-1].role == role
                and abs(lane[-1].end - start) < 1e-6
                and start not in melody.phrases
            ):
                lane[-1] = replace(lane[-1], duration=end - lane[-1].start)
            else:
                lane.append(Event(pitch, start, end - start, 72, role))
        for a, b in pairwise(
            sorted({0, 1, *(e[1] for e in events), *(e[2] for e in events)})
        ):
            ps = _active(events, a, n.pitch)
            chord = identify_chord([*ps, *([n.pitch] if n.role != "bridge" else [])])
            if ps and chord:
                harmony.append(
                    Harmony(
                        n.start + a * n.duration,
                        n.start + b * n.duration,
                        *chord,
                        ps[0],
                        tuple(ps[1:]),
                    )
                )
    return _layout(
        melody,
        list(melody.notes) + [n for lane in lanes.values() for n in lane],
        harmony,
        0,
        seed,
        tempos,
    )


def generate(melody, model, seed=0, tempos=None):
    from .chorale_model import generate_chorale

    melody.validate()
    result = plan(melody, model)
    if result is None:
        fallback = dict(model, decoder="phrase_continuity_v1")
        arrangement = generate_chorale(melody, fallback, seed, tempos)
        arrangement.diagnostics["two_pass_fallback"] = (
            "No feasible bass route with cadence and parallel constraints."
        )
        return arrangement
    path, bass_cost, inner_cost, goals = result
    arrangement = render(melody, model, path, seed, tempos)
    arrangement.diagnostics.update(
        decoder="two_pass_bass_v1",
        bass_plan_cost=bass_cost,
        inner_plan_cost=inner_cost,
        cadence_goals=goals,
        bass_route=[
            {"start": n.start, "events": bass_timeline(events)} for n, events, _ in path
        ],
        scope="Bass-first global planning within corpus-supported gesture options; rests use the existing bridge model.",
    )
    return arrangement
