"""Transfer complete accompaniment timelines, adapting harmony by measure."""

import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from itertools import pairwise
from statistics import median

from .chorale_model import _layout
from .engine import Harmony
from .model import MODES, Event, piano_hand
from .profile import identify_chord


def fit_transfer(model, references):
    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError(
            "Phrase donors must be exactly the disclosed training identities."
        )
    result = deepcopy(model)
    result["decoder"] = "whole_phrase_transfer_v1"
    result["fallback_decoder"] = model.get("fallback_decoder", model.get("decoder", ""))
    result["phrase_donors"] = [
        {
            "source_id": e["source_id"],
            "group": e["group"],
            "source_sha256": e.get("source_sha256"),
            "tonic": m.tonic,
            "mode": m.mode,
            "length": m.length,
            "meters": m.meters,
            "melody_register": median(n.pitch for n in m.notes),
            "melody": [(n.pitch, n.start, n.end) for n in m.notes],
            "notes": [
                (n.pitch, n.start, n.end, n.role) for n in a.notes if n.role != "melody"
            ],
        }
        for e, m, a in references
    ]
    return result


@lru_cache(maxsize=65536)
def mapped_pitch(pitch, source_tonic, target_tonic, mode, degree_shift, octave):
    scale = MODES[mode]
    # Locate the nearest scale tone and preserve its chromatic alteration.
    candidates = [
        (source_tonic + 12 * k + interval, 7 * k + i)
        for k in range(-2, 12)
        for i, interval in enumerate(scale)
    ]
    natural, degree = min(candidates, key=lambda x: (abs(x[0] - pitch), x[0]))
    new_degree = degree + degree_shift
    octaves, index = divmod(new_degree, 7)
    return target_tonic + 12 * octaves + scale[index] + pitch - natural + octave


def _local_loss(
    notes,
    melody,
    start,
    end,
    *,
    contextual_ornaments=False,
    supported_suspensions=(),
    check_hand_spans=True,
):
    notes = [n for n in notes if n.start < end and n.end > start]
    times = sorted(
        {
            start,
            end,
            *(max(start, n.start) for n in notes),
            *(min(end, n.end) for n in notes),
            *(
                max(start, n.start)
                for n in melody.notes
                if n.start < end and n.end > start
            ),
            *(min(end, n.end) for n in melody.notes if n.start < end and n.end > start),
        }
    )
    cost = 0.0
    for a, b in pairwise(times):
        active = [n for n in notes if n.start <= a + 1e-7 < n.end]
        top = next((n for n in melody.notes if n.start <= a + 1e-7 < n.end), None)
        if not active:
            cost += (b - a) * 0.2
            continue
        ps = sorted({n.pitch for n in active})
        if len(ps) != len(active):
            return math.inf
        if min(ps) < 21 or max(ps) > 108:
            return math.inf
        left = [n.pitch for n in active if n.role == "bass"]
        right = [n.pitch for n in active if n.role != "bass"] + (
            [top.pitch] if top else []
        )
        if check_hand_spans and any(
            hand and max(hand) - min(hand) > 12 for hand in (left, right)
        ):
            return math.inf
        if top:
            if max(ps) >= top.pitch:
                return math.inf
            chord = identify_chord([*ps, top.pitch])
            interval = (top.pitch - ps[0]) % 12
            dissonant = interval in (1, 2, 6, 10, 11)
            passing = top.duration <= 1 and any(
                abs(n.start - top.end) < 1e-6 and abs(n.pitch - top.pitch) <= 2
                for n in melody.notes
            )
            if contextual_ornaments:
                from .chorale_dissonance import melodic_ornament

                passing = melodic_ornament(top, melody, ps) is not None
            if top in supported_suspensions:
                passing = True
            local = (0.3 if passing else 1.5) * dissonant
            local += 0 if chord else 0.18
            local += 0.45 * (len({top.pitch % 12, *(p % 12 for p in ps)}) == 1)
            # The donor's alto was consonant with a different melody. Avoid
            # turning a long target note into an unprepared upper-voice cluster.
            local += (0.2 if passing else 1.0) * sum(0 < top.pitch - p <= 2 for p in ps)
            cost += (b - a) * local
    return cost / max(1, end - start)


