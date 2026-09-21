"""Conservative gate for sustained minor-ninth outer-voice clashes.

This does not ban sevenths or grade all dissonances. Short ornaments remain
outside its scope. A prepared upper tone may resolve down onto a held bass.
"""

from itertools import pairwise


def melodic_ornament(note, melody, accompaniment):
    """Recognize a short passing/neighbor tone with consonant surrounding tones.

    Consonance is checked against the current accompanying pitches. This is a
    local recognition rule, not an inference of an entire harmonic function.
    """
    if note.duration > 1 or not accompaniment:
        return None
    before = next((n for n in melody.notes if abs(n.end - note.start) < 1e-6), None)
    after = next((n for n in melody.notes if abs(n.start - note.end) < 1e-6), None)
    if before is None or after is None:
        return None
    if any(
        abs(t - note.start) < 1e-6 or abs(t - note.end) < 1e-6
        for t in [*melody.phrases, *melody.fermatas]
    ):
        return None
    incoming, outgoing = note.pitch - before.pitch, after.pitch - note.pitch
    if not (0 < abs(incoming) <= 2 and 0 < abs(outgoing) <= 2):
        return None
    consonant = {0, 3, 4, 7, 8, 9}
    if not all(
        (n.pitch - p) % 12 in consonant for n in (before, after) for p in accompaniment
    ):
        return None
    if incoming * outgoing > 0:
        return "passing"
    if before.pitch == after.pitch:
        return "neighbor"
    return None


def unsupported_minor_ninth(notes, melody, start, end):
    notes = [n for n in notes if n.start < end and n.end > start]
    times = sorted(
        {
            start,
            end,
            *(max(start, n.start) for n in notes),
            *(min(end, n.end) for n in notes),
            *(
                max(start, n.start)
                for n in melody.notes
                if n.start < end and n.end > start
            ),
            *(min(end, n.end) for n in melody.notes if n.start < end and n.end > start),
        }
    )
    spans = []
    for a, b in pairwise(times):
        top = next((n for n in melody.notes if n.start <= a + 1e-7 < n.end), None)
        bass = min(
            (n.pitch for n in notes if n.start <= a + 1e-7 < n.end), default=None
        )
        if top is None or bass is None or (top.pitch - bass) % 12 != 1:
            continue
        if spans and spans[-1][1] == a and spans[-1][2:] == (top, bass):
            spans[-1] = (spans[-1][0], b, top, bass)
        else:
            spans.append((a, b, top, bass))
    for a, b, top, bass in spans:
        if b - a < 1 - 1e-6:
            continue
        following = next(
            (n for n in melody.notes if abs(n.start - top.end) < 1e-6), None
        )
        prepared = top.start < a - 1e-6
        resolves = (
            following is not None
            and following.pitch == top.pitch - 1
            and (following.pitch - bass) % 12 == 0
            and any(
                n.pitch == bass
                and n.start <= a + 1e-7
                and n.end > following.start + 1e-7
                for n in notes
            )
        )
        if not (prepared and resolves):
            return True
    return False
