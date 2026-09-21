"""Corpus accompaniment gestures with their rhythm and held-note boundaries.

Local gestures are not a phrase composition model. Provenance and the original
decoder remain available so improvements can be assessed on actual scores.
"""

import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from itertools import pairwise

from .chorale_model import _hand_split, _layout
from .engine import Harmony
from .model import MODES, Event
from .profile import identify_chord


def beat_class(melody, start):
    offset, numerator, denominator = next(
        m for m in reversed(melody.meters) if m[0] <= start + 1e-7
    )
    unit = 4 / denominator
    position = (start - offset) / unit
    if abs(position % numerator) < 1e-6:
        return "bar"
    if abs(position - round(position)) < 1e-6:
        return "beat"
    return "offbeat"


def upgrade_model(model, references):
    """Fit only from the exact training identities already disclosed to this model."""
    if {e["source_id"] for e, _, _ in references} != set(model["training_ids"]):
        raise ValueError("Gesture training must match the model's training identities.")
    counts = Counter()
    transitions = Counter()
    transition_steps = Counter()
    for _, melody, arrangement in references:
        previous_key, previous_end = None, None
        previous_pitch = None
        for n in melody.notes:
            events = []
            for x in arrangement.notes:
                if (
                    x.role == "melody"
                    or x.start >= n.end - 1e-7
                    or x.end <= n.start + 1e-7
                ):
                    continue
                a = max(0, (x.start - n.start) / n.duration)
                b = min(1, (x.end - n.start) / n.duration)
                # Keep ordinary subdivisions. Do not invent 5:4 or 7:4 tuplets
                # through arbitrary time stretching of transcription artefacts.
                if any(
                    Fraction(t).limit_denominator(96).denominator
                    not in (1, 2, 3, 4, 6, 8, 12)
                    for t in (a, b)
                ):
                    events = []
                    break
                events.append(
                    (
                        n.pitch - x.pitch,
                        round(a, 8),
                        round(b, 8),
                        x.start < n.start - 1e-7,
                    )
                )
            if not events:
                previous_key = None
                continue
            events = tuple(sorted(events))
            if not _playable(events, n.pitch):
                previous_key = None
                continue
            key = (
                melody.mode,
                (n.pitch - melody.tonic) % 12,
                n.duration,
                beat_class(melody, n.start),
                any(abs(n.end - f) < 1e-6 for f in melody.fermatas),
                events,
            )
            counts[key] += 1
            if (
                previous_key is not None
                and abs(previous_end - n.start) < 1e-6
                and n.start not in melody.phrases
            ):
                transitions[(previous_key, key)] += 1
                transition_steps[(previous_key, key, n.pitch - previous_pitch)] += 1
            previous_key, previous_end = key, n.end
            previous_pitch = n.pitch
    result = deepcopy(model)
    result["decoder"] = "corpus_gestures_v2"
    result["status"] = "experimental_musically_reviewed"
    result["gestures"] = [
        {
            "mode": m,
            "degree": d,
            "duration": duration,
            "beat": beat,
            "cadence": cadence,
            "events": list(events),
            "count": count,
        }
        for (m, d, duration, beat, cadence, events), count in sorted(counts.items())
    ]
    indices = {key: i for i, key in enumerate(sorted(counts))}
    for i, gesture in enumerate(result["gestures"]):
        gesture["id"] = i
    result["gesture_transitions"] = {
        f"{indices[a]}>{indices[b]}": count for (a, b), count in transitions.items()
    }
    result["gesture_transition_steps"] = {
        f"{indices[a]}>{indices[b]}|{step}": count
        for (a, b, step), count in transition_steps.items()
    }
    return result


