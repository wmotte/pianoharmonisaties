"""Opt-in texture hysteresis across melody-note windows.

Short notes cannot establish whether an accompaniment figure has stopped.
Only windows long enough to contain a separate attack update the state.
This is a search preference, not a musical quality score.
"""

from .chorale_gestures import beat_class


def advance(state, previous, note, events, melody, settings):
    """Return (search cost, state) without forcing notes or changing harmony."""
    boundary = previous is None or any(
        previous.start < t <= note.start + 1e-7
        for t in [*melody.phrases, *melody.fermatas]
    )
    boundary = boundary or (
        previous is not None and note.start - previous.end >= 1 - 1e-7
    )
    if boundary:
        state = None
    if note.duration < 1.5:
        return 0.0, state
    family = "moving" if any(a > 1e-7 for _, a, _, _ in events) else "held"
    if state is None:
        return 0.0, (family, note.start)
    old_family, since = state
    if family == old_family:
        return 0.0, state
    _, numerator, denominator = next(
        m for m in reversed(melody.meters) if m[0] <= note.start + 1e-7
    )
    minimum = settings.get("minimum_bars", 1.0) * numerator * 4 / denominator
    age = note.start - since
    # Established textures can change on a bar line at little cost. Early or
    # weak-beat changes require stronger harmonic/voice-leading evidence.
    cost = settings.get("switch_cost", 1.0)
    if age >= minimum and beat_class(melody, note.start) == "bar":
        cost *= 0.15
    elif age < minimum:
        cost *= 1 + (minimum - age) / max(minimum, 1e-7)
    return cost, (family, note.start)
