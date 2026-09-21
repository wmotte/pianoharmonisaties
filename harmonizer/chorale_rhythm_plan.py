"""Keep a retrieved phrase bass rhythm fixed while planning its pitches."""

import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from itertools import pairwise

from .chorale_bass_plan import bass_connection, inner_connection
from .chorale_gestures import _active, _options
from .chorale_model import _hand_split, _layout
from .chorale_phrase_transfer import global_path
from .chorale_phrases import options as phrase_options
from .chorale_phrases import register_gap
from .engine import Harmony
from .model import Event
from .profile import identify_chord


def rhythm_features(notes, length):
    return [
        len(notes) / length,
        sum(n.duration for n in notes) / length,
        sum(n.duration for n in notes if n.duration >= 2) / length,
        sum(abs(n.start - round(n.start)) > 1e-6 for n in notes) / max(1, len(notes)),
    ]


def fit_rhythm(model, references):
    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError("Rhythm donors must exactly match the disclosed training IDs.")
    donors = []
    for e, m, a in references:
        if len(m.meters) != 1:
            continue
        bass = []
        attack_pitches = {}
        for n in a.notes:
            if n.role == "melody":
                continue
            active = [x.pitch for x in a.notes if x.start <= n.start + 1e-7 < x.end]
            if n.pitch == min(active):
                # End at the next real bass attack, or at this note's release.
                bass.append((n.start, n.end))
                attack_pitches[n.start] = n.pitch
        bass = sorted(set(bass))
        bass = [
            (a, min(b, bass[i + 1][0]) if i + 1 < len(bass) else b)
            for i, (a, b) in enumerate(bass)
        ]
        donors.append(
            {
                "source_id": e["source_id"],
                "group": e["group"],
                "source_sha256": e.get("source_sha256"),
                "meter": m.meters[0][1:],
                "length": m.length,
                "bass": bass,
                "contour": [
                    (time, (pitch > previous) - (pitch < previous))
                    for (_, previous), (time, pitch) in pairwise(
                        sorted(attack_pitches.items())
                    )
                ],
                "melody": [(n.start, n.end) for n in m.notes],
            }
        )
    result = deepcopy(model)
    result.update(decoder="phrase_rhythm_v1", rhythm_donors=donors)
    return result


def schedules(melody, model):
    if len(melody.meters) != 1:
        return []
    target = rhythm_features(melody.notes, melody.length)
    result = []
    for donor in model["rhythm_donors"]:
        if (
            tuple(donor["meter"]) != tuple(melody.meters[0][1:])
            or donor["length"] + 1e-6 < melody.length
        ):
            continue
        source = [
            Event(60, a, min(b, melody.length) - a)
            for a, b in donor["melody"]
            if a < melody.length
        ]
        features = rhythm_features(source, melody.length)
        distance = sum(abs(a - b) for a, b in zip(target, features))
        # Preserve the donor's rhythm exactly, with no stretching or repetition.
        bass = [
            (a, min(b, melody.length)) for a, b in donor["bass"] if a < melody.length
        ]
        # Reject source silences that would leave a new target melody note
        # unsupported. Do not erase those silences or invent replacement beats.
        if any(
            sum(max(0, min(n.end, b) - max(n.start, a)) for a, b in bass)
            < n.duration - 1e-6
            for n in melody.notes
        ):
            continue
        result.append((distance, donor, bass))
    return sorted(result, key=lambda row: (row[0], row[1]["source_id"]))


def _static_options(n, melody, model, gap, goals):
    from .chorale_cadences import planned_options

    options = phrase_options(n, melody, model, _options(n, melody, model), gap)
    options = planned_options(n, melody, model, options, goals)
    result = []
    for events, cost, identity in options:
        if not all(a == 0 and b == 1 for _, a, b, _ in events):
            continue
        result.append((events, cost, identity))
    return result


