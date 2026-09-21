"""Whole-passage two-hand feasibility, independent of musical voice labels."""

import math
from itertools import pairwise


def simultaneous_hand_options(notes):
    """All noncrossing hand assignments for a simultaneous set of events."""
    order = sorted(range(len(notes)), key=lambda i: (notes[i].pitch, i))
    options = []
    for cut in range(len(order) + 1):
        left = set(order[:cut])
        hands = tuple("LH" if i in left else "RH" for i in range(len(notes)))
        try:
            validate_hands(notes, hands)
        except ValueError:
            continue
        options.append(hands)
    return options


def validate_hands(notes, hands):
    if len(notes) != len(hands) or any(h not in ("LH", "RH") for h in hands):
        raise ValueError("Hand plan must assign every input event")
    if any(n.role in ("melody", "motif") and h != "RH" for n, h in zip(notes, hands)):
        raise ValueError("Melody must remain in the right hand")
    for t in sorted({n.start for n in notes}):
        left, right = (
            [
                n.pitch
                for n, h in zip(notes, hands)
                if h == hand and n.start <= t < n.end
            ]
            for hand in ("LH", "RH")
        )
        if any(p and (max(p) - min(p) > 12 or len(set(p)) > 5) for p in (left, right)):
            raise ValueError("Hand plan exceeds the span or key-count limit")
        if left and right and max(left) >= min(right):
            raise ValueError("Hand plan crosses or splits a unison")


def assign_hands(notes):
    """Return one hand per input event, or None when no stable split exists.

    Melody stays in RH. Hands do not cross. Each simultaneous hand span is at
    most an octave with at most five distinct keys. Held notes cannot change
    hands. This is a geometric assignment, not a fingering or tempo analysis.
    """
    if not notes:
        return []
    if any(n.duration <= 0 for n in notes):
        raise ValueError("Hand planning requires positive note durations")
    if any(not 21 <= n.pitch <= 108 for n in notes):
        return None
    times = sorted({t for n in notes for t in (n.start, n.end)})
    layers = []
    for start, _ in pairwise(times):
        active = sorted(
            (i for i, n in enumerate(notes) if n.start <= start < n.end),
            key=lambda i: (notes[i].pitch, i),
        )
        states = []
        for cut in range(len(active) + 1):
            left, right = active[:cut], active[cut:]
            if left and right and notes[left[-1]].pitch == notes[right[0]].pitch:
                continue
            if any(notes[i].role in ("melody", "motif") for i in left):
                continue
            if any(
                len({notes[i].pitch for i in hand}) > 5
                or (hand and notes[hand[-1]].pitch - notes[hand[0]].pitch > 12)
                for hand in (left, right)
            ):
                continue
            state = {i: ("LH" if i in left else "RH") for i in active}
            cost = sum(
                hand != ("LH" if notes[i].role in ("bass", "tenor") else "RH")
                for i, hand in state.items()
                if notes[i].start == start
            )
            states.append((state, cost))
        if not states:
            return None
        layers.append(states)
    costs = [cost for _, cost in layers[0]]
    parents = []
    for previous, layer in pairwise(layers):
        following, links = [], []
        for state, local in layer:
            options = [
                (cost + local, i)
                for i, ((old, _), cost) in enumerate(zip(previous, costs))
                if math.isfinite(cost)
                and all(old[k] == state[k] for k in old.keys() & state.keys())
            ]
            cost, index = min(options, default=(math.inf, 0))
            following.append(cost)
            links.append(index)
        costs = following
        parents.append(links)
    index = min(range(len(costs)), key=lambda i: costs[i])
    if not math.isfinite(costs[index]):
        return None
    path = [index]
    for links in reversed(parents):
        index = links[index]
        path.append(index)
    hands = [None] * len(notes)
    for layer, index in zip(layers, reversed(path)):
        for i, hand in layer[index][0].items():
            hands[i] = hand
    return hands
