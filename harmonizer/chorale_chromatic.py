"""Contextual options for chromatic leading notes, with a preparation gate."""

from .chorale_phrases import _voicings
from .model import MODES


def leading_options(n, melody, gap):
    if n.end in melody.phrases or n.end in melody.fermatas:
        return []
    scale = {(melody.tonic + p) % 12 for p in MODES[melody.mode]}
    following = next((x for x in melody.notes if abs(x.start - n.end) < 1e-6), None)
    if n.pitch % 12 in scale or following is None or following.pitch != n.pitch + 1:
        return []
    if following.pitch % 12 not in scale:
        return []
    root = (following.pitch + 7) % 12
    result = []
    for quality in ("major", "dom7"):
        for pitches, layout_cost in _voicings(n.pitch, root, quality, round(gap)):
            result.append(
                ([(n.pitch - p, 0, 1, False) for p in pitches], 1.1 + layout_cost, -5)
            )
    return result


def unprepared_clash(n, melody, events, before, continuous):
    if n.duration < 1 or (n.pitch - melody.tonic) % 12 in MODES[melody.mode]:
        return False
    return any(
        offset == 1
        and a == 0
        and (b - a) * n.duration >= 1 - 1e-7
        and not (continuous and n.pitch - offset in before)
        for offset, a, b, _ in events
    )
