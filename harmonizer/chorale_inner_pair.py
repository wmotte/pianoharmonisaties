"""Exact two-slot inner-voice search with fixed note identities and occupancy."""

import math
from dataclasses import replace
from itertools import pairwise, product, zip_longest

from .chorale_hand_plan import simultaneous_hand_options, validate_hands
from .chorale_inner_line import _pitch_bounds
from .chorale_phrase_transfer import _local_loss
from .chorale_source_protection import source_supported_resolutions
from .chorale_targets import compatible_targets
from .model import MODES


def revoice_inner_pair(
    notes,
    melody,
    targets,
    *,
    source_contexts=(),
    diagnostics=None,
    plan_hands=False,
    obligations=(),
    protected_indices=(),
):
    """Keep every attack and duration; infer lower/upper inner slots jointly.

    None is an actual source rest, never an option to remove a difficult note.
    A held note retains pitch and hand. Its vertical slot may change when
    the other voice rests and reenters on the opposite side. More than two
    simultaneous inner notes require a different voice model and are rejected.
    Slot identity
    is an inferred arrangement choice, not a recovered historical SATB label.
    Explicit protected indices retain their input pitch throughout the path.
    """
    trace = diagnostics if diagnostics is not None else {}
    trace.clear()
    for contract in obligations:
        if (
            not 0 <= contract.trigger_index < len(notes)
            or notes[contract.trigger_index].role != "inner"
            or contract.expires_at < notes[contract.trigger_index].start
        ):
            raise ValueError("Invalid resolution trigger or deadline")
    inner = {i: n for i, n in enumerate(notes) if n.role == "inner"}
    protected_indices = tuple(protected_indices)
    if any(not isinstance(i, int) or i not in inner for i in protected_indices):
        raise ValueError("Protected identity must name an existing inner note")
    fixed = [n for n in notes if n.role not in ("inner", "melody")]
    protected = {
        i
        for e in source_supported_resolutions(notes, source_contexts)
        for i in e["protected_indices"]
    }
    protected.update(protected_indices)
    times = sorted({0, melody.length, *(t for n in notes for t in (n.start, n.end))})
    spans = list(pairwise(times))
    if any(sum(n.start <= a < n.end for n in inner.values()) > 2 for a, _ in spans):
        raise ValueError("More than two simultaneous inner notes")
    pcs = {(melody.tonic + p) % 12 for p in MODES[melody.mode]}
    domains = {}
    for i, note in inner.items():
        lo, hi = _pitch_bounds(note, fixed, melody, right_hand=not plan_hands)
        domains[i] = [
            p
            for p in range(lo, hi + 1)
            if (p == note.pitch or p % 12 in pcs)
            and (i not in protected or p == note.pitch)
        ]
    layers = []
    for start, end in spans:
        ids = sorted(
            (i for i, n in inner.items() if n.start <= start < n.end),
            key=lambda i: (inner[i].pitch, i),
        )
        states = []
        for pitches in product(*(domains[i] for i in ids)):
            if len(pitches) == 2 and pitches[0] >= pitches[1]:
                continue
            active = [replace(inner[i], pitch=p) for i, p in zip(ids, pitches)]
            accompaniment = fixed + active
            if not compatible_targets(
                list(enumerate(accompaniment)), melody, targets, start, end
            ):
                continue
            cost = _local_loss(
                accompaniment,
                melody,
                start,
                end,
                contextual_ornaments=True,
                check_hand_spans=not plan_hands,
            ) * max(1, end - start)
            cost += sum(
                0.03 * abs(p - inner[i].pitch)
                for i, p in zip(ids, pitches)
                if inner[i].start == start
            )
            if not math.isfinite(cost):
                continue
            assignments = tuple(zip(ids, pitches))
            slots = (
                [(None, None)]
                if not ids
                else (
                    [(assignments[0], None), (None, assignments[0])]
                    if len(ids) == 1
                    else [assignments]
                )
            )
            hand_states = [((), 0.0)]
            if plan_hands:
                pitch_map = dict(assignments)
                active_ids = [
                    i for i, n in enumerate(notes) if n.start <= start < n.end
                ]
                events = [
                    replace(notes[i], pitch=pitch_map.get(i, notes[i].pitch))
                    for i in active_ids
                ]
                hand_states = []
                for hands in simultaneous_hand_options(events):
                    hand_cost = 0.03 * sum(
                        h != ("LH" if n.role in ("bass", "tenor") else "RH")
                        for n, h in zip(events, hands)
                        if n.start == start
                    )
                    hand_states.append((tuple(zip(active_ids, hands)), hand_cost))
            states.extend(((s, h), cost + hc) for s in slots for h, hc in hand_states)
        trace.setdefault("layer_sizes", []).append(len(states))
        if not states:
            trace["status"] = "empty_layer"
            return None
        layers.append(states)

    def transition(before, after, t):
        before, before_hands = before
        after, after_hands = after
        old_hands, new_hands = dict(before_hands), dict(after_hands)
        if any(
            old_hands[i] != new_hands[i] for i in old_hands.keys() & new_hands.keys()
        ):
            return math.inf
        old = {v[0]: (slot, v[1]) for slot, v in enumerate(before) if v is not None}
        new = {v[0]: (slot, v[1]) for slot, v in enumerate(after) if v is not None}
        held = old.keys() & new.keys()
        if any(old[i][1] != new[i][1] for i in held):
            return math.inf
        if len(old) > 1 and len(new) > 1 and any(old[i][0] != new[i][0] for i in held):
            return math.inf
        if (
            len(old) == len(new) == 1
            and next(iter(old.values()))[0] != next(iter(new.values()))[0]
        ):
            return math.inf
        cost = 0.0
        # Match held identities first. When the other voice has rested, its
        # reentry may be below a held note formerly in the lower slot. That
        # changes vertical rank, not the held note's pitch or physical hand.
        connections = [((i, old[i][1]), (i, new[i][1])) for i in sorted(held)]
        connections.extend(
            zip_longest(
                (v for v in before if v is not None and v[0] not in held),
                (v for v in after if v is not None and v[0] not in held),
            )
        )
        for a, b in connections:
            if a is None or b is None:
                cost += 0.05 * (a != b)
                continue
            i, p = a
            j, q = b
            movement = abs(q - p)
            if i != j and inner[i].pitch != inner[j].pitch and p == q:
                return math.inf
            if movement > max(7, abs(inner[i].pitch - inner[j].pitch)):
                return math.inf
            cost += 0.08 * movement + 0.02 * max(0, movement - 4) ** 2
            for lane, perfect in ((fixed, (0, 7)), (melody.notes, (0, 5))):
                left = [n.pitch for n in lane if n.start < t <= n.end]
                right = [n.pitch for n in lane if n.start <= t < n.end]
                if left and right:
                    x, y = min(left), min(right)
                    if (
                        (p - x) % 12 in perfect
                        and (p - x) % 12 == (q - y) % 12
                        and (q - p) * (y - x) > 0
                    ):
                        return math.inf
        if all(x is not None for x in before + after):
            p, q = (x[1] for x in before)
            r, s = (x[1] for x in after)
            if (
                (q - p) % 12 in (0, 7)
                and (q - p) % 12 == (s - r) % 12
                and (s - q) * (r - p) > 0
            ):
                return math.inf
        return cost

    if obligations:
        from .chorale_obligations import augmented_path, obligation_step

        solved = augmented_path(
            layers,
            lambda a, b, k: transition(a, b, spans[k][0]),
            lambda pending, state, k: obligation_step(
                pending, state, *spans[k], obligations, notes, fixed, melody
            ),
        )
        if solved is None:
            trace["status"] = "no_contract_path"
            return None
        cost, augmented = solved
        trace["cost"] = cost
        trace["obligation_path"] = [list(pending) for _, pending in augmented]
        path = list(reversed([i for i, _ in augmented]))
    else:
        costs = [cost for _, cost in layers[0]]
        parents = []
        for k, layer in enumerate(layers[1:], 1):
            following, links = [], []
            for state, local in layer:
                options = [
                    (cost + local + transition(previous, state, spans[k][0]), j)
                    for j, ((previous, _), cost) in enumerate(zip(layers[k - 1], costs))
                    if math.isfinite(cost)
                ]
                cost, j = min(options, default=(math.inf, 0))
                following.append(cost)
                links.append(j)
            if not any(math.isfinite(cost) for cost in following):
                trace.update(
                    status="no_path",
                    first_unreachable_span=list(spans[k]),
                    reachable_previous_states=[
                        state
                        for (state, _), cost in zip(layers[k - 1], costs)
                        if math.isfinite(cost)
                    ],
                    rejected_next_states=[state for state, _ in layer],
                )
                return None
            parents.append(links)
            costs = following
        index = min(range(len(costs)), key=lambda i: costs[i])
        if not math.isfinite(costs[index]):
            trace["status"] = "no_path"
            return None
        trace["cost"] = costs[index]
        path = [index]
        for links in reversed(parents):
            index = links[index]
            path.append(index)
    result = list(notes)
    chosen = [layer[i][0] for layer, i in zip(layers, reversed(path))]
    hands = [None] * len(notes)
    for state, hand_state in chosen:
        for i, hand in hand_state:
            hands[i] = hand
        for item in state:
            if item is not None:
                i, pitch = item
                result[i] = replace(notes[i], pitch=pitch)
    trace.update(
        status="realized",
        slots=[
            {"start": a, "end": b, "slots": state, "hands": hand_state}
            for (a, b), (state, hand_state) in zip(spans, chosen)
        ],
    )
    if plan_hands:
        validate_hands(result, hands)
        trace["hands"] = hands
    return result