def global_path(layers, transition):
    """Exact shortest path through layered Markov states, without beam pruning.

    Each state starts with its local cost. Future costs depend only on the
    preceding state. This guarantee does not extend beyond the supplied states.
    """
    if not layers or any(not layer for layer in layers):
        return None
    costs = [state[0] for state in layers[0]]
    parents = []
    for previous, current in pairwise(layers):
        next_costs, links = [], []
        for state in current:
            cost, parent = min(
                (costs[i] + transition(old, state), i) for i, old in enumerate(previous)
            )
            next_costs.append(cost + state[0])
            links.append(parent)
        costs = next_costs
        parents.append(links)
    index = min(range(len(costs)), key=costs.__getitem__)
    total = costs[index]
    if not math.isfinite(total):
        return None
    indices = [index]
    for links in reversed(parents):
        index = links[index]
        indices.append(index)
    return total, [layer[i] for layer, i in zip(layers, reversed(indices))]


def _connection(previous, current):
    _, old_shift, old_octave, old_events = previous
    _, shift, octave, events = current
    cost = 0.12 * abs(shift - old_shift) + 0.2 * abs(octave - old_octave) / 12
    old = dict(old_events)
    for identity, note in events:
        if identity in old and old[identity].pitch != note.pitch:
            cost += 0.4
    # Penalize actual bass movement, which can differ from the scale transform.
    if old_events and events:
        boundary = min(n.start for _, n in events)
        ending = [n.pitch for _, n in old_events if abs(n.end - boundary) < 1e-6]
        starting = [n.pitch for _, n in events if abs(n.start - boundary) < 1e-6]
        if ending and starting:
            leap = abs(min(starting) - min(ending))
            cost += 0.04 * max(0, leap - 2) + 0.2 * max(0, leap - 7)
    return cost


def _cadences_match(events, melody, start, end, goals):
    notes = [n for _, n in events] + list(melody.notes)
    for at, goal in goals:
        if start < at <= end:
            pitches = [n.pitch for n in notes if n.start <= at - 1e-6 < n.end]
            chord = identify_chord(pitches)
            alternatives = goal.get("alternatives") or [goal]
            if not chord or not any(
                ((chord[0] - melody.tonic) % 12, chord[1])
                == (option["root_degree"], option["quality"])
                and (
                    "bass_degree" not in option
                    or (min(pitches) - melody.tonic) % 12 == option["bass_degree"]
                )
                for option in alternatives
            ):
                return False
    return True


def octave_voicings(events, melody, start, end, *, flexible_hands=False):
    """Retain bass and source identities while trying inner-voice octaves.

    This bounded search changes neither pitch classes nor attack/release times.
    It supplies alternatives, without claiming they form a good inner line.
    """
    fixed = [(i, n) for i, n in events if n.role == "bass"]
    beam = [(0, fixed)]
    for identity, note in sorted(
        ((i, n) for i, n in events if n.role != "bass"),
        key=lambda row: (row[1].start, row[0]),
    ):
        candidates = []
        for cost, path in beam:
            for octave in (0, -12, 12):
                event = replace(note, pitch=note.pitch + octave)
                extended = [*path, (identity, event)]
                if math.isfinite(
                    _local_loss(
                        [n for _, n in extended],
                        melody,
                        start,
                        end,
                        check_hand_spans=not flexible_hands,
                    )
                ):
                    candidates.append((cost + abs(octave) / 12, extended))
        beam = sorted(candidates, key=lambda row: row[0])[:12]
        if not beam:
            break
    return [path for _, path in beam]


