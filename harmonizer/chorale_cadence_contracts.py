"""Keep a synthetic cadence preparation attached to its offered destination."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CadencePreparation:
    identity: int
    destination: tuple  # (arrival end, root degree, quality)


def preparation_targets(destination, mode):
    """Offer diatonic dominants of relative goals, plus the existing tonic V."""
    from .chorale_phrases import CHORDS
    from .model import MODES

    degree = destination["root_degree"]
    if degree != 0 and destination["quality"] not in ("major", "minor"):
        return []
    root = (degree + 7) % 12
    return [
        {"root_degree": root, "quality": quality}
        for quality in ("major", "dom7")
        if degree == 0 or {(root + i) % 12 for i in CHORDS[quality]} <= set(MODES[mode])
    ]


def advance_destination(pending, identity, note, events, tonic):
    """Return (valid, pending); arrival must establish the promised harmony."""
    if isinstance(identity, CadencePreparation):
        if pending is not None and pending != identity.destination:
            return False, pending
        pending = identity.destination
    if pending is None:
        return True, None
    end, degree, quality = pending
    if note.end > end + 1e-7:
        return False, pending
    if note.end < end - 1e-7:
        return True, pending
    from .chorale_phrases import CHORDS

    intervals = CHORDS[quality]
    root = (tonic + degree) % 12
    pcs = {(root + i) % 12 for i in intervals}
    sounding = {
        note.pitch % 12,
        *((note.pitch - p) % 12 for p, a, b, _ in events if a <= 1 - 1e-7 < b),
    }
    # A missing fifth is allowed. Root, third, and any defining seventh are not.
    required = {(root + i) % 12 for i in intervals if i != 7}
    valid = required <= sounding <= pcs
    return valid, None if valid else pending
