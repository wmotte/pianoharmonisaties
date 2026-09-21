"""Layered paths with an explicit non-compensating primary criterion."""

import math
from itertools import pairwise


def priority_paths(layers, transition, priority, entry_key=None, exit_key=None):
    """Minimize summed priority, then musical cost, per boundary pair.

    Infeasible edges remain infeasible regardless of either score. Without
    boundary keys the result contains at most one complete path.
    """
    if not layers or any(not layer for layer in layers):
        return []
    entry_key = entry_key or (lambda state: None)
    exit_key = exit_key or (lambda state: None)
    primary = [[priority(state) for state in layer] for layer in layers]
    if any(not math.isfinite(p) or p < 0 for layer in primary for p in layer):
        raise ValueError("Path priorities must be finite and nonnegative.")
    edges = [
        [[transition(a, b) for a in before] for b in after]
        for before, after in pairwise(layers)
    ]
    retained = []
    for entry in dict.fromkeys(entry_key(s) for s in layers[0]):
        costs = [
            (p, s[0])
            if entry_key(s) == entry and math.isfinite(s[0])
            else (math.inf, math.inf)
            for p, s in zip(primary[0], layers[0])
        ]
        parents = []
        for layer, priorities, matrix in zip(layers[1:], primary[1:], edges):
            following, links = [], []
            for state, p, row in zip(layer, priorities, matrix):
                options = [
                    ((cost[0] + p, cost[1] + edge + state[0]), index)
                    for index, (cost, edge) in enumerate(zip(costs, row))
                    if math.isfinite(cost[1])
                    and math.isfinite(edge)
                    and math.isfinite(state[0])
                ]
                cost, parent = min(options, default=((math.inf, math.inf), 0))
                following.append(cost)
                links.append(parent)
            costs = following
            parents.append(links)
        best = {}
        for index, (cost, state) in enumerate(zip(costs, layers[-1])):
            key = exit_key(state)
            if math.isfinite(cost[1]) and (key not in best or cost < best[key][0]):
                best[key] = (cost, index)
        for cost, index in best.values():
            indices = [index]
            for links in reversed(parents):
                index = links[index]
                indices.append(index)
            path = [layer[i] for layer, i in zip(layers, reversed(indices))]
            retained.append((cost, path))
    return [
        (cost[1], path) for cost, path in sorted(retained, key=lambda item: item[0])
    ]