def adapt_donor(
    melody,
    donor,
    seed=0,
    tempos=None,
    cadence_goals=(),
    *,
    dissonance_gate=False,
    revoice_inner_octaves=False,
    contextual_ornaments=False,
    boundary_variants=False,
    register_fidelity=False,
    preserve_source_dominants=False,
    harmonic_targets=(),
    complete_target_harmony=False,
    revoice_target_harmony=False,
    contextual_suspensions=False,
    fixed_scale_degree=False,
    minimize_completion=False,
    preserve_source_motion=False,
    preserve_source_contour=False,
    extended_source_motion=False,
    metric_phase=0.0,
    search_trace=None,
    source_contour_scope="all",
    flexible_hands=False,
    structural_search=False,
):
    if source_contour_scope not in ("all", "bass"):
        raise ValueError("source_contour_scope must be all or bass")
    if search_trace is not None:
        search_trace.update(
            status="searching", layers=[], planned_paths=0, realized_paths=0
        )
    # No arbitrary time stretching or meter conversion: preserve source rhythm.
    from .chorale_source_spans import meter_timeline, metered_spans

    if meter_timeline(melody.meters, melody.length) != meter_timeline(
        donor["meters"], melody.length
    ):
        if search_trace is not None:
            search_trace["status"] = "meter_mismatch"
        return [] if boundary_variants else None
    if donor["mode"] != melody.mode or donor["length"] + 1e-6 < melody.length:
        if search_trace is not None:
            search_trace["status"] = "mode_or_length_mismatch"
        return [] if boundary_variants else None
    spans = metered_spans(melody.length, melody.meters, metric_phase)
    if abs(donor.get("metric_phase", 0.0) - metric_phase) > 1e-7:
        if search_trace is not None:
            search_trace["status"] = "metric_phase_mismatch"
        return [] if boundary_variants else None
    register = 12 * round(
        (
            median(n.pitch for n in melody.notes)
            - donor["melody_register"]
            - (melody.tonic - donor["tonic"])
        )
        / 12
    )
    segments = []
    motion_pairs = []
    contour_pairs = []
    motion_anchors = []
    if preserve_source_motion or preserve_source_contour:
        from .chorale_motion import (
            bass_motion_pairs,
            extended_motion_evidence,
            has_collapsed_motion,
            has_displaced_anchor,
            has_distorted_contour,
            source_motion_pairs,
        )

        motion_pairs = source_motion_pairs(donor, extended=extended_source_motion)
        contour_pairs = (
            bass_motion_pairs(donor["notes"], motion_pairs)
            if source_contour_scope == "bass"
            else motion_pairs
        )
        if extended_source_motion:
            motion_anchors = extended_motion_evidence(donor)
    source_links = []
    if preserve_source_dominants:
        from .chorale_functions import dominant_links, preserves_links

        source_links = dominant_links(donor)

    def source_motion_valid(events):
        if motion_anchors and has_displaced_anchor(
            events, motion_anchors, donor["notes"]
        ):
            return False
        if motion_pairs and has_collapsed_motion(events, motion_pairs):
            return False
        return not (
            preserve_source_contour
            and has_distorted_contour(events, contour_pairs, donor["notes"])
        )

    if register_fidelity:
        from .chorale_register import gap_distribution, register_distance

        if not donor.get("melody"):
            raise ValueError("Source melody is required for register comparison.")
        source_melody = [Event(p, a, b - a) for p, a, b in donor["melody"]]
        source_notes = [
            Event(p, a, b - a, 72, role) for p, a, b, role in donor["notes"]
        ]
    for start, end in spans:
        audit = Counter()
        if search_trace is not None:
            search_trace["layers"].append({"start": start, "end": end, "counts": audit})
        if register_fidelity:
            source_profile = gap_distribution(source_notes, source_melody, start, end)
        source = [
            (i, p, max(a, start), min(b, end), role)
            for i, (p, a, b, role) in enumerate(donor["notes"])
            if a < end - 1e-6 and b > start + 1e-6
        ]
        options = []
        for shift in (0,) if fixed_scale_degree else range(-3, 4):
            for octave in (
                register - 24,
                register - 12,
                register,
                register + 12,
                register + 24,
            ):
                events = [
                    (
                        i,
                        Event(
                            mapped_pitch(
                                p,
                                donor["tonic"],
                                melody.tonic,
                                melody.mode,
                                shift,
                                octave,
                            ),
                            a,
                            b - a,
                            72,
                            role,
                        ),
                    )
                    for i, p, a, b, role in source
                ]
                variants = (
                    octave_voicings(
                        events, melody, start, end, flexible_hands=flexible_hands
                    )
                    if revoice_inner_octaves
                    else [events]
                )
                if search_trace is not None:
                    audit["octave_variants"] += len(variants)
                if harmonic_targets and revoice_target_harmony:
                    from .chorale_targets import revoice_targets

                    immutable = {
                        i
                        for i, (_, a, b, _) in enumerate(donor["notes"])
                        if any(a < target["start"] < b for target in harmonic_targets)
                    }
                    variants = [
                        voiced
                        for variant in variants
                        for voiced in revoice_targets(
                            variant,
                            melody,
                            harmonic_targets,
                            start,
                            end,
                            immutable_ids=immutable,
                            allow_completion=complete_target_harmony,
                            partial_validator=source_motion_valid
                            if motion_pairs or motion_anchors
                            else None,
                        )
                    ]
                    if search_trace is not None:
                        audit["after_target_revoice"] += len(variants)
                if harmonic_targets and complete_target_harmony:
                    from .chorale_targets import complete_targets

                    variants = [
                        completed
                        for variant in variants
                        for completed in complete_targets(
                            variant, melody, harmonic_targets, start, end
                        )
                    ]
                    if search_trace is not None:
                        audit["after_completion"] += len(variants)
                for voiced in variants:
                    if motion_anchors and has_displaced_anchor(
                        voiced, motion_anchors, donor["notes"]
                    ):
                        if search_trace is not None:
                            audit["displaced_anchor"] += 1
                        continue
                    if motion_pairs and has_collapsed_motion(voiced, motion_pairs):
                        if search_trace is not None:
                            audit["collapsed_motion"] += 1
                        continue
                    if preserve_source_contour and has_distorted_contour(
                        voiced, contour_pairs, donor["notes"]
                    ):
                        if search_trace is not None:
                            audit["distorted_contour"] += 1
                        continue
                    if harmonic_targets:
                        from .chorale_targets import compatible_targets

                        if not compatible_targets(
                            voiced, melody, harmonic_targets, start, end
                        ):
                            if search_trace is not None:
                                audit["incompatible_target"] += 1
                            continue
                    if source_links and not preserves_links(
                        voiced, source_links, start, end
                    ):
                        if search_trace is not None:
                            audit["lost_source_dominant"] += 1
                        continue
                    cost = _local_loss(
                        [n for _, n in voiced],
                        melody,
                        start,
                        end,
                        contextual_ornaments=contextual_ornaments,
                        check_hand_spans=not flexible_hands,
                    )
                    if structural_search:
                        from .chorale_search_gates import timeline_issues

                        issues = timeline_issues(
                            [n for _, n in voiced], melody.notes, start, end
                        )
                        if issues:
                            if search_trace is not None:
                                audit.update(issues)
                            continue
                    if flexible_hands and math.isfinite(cost):
                        from .chorale_hand_plan import assign_hands

                        window_notes = [n for _, n in voiced] + [
                            replace(
                                n,
                                start=max(start, n.start),
                                duration=min(end, n.end) - max(start, n.start),
                            )
                            for n in melody.notes
                            if n.start < end and n.end > start
                        ]
                        if assign_hands(window_notes) is None:
                            cost = math.inf
                    if register_fidelity:
                        target_profile = gap_distribution(
                            [n for _, n in voiced], melody.notes, start, end
                        )
                        cost += register_distance(source_profile, target_profile)
                    if dissonance_gate:
                        from .chorale_dissonance import unsupported_minor_ninth

                        if unsupported_minor_ninth(
                            [n for _, n in voiced], melody, start, end
                        ):
                            if search_trace is not None:
                                audit["unsupported_minor_ninth"] += 1
                            continue
                    if math.isfinite(cost) and _cadences_match(
                        voiced, melody, start, end, cadence_goals
                    ):
                        cost += 0.035 * abs(shift) + 0.03 * abs(octave - register) / 12
                        options.append((cost, shift, octave, voiced))
                        if search_trace is not None:
                            audit["accepted"] += 1
                    elif search_trace is not None:
                        audit["geometry_or_cadence"] += 1
        if not options:
            if search_trace is not None:
                search_trace["status"] = "empty_layer"
            return [] if boundary_variants else None
        segments.append((start, end, options))
    layers = [options for _, _, options in segments]
    bounds = {
        id(option): (start, end)
        for start, end, options in segments
        for option in options
    }

    def transition(previous, current):
        if structural_search:
            from .chorale_search_gates import timeline_issues

            if timeline_issues(
                [n for _, n in previous[3] + current[3]],
                melody.notes,
                bounds[id(previous)][0],
                bounds[id(current)][1],
            ):
                return math.inf
        if motion_anchors and has_displaced_anchor(
            previous[3] + current[3], motion_anchors, donor["notes"]
        ):
            return math.inf
        if preserve_source_contour and has_distorted_contour(
            previous[3] + current[3], contour_pairs, donor["notes"]
        ):
            return math.inf
        if motion_pairs and has_collapsed_motion(
            previous[3] + current[3], motion_pairs
        ):
            return math.inf
        if source_links:
            joined = previous[3] + current[3]
            if not joined:
                return _connection(previous, current)
            if not preserves_links(
                joined,
                source_links,
                min(n.start for _, n in joined),
                max(n.end for _, n in joined),
            ):
                return math.inf
        connection = _connection(previous, current)
        if contextual_suspensions and math.isfinite(connection):
            from .chorale_suspensions import prepared_suspensions

            previous_start, boundary = bounds[id(previous)]
            _, end = bounds[id(current)]
            joined = [n for _, n in previous[3] + current[3]]
            evidence = prepared_suspensions(
                melody, joined, previous_start, boundary, end
            )
            if evidence:
                notes = [n for _, n in current[3]]
                original = _local_loss(
                    notes,
                    melody,
                    boundary,
                    end,
                    contextual_ornaments=contextual_ornaments,
                    check_hand_spans=not flexible_hands,
                )
                adjusted = _local_loss(
                    notes,
                    melody,
                    boundary,
                    end,
                    contextual_ornaments=contextual_ornaments,
                    check_hand_spans=not flexible_hands,
                    supported_suspensions=tuple(
                        melody.notes[e["melody_index"]] for e in evidence
                    ),
                )
                connection += adjusted - original
        return connection

    if minimize_completion:
        from .chorale_boundaries import sounding_signature
        from .chorale_priority_paths import priority_paths

        plans = priority_paths(
            layers,
            transition,
            lambda state: sum(n.duration for identity, n in state[3] if identity < 0),
            (lambda state: sounding_signature(state, 0)) if boundary_variants else None,
            (lambda state: sounding_signature(state, melody.length - 1e-6))
            if boundary_variants
            else None,
        )
    elif boundary_variants:
        from .chorale_boundaries import boundary_paths, sounding_signature

        plans = boundary_paths(
            layers,
            transition,
            lambda state: sounding_signature(state, 0),
            lambda state: sounding_signature(state, melody.length - 1e-6),
        )
    else:
        planned = global_path(layers, transition)
        plans = [] if planned is None else [planned]
    results = []
    if search_trace is not None:
        search_trace["planned_paths"] = len(plans)
    for planned in plans:
        result = _realize_donor(
            melody,
            donor,
            segments,
            planned,
            seed,
            tempos,
            dissonance_gate,
            revoice_inner_octaves,
            flexible_hands,
        )
        if result is not None:
            if structural_search:
                from .chorale_search_gates import timeline_issues

                if timeline_issues(
                    [n for n in result.notes if n.role != "melody"],
                    melody.notes,
                    0,
                    melody.length,
                ):
                    continue
                result.diagnostics["structural_search"] = True
            result.diagnostics["metric_phase"] = metric_phase
            if preserve_source_motion or preserve_source_contour:
                result.diagnostics["preserved_source_motion_pairs"] = motion_pairs
                result.diagnostics["extended_source_motion"] = extended_source_motion
                result.diagnostics["source_contour_scope"] = source_contour_scope
                result.diagnostics["preserved_source_contour_pairs"] = contour_pairs
                result.diagnostics["source_contour_constraint"] = (
                    preserve_source_contour
                )
            result.diagnostics["completion_note_quarters"] = sum(
                n.duration
                for state in planned[1]
                for identity, n in state[3]
                if identity < 0
            )
            if minimize_completion:
                result.diagnostics["completion_selection"] = (
                    "minimum_added_note_time_then_musical_cost"
                )
            if contextual_suspensions:
                from .chorale_suspensions import prepared_suspensions

                evidence = []
                for previous, current in pairwise(planned[1]):
                    previous_start, boundary = bounds[id(previous)]
                    _, end = bounds[id(current)]
                    evidence.extend(
                        dict(item, boundary=boundary)
                        for item in prepared_suspensions(
                            melody,
                            [n for _, n in previous[3] + current[3]],
                            previous_start,
                            boundary,
                            end,
                        )
                    )
                result.diagnostics["conditional_suspensions"] = evidence
            if preserve_source_dominants:
                result.diagnostics["preserved_source_dominants"] = source_links
            if register_fidelity:
                result.diagnostics["register_fidelity"] = {
                    "reference": "donor melody to lowest accompaniment",
                    "distance": "duration-weighted Wasserstein",
                    "unit": "octaves",
                }
            results.append(result)
    if search_trace is not None:
        search_trace.update(
            status="realized" if results else "no_realized_path",
            realized_paths=len(results),
        )
    return results if boundary_variants else next(iter(results), None)


