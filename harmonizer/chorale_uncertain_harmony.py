"""Fit categorical probabilities from sets of possible observed labels.

Unknown chord identities remain latent. Positive symmetric pseudocounts keep
the probabilities finite. These fits do not certify transcription labels.
"""

import math

import numpy as np


def _fit(masks, weights, size, alpha, max_iterations, tolerance):
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be positive and finite")
    if max_iterations < 1 or tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("Invalid iteration controls")
    if not masks or any(not mask for mask in masks):
        raise ValueError("Observations and their candidate sets must be nonempty")
    if any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError("Observation weights must be positive and finite")
    probability = np.full(size, 1 / size)
    prior = alpha / size
    indices = [np.array(sorted(set(mask)), dtype=int) for mask in masks]

    def objective(p):
        return sum(
            w * math.log(float(p[ix].sum())) for ix, w in zip(indices, weights)
        ) + prior * float(np.log(p).sum())

    objectives = [objective(probability)]
    converged = False
    for iteration in range(1, max_iterations + 1):
        counts = np.full(size, prior)
        for ix, weight in zip(indices, weights):
            counts[ix] += weight * probability[ix] / probability[ix].sum()
        updated = counts / counts.sum()
        objectives.append(objective(updated))
        difference = float(np.abs(updated - probability).sum())
        probability = updated
        if difference <= tolerance:
            converged = True
            break
    return probability, {
        "iterations": iteration,
        "converged": converged,
        "objectives": objectives,
        "observations": len(masks),
        "total_weight": sum(weights),
    }


def _label(value):
    # JSON turns tuple-valued chord labels into lists.
    if isinstance(value, (tuple, list)):
        value = tuple(_label(x) for x in value)
    try:
        hash(value)
    except TypeError as error:
        raise ValueError("Labels must be hashable categories") from error
    return value


def _domain(labels):
    labels = [_label(value) for value in labels]
    if not labels or len(set(labels)) != len(labels):
        raise ValueError("Labels must form a nonempty unique domain")
    return labels, {label: i for i, label in enumerate(labels)}


def fit_label_sets(
    observations, labels, *, alpha=1.0, max_iterations=100, tolerance=1e-9
):
    """Fit a marginal from (candidate_labels, weight) observations."""
    labels, index = _domain(labels)
    observations = list(observations)
    try:
        masks = [
            [index[_label(x)] for x in candidates] for candidates, _ in observations
        ]
    except KeyError as error:
        raise ValueError("Observation label outside domain") from error
    probabilities, diagnostics = _fit(
        masks,
        [w for _, w in observations],
        len(labels),
        alpha,
        max_iterations,
        tolerance,
    )
    return {"labels": labels, "probabilities": probabilities.tolist(), **diagnostics}


def fit_pair_sets(
    observations, labels, *, alpha=1.0, max_iterations=100, tolerance=1e-9
):
    """Fit a joint table from (previous_candidates, next_candidates, weight)."""
    labels, index = _domain(labels)
    observations = list(observations)
    size = len(labels)
    try:
        masks = [
            [index[_label(a)] * size + index[_label(b)] for a in left for b in right]
            for left, right, _ in observations
        ]
    except KeyError as error:
        raise ValueError("Observation label outside domain") from error
    probabilities, diagnostics = _fit(
        masks,
        [w for _, _, w in observations],
        size * size,
        alpha,
        max_iterations,
        tolerance,
    )
    return {
        "labels": labels,
        "probabilities": probabilities.reshape(size, size).tolist(),
        **diagnostics,
    }


def condition_pair(model, previous, allowed):
    """Condition on a possible previous chord set and melody-compatible labels.

    No observed target chord set is accepted here: that would leak the answer
    into prediction. `allowed` must be constructed from the input melody.
    """
    labels, index = _domain(model["labels"])
    previous = {_label(x) for x in previous}
    allowed = {_label(x) for x in allowed}
    if not previous or not allowed:
        raise ValueError("Prediction requires previous and allowed labels")
    try:
        rows = [index[x] for x in previous]
        columns = [i for i, x in enumerate(labels) if x in allowed]
        if len(columns) != len(allowed):
            raise KeyError("allowed")
    except KeyError as error:
        raise ValueError("Prediction label outside domain") from error
    matrix = np.asarray(model["probabilities"])
    values = matrix[np.ix_(rows, columns)].sum(axis=0)
    values /= values.sum()
    return {labels[i]: float(value) for i, value in zip(columns, values)}
