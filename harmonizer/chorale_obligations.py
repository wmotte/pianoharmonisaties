"""Explicit, conditional resolution obligations for the two-slot decoder."""

import math
from dataclasses import dataclass, replace
from itertools import pairwise


@dataclass(frozen=True)
class ResolutionObligation:
    trigger_index: int
    trigger_pitch: int
    target_pitch: int
    expires_at: float

    def __post_init__(self):
        if not 0 < abs(self.target_pitch - self.trigger_pitch) <= 2:
            raise ValueError("A resolution obligation must specify a step")
        if not math.isfinite(self.expires_at):
            raise ValueError("Resolution deadline must be finite")


def consonant_outer_context(note, fixed, melody):
    times = sorted(
        {
            note.start,
            note.end,
            *(
                t
                for n in [*fixed, *melody.notes]
                for t in (n.start, n.end)
                if note.start < t < note.end
            ),
        }
    )
    for t, _ in pairwise(times):
        top = [n.pitch for n in melody.notes if n.start <= t < n.end]
        bass = [n.pitch for n in fixed if n.start <= t < n.end]
        if len(top) != 1 or not bass or not min(bass) < note.pitch < top[0]:
            return False
        if (top[0] - note.pitch) % 12 not in (3, 4, 7, 8, 9) or (
            note.pitch - min(bass)
        ) % 12 not in (0, 3, 4, 7, 8, 9):
            return False
    return True


def obligation_step(pending, state, start, end, contracts, notes, fixed, melody):
    slots, _ = state
    active = dict(pending)
    for slot, cid in list(active.items()):
        contract = contracts[cid]
        item = slots[slot]
        if item is not None and item[0] != contract.trigger_index:
            i, pitch = item
            if (
                pitch != contract.target_pitch
                or notes[i].start > contract.expires_at
                or not consonant_outer_context(
                    replace(notes[i], pitch=pitch), fixed, melody
                )
            ):
                return None
            del active[slot]
    for cid, contract in enumerate(contracts):
        for slot, item in enumerate(slots):
            if (
                item == (contract.trigger_index, contract.trigger_pitch)
                and notes[item[0]].start == start
            ):
                if slot in active:
                    return None
                active[slot] = cid
    if any(end > contracts[cid].expires_at + 1e-7 for cid in active.values()):
        return None
    return tuple(sorted(active.items()))


def augmented_path(layers, transition, advance):
    """Exact DP keyed by both musical state and outstanding obligations."""
    if not layers or any(not layer for layer in layers):
        return None
    costs = {}
    for i, (state, cost) in enumerate(layers[0]):
        pending = advance((), state, 0)
        if pending is not None and math.isfinite(cost):
            costs[i, pending] = cost
    parents = []
    for k, layer in enumerate(layers[1:], 1):
        following, links, edges = {}, {}, {}
        for previous, oldcost in costs.items():
            j, pending = previous
            for i, (state, local) in enumerate(layer):
                pair = (j, i)
                if pair not in edges:
                    edges[pair] = transition(layers[k - 1][j][0], state, k)
                score = oldcost + local + edges[pair]
                if not math.isfinite(score):
                    continue
                obligations = advance(pending, state, k)
                if obligations is None:
                    continue
                key = (i, obligations)
                if score < following.get(key, math.inf):
                    following[key], links[key] = score, previous
        costs = following
        parents.append(links)
    finished = [(cost, key) for key, cost in costs.items() if not key[1]]
    if not finished:
        return None
    cost, key = min(finished)
    path = [key]
    for links in reversed(parents):
        key = links[key]
        path.append(key)
    return cost, list(reversed(path))