def _realize_donor(
    melody,
    donor,
    segments,
    planned,
    seed,
    tempos,
    dissonance_gate,
    revoice_inner_octaves,
    flexible_hands=False,
):
    cost, states = planned
    path = [
        (start, end, shift, octave, events)
        for (start, end, _), (_, shift, octave, events) in zip(segments, states)
    ]
    lanes = defaultdict(list)
    for start, end, shift, octave, events in path:
        for identity, n in events:
            lane = lanes[identity]
            if (
                lane
                and lane[-1].pitch == n.pitch
                and abs(lane[-1].end - n.start) < 1e-6
            ):
                lane[-1] = replace(lane[-1], duration=n.end - lane[-1].start)
            else:
                lane.append(n)
    notes = list(melody.notes) + [n for lane in lanes.values() for n in lane]
    harmony = []
    for n in melody.notes:
        ps = sorted({e.pitch for e in notes if e.start <= n.start + 1e-7 < e.end})
        chord = identify_chord(ps)
        if chord:
            harmony.append(
                Harmony(n.start, n.end, chord[0], chord[1], ps[0], tuple(ps[1:-1]))
            )
    result = _layout(melody, notes, harmony, cost / len(path), seed, tempos)
    if flexible_hands:
        from .chorale_hand_plan import assign_hands

        hands = assign_hands(result.notes)
        if hands is None:
            return None
        result.diagnostics["hands"] = hands
    for t in () if flexible_hands else {n.start for n in notes}:
        for hand in ("LH", "RH"):
            ps = [
                n.pitch
                for n in notes
                if n.start <= t + 1e-7 < n.end and piano_hand(n, result) == hand
            ]
            if ps and max(ps) - min(ps) > 12:
                return None
    result.diagnostics.update(
        method="whole_phrase_transfer",
        planner="exact_layered_dynamic_programming",
        cadence_constraints_in_search=True,
        donor_source_id=donor["source_id"],
        donor_group=donor["group"],
        donor_sha256=donor["source_sha256"],
        time_warp=False,
        bar_transforms=[
            {"start": a, "end": b, "scale_steps": s, "octave_shift": o}
            for a, b, s, o, _ in path
        ],
    )
    if dissonance_gate:
        result.diagnostics["minor_ninth_gate"] = True
    if revoice_inner_octaves:
        result.diagnostics["inner_octave_adjustments"] = [
            {
                "source_note": identity,
                "start": n.start,
                "pitch": n.pitch,
                "original_mapping": mapped_pitch(
                    donor["notes"][identity][0],
                    donor["tonic"],
                    melody.tonic,
                    melody.mode,
                    shift,
                    octave,
                ),
            }
            for _, _, shift, octave, events in path
            for identity, n in events
            if identity >= 0
            and n.role != "bass"
            and n.pitch
            != mapped_pitch(
                donor["notes"][identity][0],
                donor["tonic"],
                melody.tonic,
                melody.mode,
                shift,
                octave,
            )
        ]
        adjustments = result.diagnostics["inner_octave_adjustments"]
        result.diagnostics["inner_octave_adjustments"] = [
            a for a in adjustments if (a["pitch"] - a["original_mapping"]) % 12 == 0
        ]
        changed_classes = [
            a for a in adjustments if (a["pitch"] - a["original_mapping"]) % 12 != 0
        ]
        if changed_classes:
            result.diagnostics["inner_pitch_class_adjustments"] = changed_classes
    return result