def observed_transition_count(
    model, previous_id, current_id, previous, current, before_events, after_events
):
    """Count a source connection only when its geometry and rhythm survive.

    Legacy models retain their original objective for reproducible comparisons.
    Refit models distinguish octave-displaced melodic motion, added chord tones
    and separately stretched adjacent gestures from observed connections.
    Uniform transposition and uniform rhythmic scaling remain supported.
    """
    contexts = model.get("gesture_transition_steps")
    if contexts is None:
        return model.get("gesture_transitions", {}).get(
            f"{previous_id}>{current_id}", 0
        )
    count = contexts.get(
        f"{previous_id}>{current_id}|{current.pitch - previous.pitch}", 0
    )
    if not count:
        return 0
    gestures = {g["id"]: g for g in model["gestures"]}
    first, second = gestures.get(previous_id), gestures.get(current_id)
    if first is None or second is None:
        return 0
    if not math.isclose(
        previous.duration / first["duration"],
        current.duration / second["duration"],
        rel_tol=0,
        abs_tol=1e-7,
    ):
        return 0
    if any(
        sorted(map(tuple, events)) != sorted(map(tuple, gesture["events"]))
        for events, gesture in ((before_events, first), (after_events, second))
    ):
        return 0
    return count


def recorded_completeness_penalty(note, events, identity, melody, by_id):
    """The existing completeness charge, only for an unchanged recorded figure."""
    recorded = by_id.get(identity)
    if recorded is None or sorted(map(tuple, events)) != sorted(
        map(tuple, recorded["events"])
    ):
        return 0.0
    sounding = {note.pitch % 12, *((note.pitch - o) % 12 for o, _, _, _ in events)}
    strong = beat_class(melody, note.start) != "offbeat" or note.duration >= 1.5
    return (0.8 if strong else 0.35) * max(0, 3 - len(sounding))


def source_completion_credit(previous_debt, current_penalty, connected):
    """Refund each supported endpoint once; isolated figures keep their charge."""
    if connected:
        return previous_debt + current_penalty, 0.0
    return 0.0, current_penalty


def _active(events, time, top):
    return tuple(
        sorted({top - offset for offset, a, b, _ in events if a <= time + 1e-7 < b})
    )


def _playable(events, top):
    for time in sorted({a for _, a, _, _ in events}):
        pitches = _active(events, time, top)
        if (
            not pitches
            or min(pitches) < 21
            or max(pitches) >= top
            or _hand_split(pitches, top) is None
        ):
            return False
    return True


def _options(n, melody, model):
    from .chorale_model import _candidates

    gestures = model["gestures"]
    arrivals = model.get("arrival_gestures", [])
    if arrivals and _arrival_note(n, melody, model):
        gestures = gestures + arrivals
    pool = [
        g
        for g in gestures
        if g["mode"] == melody.mode
        and g["degree"] == (n.pitch - melody.tonic) % 12
        and any(abs(n.duration / g["duration"] - ratio) < 1e-6 for ratio in (0.5, 1, 2))
        and _playable(g["events"], n.pitch)
    ]
    total = sum(g["count"] for g in pool)
    choices = []
    cadence = any(abs(n.end - f) < 1e-6 for f in melody.fermatas)
    for g in pool:
        local = -0.28 * math.log((g["count"] + 1) / (total + len(pool)))
        local += 0.35 * (g["beat"] != beat_class(melody, n.start))
        local += 0.2 * abs(math.log2(n.duration / g["duration"]))
        local += 0.5 * (cadence != g["cadence"])
        states = [
            _active(g["events"], t, n.pitch)
            for t in sorted({a for _, a, _, _ in g["events"]})
        ]
        local += 0.15 * sum(max(0, abs(a[0] - b[0]) - 7) for a, b in pairwise(states))
        scale = {(melody.tonic + degree) % 12 for degree in MODES[melody.mode]}
        times = sorted(
            {
                0,
                1,
                *(a for _, a, _, _ in g["events"]),
                *(b for _, _, b, _ in g["events"]),
            }
        )
        for a, b in pairwise(times):
            ps = _active(g["events"], a, n.pitch)
            if ps:
                local += (b - a) * (
                    0.55 * sum(p % 12 not in scale for p in ps)
                    + 0.025 * abs(n.pitch - ps[0] - model["bass_gap"])
                    + 0.5 * any((p - ps[0]) % 12 in (1, 11) for p in [*ps[1:], n.pitch])
                )
        choices.append((g["events"], local, g.get("id", -1)))
    # A transparent fallback for unseen modes/degrees/durations. Do not silently
    # transpose a major gesture into a mode absent from training.
    if not choices:
        choices = [
            ([(n.pitch - p, 0, 1, True) for p in ps], cost, -1)
            for ps, cost in _candidates(n, melody, model)
        ]
    return sorted(choices, key=lambda x: x[1])[:48]


