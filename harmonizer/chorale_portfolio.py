"""Enumerate distinct accompaniment plans without changing musical costs."""

import heapq
import math
from itertools import count, pairwise

from .chorale_priority_paths import priority_paths


def distinct_paths(layers, transition, priority, identity, limit=8):
    """Return the best path for each of the first distinct identity sequences.

    Rank by summed nonnegative priority, then existing path cost. Partition the
    remaining identity sequences after each solution, so voicing variants of
    one plan cannot fill the portfolio. This is exact within the supplied
    layers, which may themselves have been produced by a bounded decoder.
    """
    if limit < 1 or not layers or any(not layer for layer in layers):
        return []
    ids = {id(state): identity(state) for layer in layers for state in layer}
    # Precompute transitions once. Subproblems only restrict identities.
    edges = {}
    for before, after in pairwise(layers):
        for left in before:
            for right in after:
                edges[id(left), id(right)] = transition(left, right)

    def solve(prefix, banned):
        restricted = [
            [
                state
                for state in layer
                if (i >= len(prefix) or ids[id(state)] == prefix[i])
                and (i != len(prefix) or ids[id(state)] not in banned)
            ]
            for i, layer in enumerate(layers)
        ]
        paths = priority_paths(restricted, lambda a, b: edges[id(a), id(b)], priority)
        if not paths:
            return None
        cost, path = paths[0]
        rank = (sum(priority(s) for s in path), cost)
        if not all(math.isfinite(x) for x in rank):
            return None
        return rank, path

    initial = solve((), frozenset())
    if initial is None:
        return []
    serial = count()
    queue = [(initial[0], next(serial), (), frozenset(), initial[1])]
    result = []
    while queue and len(result) < limit:
        rank, _, prefix, banned, path = heapq.heappop(queue)
        result.append((rank[1], path))
        if len(result) == limit:
            break
        sequence = tuple(ids[id(state)] for state in path)
        for i in range(len(prefix), len(layers)):
            excluded = (banned if i == len(prefix) else frozenset()) | {sequence[i]}
            following = solve(sequence[:i], excluded)
            if following is not None:
                heapq.heappush(
                    queue,
                    (
                        following[0],
                        next(serial),
                        sequence[:i],
                        excluded,
                        following[1],
                    ),
                )
    return result