def generate(melody, model, seed=0, tempos=None):
    from .chorale_cadences import phrase_goals
    from .chorale_model import generate_chorale

    melody.validate()
    candidates = []
    goals = [(goal["end"], goal) for goal in phrase_goals(melody, model)]
    for donor in model["phrase_donors"]:
        candidate = adapt_donor(
            melody,
            donor,
            seed,
            tempos,
            goals,
            dissonance_gate=model.get("passage_dissonance_gate", False),
            revoice_inner_octaves=model.get("revoice_inner_octaves", False),
            contextual_ornaments=model.get("contextual_ornaments", False),
            register_fidelity=model.get("register_fidelity", False),
            preserve_source_dominants=model.get("preserve_source_dominants", False),
            contextual_suspensions=model.get("contextual_suspensions", False),
            fixed_scale_degree=model.get("fixed_scale_degree", False),
            minimize_completion=model.get("minimize_completion", False),
            preserve_source_motion=model.get("preserve_source_motion", False),
            preserve_source_contour=model.get("preserve_source_contour", False),
            extended_source_motion=model.get("extended_source_motion", False),
            source_contour_scope=model.get("source_contour_scope", "all"),
            flexible_hands=model.get("flexible_hands", False),
            structural_search=model.get("structural_search", False),
        )
        if candidate is not None:
            candidates.append(candidate)
    if candidates:
        best = min(
            candidates,
            key=lambda a: (
                a.diagnostics.get("completion_note_quarters", 0)
                if model.get("minimize_completion")
                else 0,
                a.score,
            ),
        )
        best.diagnostics["feasible_donors"] = len(candidates)
        best.diagnostics["cadence_goals"] = [goal for _, goal in goals]
        return best
    fallback = deepcopy(model)
    fallback["decoder"] = model["fallback_decoder"]
    result = generate_chorale(melody, fallback, seed, tempos)
    result.diagnostics["whole_phrase_fallback"] = (
        "No compatible complete donor passed meter, geometry and cadence constraints."
    )
    return result