def _arrival_note(n, melody, model):
    """Use actual note endings, never an arbitrary crop or mid-note boundary."""
    if any(abs(n.end - end) < 1e-6 for end in melody.fermatas):
        return True
    if model.get("terminal_cadence") is not None and n == melody.notes[-1]:
        return True
    return any(
        boundary < melody.length
        and not any(x.start < boundary < x.end for x in melody.notes)
        and abs(
            n.end - max((x.end for x in melody.notes if x.end <= boundary), default=-1)
        )
        < 1e-6
        for boundary in melody.phrases
    )


def retain_search_states(states, mode):
    if mode == "beam":
        return sorted(states, key=lambda s: s[0])[:24]
    if mode != "exact":
        raise ValueError("gesture_search must be beam or exact")
    retained = {}
    for state in states:
        cost, path, pitches, previous, identity, pattern, texture, *pending = state
        # Every future transition reads only these fields and the next fixed
        # melody note. Different gesture identities or pending texture ages
        # are not equivalent, even when their sounding pitches coincide.
        key = (
            tuple(sorted(map(tuple, path[-1][1]))),
            pitches,
            previous,
            identity,
            pattern,
            texture,
            tuple(pending),
        )
        if key not in retained or cost < retained[key][0]:
            retained[key] = state
    return sorted(retained.values(), key=lambda s: s[0])


