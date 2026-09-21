"""Shortest paths retained separately for each entry/exit signature."""

import math
from itertools import pairwise


def boundary_paths(layers, transition, entry_key, exit_key):
    """Keep the cheapest supplied-state path per pair of boundary signatures.

    Costs are Markovian. Later rejection criteria not represented in the state
    graph can still discard a retained path without recovering its runner-up.
    """
    if not layers or any(not layer for layer in layers):
        return []
    matrices = [
        [[transition(old, new) for old in before] for new in after]
        for before, after in pairwise(layers)
    ]
    retained = []
    for entry in dict.fromkeys(entry_key(state) for state in layers[0]):
        costs = [s[0] if entry_key(s) == entry else math.inf for s in layers[0]]
        parents = []
        for current, matrix in zip(layers[1:], matrices):
            next_costs, links = [], []
            for state, transitions in zip(current, matrix):
                cost, index = min(
                    (c + t, i) for i, (c, t) in enumerate(zip(costs, transitions))
                )
                next_costs.append(cost + state[0])
                links.append(index)
            costs = next_costs
            parents.append(links)
        best = {}
        for i, (cost, state) in enumerate(zip(costs, layers[-1])):
            key = exit_key(state)
            if math.isfinite(cost) and (key not in best or cost < best[key][0]):
                best[key] = (cost, i)
        for cost, index in best.values():
            indices = [index]
            for links in reversed(parents):
                index = links[index]
                indices.append(index)
            retained.append(
                (cost, [layer[i] for layer, i in zip(layers, reversed(indices))])
            )
    return sorted(retained, key=lambda item: item[0])


def sounding_signature(state, time):
    return tuple(
        sorted((n.role, n.pitch) for _, n in state[3] if n.start <= time < n.end)
    )