def arrange_schedule(melody, model, donor, rhythm, seed, tempos):
    from .chorale_cadences import propose
    from .chorale_continuity import choose_context

    rest_windows = [
        (previous.end, following.start, previous)
        for previous, following in pairwise(melody.notes)
        if choose_context(melody, previous, following, model) is not None
    ]
    goals = [propose(melody, end, model) for end in melody.fermatas]
    gap = register_gap(melody, model)
    cache = {n: _static_options(n, melody, model, gap, goals) for n in melody.notes}
    boundaries = sorted(
        {
            0,
            melody.length,
            *(t for a, b in rhythm for t in (a, b)),
            *(t for n in melody.notes for t in (n.start, n.end)),
        }
    )
    layers = []
    for start, end in pairwise(boundaries):
        top = next((n for n in melody.notes if n.start <= start + 1e-7 < n.end), None)
        beat = next(((a, b) for a, b in rhythm if a <= start + 1e-7 < b), None)
        bridge = top is None
        if bridge:
            top = next(
                (previous for a, b, previous in rest_windows if a <= start + 1e-7 < b),
                None,
            )
        if top is None or beat is None:
            continue
        anchor = Event(
            top.pitch, start, end - start, 72, "bridge" if bridge else "melody"
        )
        goal = next((g for g in goals if g and abs(g["end"] - end) < 1e-6), None)
        groups = defaultdict(list)
        for events, local, identity in cache[top]:
            pitches = _active(events, 0, top.pitch)
            chord = identify_chord([*pitches, top.pitch])
            if goal and (
                not chord
                or ((chord[0] - melody.tonic) % 12, chord[1])
                != (goal["root_degree"], goal["quality"])
            ):
                continue
            bass = pitches[0]
            held = start > beat[0] + 1e-6
            altered = [
                (offset, 0, 1, held if top.pitch - offset == bass else True)
                for offset, _, _, _ in events
            ]
            signature = ((top.pitch - bass, 0, 1, held),)
            label = chord if model.get("fixed_harmonic_cells") else None
            groups[(signature, label)].append(
                (local * anchor.duration, anchor, altered, identity)
            )
        layers.append(
            [
                (
                    0.025 * abs(bass[0][0] - gap) * anchor.duration,
                    anchor,
                    bass,
                    choices,
                    label,
                    top.start,
                )
                for (bass, label), choices in groups.items()
            ]
        )
    if not layers:
        return None

    def connect(old, new):
        old_note, new_note = old[1], new[1]
        if model.get("fixed_harmonic_cells") and old[5] == new[5] and old[4] != new[4]:
            return math.inf
        if (
            new[2][0][3]
            and abs(old_note.end - new_note.start) < 1e-6
            and old_note.pitch - old[2][-1][0] != new_note.pitch - new[2][0][0]
        ):
            return math.inf
        direction = next(
            (
                direction
                for time, direction in donor.get("contour", [])
                if abs(time - new_note.start) < 1e-6
            ),
            None,
        )
        if direction is not None and abs(old_note.end - new_note.start) < 1e-6:
            old_pitch = old_note.pitch - old[2][-1][0]
            new_pitch = new_note.pitch - new[2][0][0]
            if (new_pitch > old_pitch) - (new_pitch < old_pitch) != direction:
                return math.inf
        if old_note.role == "bridge" or new_note.role == "bridge":
            p = old_note.pitch - old[2][-1][0]
            q = new_note.pitch - new[2][0][0]
            return 0.045 * abs(q - p) + 0.25 * max(0, abs(q - p) - 7)
        return bass_connection(old[:4], new[:4])

    first = global_path(layers, connect)
    if first is None:
        return None
    _, route = first
    second = global_path([state[3] for state in route], inner_connection)
    if second is None:
        return None
    _, path = second
    # Roles follow the same playable split as the candidate. Bass attacks are
    # never merged unless the fixed rhythm explicitly continues the same note.
    lanes = defaultdict(list)
    harmony = []
    for _, n, events, _ in path:
        pitches = _active(events, 0, n.pitch)
        split = _hand_split(pitches, n.pitch)
        for offset, _, _, held in events:
            pitch = n.pitch - offset
            role = "bass" if pitch in pitches[:split] else "inner"
            lane = lanes[pitch]
            if (
                held
                and lane
                and lane[-1].role == role
                and abs(lane[-1].end - n.start) < 1e-6
            ):
                lane[-1] = replace(lane[-1], duration=n.end - lane[-1].start)
            else:
                lane.append(Event(pitch, n.start, n.duration, 72, role))
        chord = identify_chord([*pitches, *([n.pitch] if n.role != "bridge" else [])])
        if chord:
            harmony.append(
                Harmony(n.start, n.end, *chord, pitches[0], tuple(pitches[1:]))
            )
    result = _layout(
        melody,
        list(melody.notes) + [n for lane in lanes.values() for n in lane],
        harmony,
        0,
        seed,
        tempos,
    )
    result.diagnostics.update(
        decoder="phrase_rhythm_v1",
        rhythm_donor=donor["source_id"],
        rhythm_source_sha256=donor["source_sha256"],
        fixed_harmonic_cells=bool(model.get("fixed_harmonic_cells")),
        rhythm_schedule=rhythm,
        scope="One complete unwarped source rhythm and bass contour; melody-rest eligibility uses the existing context model.",
        cadence_goals=goals,
    )
    return result


def generate(melody, model, seed=0, tempos=None):
    from .chorale_model import generate_chorale

    melody.validate()
    for rank, (distance, donor, rhythm) in enumerate(schedules(melody, model)):
        result = arrange_schedule(melody, model, donor, rhythm, seed, tempos)
        if result:
            result.diagnostics.update(
                rhythm_rank=rank, rhythm_context_distance=distance
            )
            return result
    fallback = generate_chorale(
        melody, dict(model, decoder="two_pass_bass_v1"), seed, tempos
    )
    fallback.diagnostics["rhythm_fallback"] = (
        "No compatible complete rhythm has a feasible pitch route."
    )
    return fallback