def generate(melody, model, seed=0, tempos=None):
    from .chorale_cadence_contracts import CadencePreparation, advance_destination

    melody.validate()
    search_mode = model.get("gesture_search", "beam")
    if search_mode not in ("beam", "exact"):
        raise ValueError("gesture_search must be beam or exact")
    search_sizes = []
    from .chorale_terminal import anchored_options, sustain_terminal_tail, terminal_goal

    terminal = terminal_goal(melody, model.get("terminal_cadence"))
    goals = []
    continuity_mode = model.get("decoder") == "phrase_continuity_v1"
    phrase_mode = model.get("decoder") in ("phrase_harmony_v1", "phrase_continuity_v1")
    connected_completeness = model.get("connected_source_completeness", False)
    if connected_completeness and (
        not phrase_mode or not isinstance(model.get("gesture_transition_steps"), dict)
    ):
        raise ValueError(
            "Connected completeness requires a phrase decoder and contextual source transitions"
        )
    source_gestures = (
        {g["id"]: g for g in model["gestures"]} if connected_completeness else {}
    )
    if continuity_mode:
        from .chorale_continuity import bridge, choose_context
    if phrase_mode:
        from .chorale_phrases import connection, register_gap
        from .chorale_phrases import options as phrase_options

        gap = register_gap(melody, model)
    if model.get("decoder") in (
        "cadence_context_v1",
        "phrase_harmony_v1",
        "phrase_continuity_v1",
    ):
        from .chorale_cadences import phrase_goals, planned_options

        goals = phrase_goals(melody, model)
    texture_settings = model.get("texture_persistence")
    if texture_settings:
        from .chorale_texture import advance

    beam = [(0.0, [], (), None, -1, None, None, None)]
    if connected_completeness:
        beam = [(*state, 0.0) for state in beam]
    for n in melody.notes:
        rest_context = None
        if continuity_mode and beam[0][3] is not None:
            rest_context = choose_context(melody, beam[0][3], n, model)
        options = _options(n, melody, model)
        if phrase_mode:
            options = phrase_options(n, melody, model, options, gap)
        if goals:
            options = planned_options(n, melody, model, options, goals)
        if model.get("chromatic_context"):
            from .chorale_chromatic import leading_options, unprepared_clash

            options += leading_options(
                n, melody, gap if phrase_mode else model["bass_gap"]
            )
        options = anchored_options(n, melody, model, options, terminal)
        if model.get("structural_search"):
            from .chorale_search_gates import bass_route, valid_extension

            options = [
                choice
                for choice in options
                if bass_route(n.pitch, tuple(map(tuple, choice[0]))) is not None
            ]
        if model.get("register_exposure") is not None:
            from .chorale_register import exposure_penalty

            options = [
                (
                    events,
                    cost + exposure_penalty(n, events, model["register_exposure"]),
                    identity,
                )
                for events, cost, identity in options
            ]
        extensions = []
        for (
            cost,
            path,
            before,
            previous,
            previous_id,
            last_pattern,
            texture,
            pending,
            *debt_state,
        ) in beam:
            for events, local, choice_id in options:
                gesture_id = (
                    choice_id.identity
                    if isinstance(choice_id, CadencePreparation)
                    else choice_id
                )
                valid, next_pending = advance_destination(
                    pending, choice_id, n, events, melody.tonic
                )
                if not valid:
                    continue
                first = _active(events, 0, n.pitch)
                last = _active(events, 1 - 1e-6, n.pitch)
                transition = 0.0
                observed = 0
                next_texture = texture
                if texture_settings:
                    texture_cost, next_texture = advance(
                        texture, previous, n, events, melody, texture_settings
                    )
                    transition += texture_cost
                rest_path = []
                if rest_context is not None:
                    source_pitches = before or _active(
                        path[-1][1],
                        max(b for _, _, b, _ in path[-1][1]) - 1e-6,
                        previous.pitch,
                    )
                    destination = first or _active(
                        events, min(a for _, a, _, _ in events), n.pitch
                    )
                    rest_events, rest_cost = bridge(
                        previous, n, source_pitches, destination, rest_context
                    )
                    transition += rest_cost
                    if not math.isfinite(transition):
                        continue
                    if rest_events:
                        anchor = Event(
                            previous.pitch,
                            previous.end,
                            n.start - previous.end,
                            72,
                            "bridge",
                        )
                        rest_path = [(anchor, rest_events, -4)]
                if model.get("structural_search") and not valid_extension(
                    before, previous, n, events, rest_path
                ):
                    continue
                active_pattern = None if n.start in melody.phrases else last_pattern
                if phrase_mode and gesture_id <= -10:
                    if active_pattern is not None:
                        if gesture_id != active_pattern:
                            transition += 0.12
                        elif not model.get("pattern_prior_per_bar"):
                            transition -= 0.25
                    active_pattern = gesture_id
                continuous = (
                    previous
                    and abs(previous.end - n.start) < 1e-6
                    and n.start not in melody.phrases
                )
                if previous and not continuous and model.get("phrase_bass_connections"):
                    from .chorale_phrases import phrase_bass_connection

                    transition += phrase_bass_connection(before, first, previous, n)
                    if not math.isfinite(transition):
                        continue
                if model.get("chromatic_context") and unprepared_clash(
                    n, melody, events, before, continuous
                ):
                    continue
                if before and first and continuous:
                    if phrase_mode:
                        transition += connection(
                            before,
                            first,
                            path[-1][1],
                            events,
                            n.pitch,
                            previous.pitch,
                            melody.tonic,
                            model,
                        )
                    # Prefer connections actually observed in a source phrase,
                    # rather than treating every compatible grip independently.
                    observed = observed_transition_count(
                        model,
                        previous_id,
                        gesture_id,
                        previous,
                        n,
                        path[-1][1],
                        events,
                    )
                    transition -= 0.7 * math.log1p(observed)
                    transition += 0.065 * abs(first[0] - before[0])
                    transition += 0.12 * max(0, abs(first[0] - before[0]) - 7)
                    if not phrase_mode:
                        transition += 0.035 * sum(
                            min(abs(p - q) for q in before) for p in first[1:]
                        )
                    # A source tie needs an available same-pitch predecessor.
                    transition += 0.28 * sum(
                        n.pitch - offset not in before
                        for offset, a, _, held in events
                        if held and a == 0
                    )
                    transition -= 0.08 * len(set(before) & set(first))
                    if (
                        (previous.pitch - before[0]) % 12 in (0, 7)
                        and (previous.pitch - before[0]) % 12
                        == (n.pitch - first[0]) % 12
                        and (n.pitch - previous.pitch) * (first[0] - before[0]) > 0
                    ):
                        transition += 0.45
                extra_state = ()
                if model.get("phrase_boundary_links"):
                    from .chorale_boundary_links import boundary_support

                    # The existing corpus-connection weight now applies to an
                    # observed cadence/next-entry pair as well. Both harmonic
                    # endpoints must match; a cadence alone earns no credit.
                    transition -= 0.7 * math.log1p(
                        boundary_support(model, melody, previous, n, before, first)
                    )
                if connected_completeness:
                    penalty = recorded_completeness_penalty(
                        n, events, gesture_id, melody, source_gestures
                    )
                    credit, next_debt = source_completion_credit(
                        debt_state[0], penalty, observed > 0
                    )
                    transition -= credit
                    extra_state = (next_debt,)
                extensions.append(
                    (
                        cost + local + transition,
                        path + rest_path + [(n, events, choice_id)],
                        last,
                        n,
                        gesture_id,
                        active_pattern,
                        next_texture,
                        next_pending,
                    )
                    + extra_state
                )
        if not extensions:
            raise ValueError("No candidate passes the active musical gates.")
        beam = retain_search_states(extensions, search_mode)
        search_sizes.append(len(beam))
    beam = [state for state in beam if state[7] is None]
    if not beam:
        raise ValueError("No complete path fulfills the cadence destination contracts")
    cost, path, *_ = beam[0]
    path = sustain_terminal_tail(path, melody, terminal)
    lanes = defaultdict(list)
    hs = []
    for n, events, _ in path:
        for offset, a, b, held in sorted(events, key=lambda x: (x[1], -x[0])):
            p = n.pitch - offset
            start, end = n.start + n.duration * a, n.start + n.duration * b
            pitches = _active(events, a, n.pitch)
            split = _hand_split(pitches, n.pitch)
            role = "bass" if p in pitches[:split] else "inner"
            if (
                n.role == "bridge"
                and model.get("continuity_scope", {}).get("bridge_hand") == "left"
            ):
                role = "bass"
            lane = lanes[p]
            # Preserve source ties, and connect a common tone on a weak arrival.
            # Bar starts and phrase boundaries retain their articulation.
            connect = held or (a == 0 and beat_class(melody, start) != "bar")
            if (
                phrase_mode
                and model.get("sustain_common_inner")
                and a == 0
                and p > pitches[0]
            ):
                connect = True
            if (
                connect
                and lane
                and lane[-1].role == role
                and abs(lane[-1].end - start) < 1e-6
                and start not in melody.phrases
            ):
                lane[-1] = replace(lane[-1], duration=end - lane[-1].start)
            else:
                lane.append(Event(p, start, end - start, 72, role))
        times = sorted(
            {0, 1, *(a for _, a, _, _ in events), *(b for _, _, b, _ in events)}
        )
        for a, b in pairwise(times):
            pitches = _active(events, a, n.pitch)
            if pitches:
                chord = identify_chord(
                    [*pitches] if n.role == "bridge" else [*pitches, n.pitch]
                ) or (
                    pitches[0] % 12,
                    "major",
                )
                hs.append(
                    Harmony(
                        n.start + a * n.duration,
                        n.start + b * n.duration,
                        chord[0],
                        chord[1],
                        pitches[0],
                        tuple(pitches[1:]),
                    )
                )
    result = _layout(
        melody,
        list(melody.notes) + [n for lane in lanes.values() for n in lane],
        hs,
        cost / len(path),
        seed,
        tempos,
    )
    result.diagnostics.update(
        decoder=model["decoder"],
        model_revision=model["revision"],
        phrase_planning="local gestures only; no forced cadence at crop end",
        search={
            "mode": search_mode,
            "total_cost": cost,
            "structural_gates": bool(model.get("structural_search")),
            "retained_states": search_sizes,
            "scope": "Existing pruned candidate vocabulary and transition objective",
        },
    )
    if "gesture_transition_steps" in model:
        connections = []
        for (a, ae, ai), (b, be, bi) in pairwise(path):
            if (
                a.role == "bridge"
                or b.role == "bridge"
                or abs(a.end - b.start) > 1e-6
                or b.start in melody.phrases
            ):
                continue
            ai = ai.identity if isinstance(ai, CadencePreparation) else ai
            bi = bi.identity if isinstance(bi, CadencePreparation) else bi
            legacy = model.get("gesture_transitions", {}).get(f"{ai}>{bi}", 0)
            if legacy:
                connections.append(
                    {
                        "previous_start": a.start,
                        "start": b.start,
                        "melodic_step": b.pitch - a.pitch,
                        "legacy_count": legacy,
                        "context_count": observed_transition_count(
                            model, ai, bi, a, b, ae, be
                        ),
                    }
                )
        result.diagnostics["source_connections"] = connections
    if terminal is not None:
        result.diagnostics["terminal_cadence"] = terminal
    if model.get("phrase_boundary_links"):
        from .chorale_boundary_links import boundary_support

        melodic_path = [step for step in path if step[0].role != "bridge"]
        evidence = []
        for (a, ae, _), (b, be, _) in pairwise(melodic_path):
            count = boundary_support(
                model,
                melody,
                a,
                b,
                _active(ae, 1 - 1e-6, a.pitch),
                _active(be, 0, b.pitch),
            )
            if count:
                evidence.append(
                    {"release": a.end, "next_start": b.start, "recordings": count}
                )
        result.diagnostics["phrase_boundary_connections"] = evidence
    if model.get("arrival_gestures"):
        sources = {g["id"]: g for g in model["arrival_gestures"]}
        result.diagnostics["arrival_figures"] = [
            {
                "start": n.start,
                "end": n.end,
                "gesture_id": identity,
                "source_id": sources[identity]["source_id"],
                "source_end": sources[identity]["source_end"],
            }
            for n, _, identity in path
            if identity in sources
        ]
    if texture_settings:
        result.diagnostics["texture_persistence"] = dict(texture_settings)
        result.diagnostics["texture_windows"] = [
            {
                "start": n.start,
                "duration": n.duration,
                "family": "moving"
                if any(a > 1e-7 for _, a, _, _ in events)
                else "held",
            }
            for n, events, _ in path
            if n.role != "bridge" and n.duration >= 1.5
        ]
    if model.get("decoder") in (
        "cadence_context_v1",
        "phrase_harmony_v1",
        "phrase_continuity_v1",
    ):
        result.diagnostics["cadence_goals"] = goals
        result.diagnostics["phrase_planning"] = (
            "learned cadence contexts with three-note approach; other phrase planning remains local"
        )
    if phrase_mode:
        if continuity_mode:
            result.diagnostics["rest_bridges"] = [
                {"start": n.start, "end": n.end, "events": len(events)}
                for n, events, identity in path
                if identity == -4
            ]
        result.diagnostics["bar_pattern_trace"] = [
            {"start": n.start, "pattern_index": -10 - identity}
            for n, _, choice_id in path
            for identity in [
                choice_id.identity
                if isinstance(choice_id, CadencePreparation)
                else choice_id
            ]
            if identity <= -10
        ]
        result.diagnostics.update(
            phrase_planning="harmonic completion, ordered voices and texture continuity with cadence context",
            register_gap=gap,
        )
    if model.get("cadence_destination_contracts"):
        result.diagnostics["cadence_preparations"] = [
            {
                "start": n.start,
                "destination_end": identity.destination[0],
                "root_degree": identity.destination[1],
                "quality": identity.destination[2],
            }
            for n, _, identity in path
            if isinstance(identity, CadencePreparation)
        ]
    return result
