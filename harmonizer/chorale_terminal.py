"""Explicit tonic closure for complete chorales, never inferred from a crop end."""

from itertools import pairwise

from .chorale_cadences import cadence_choices
from .model import MODES


def terminal_goal(melody, settings):
    if settings is None:
        return None
    if not isinstance(settings, dict) or set(settings) - {"quality"}:
        raise ValueError("terminal_cadence accepts only an optional quality")
    quality = settings.get("quality", "minor" if 3 in MODES[melody.mode] else "major")
    if quality not in ("major", "minor"):
        raise ValueError("Terminal tonic quality must be major or minor")
    pcs = {(melody.tonic + x) % 12 for x in (0, 3 if quality == "minor" else 4, 7)}
    if melody.notes[-1].pitch % 12 not in pcs:
        raise ValueError("Final melody pitch does not fit the requested tonic closure")
    return {
        "root_degree": 0,
        "quality": quality,
        "arrival": melody.notes[-1].start,
        "end": melody.length,
    }


def anchored_options(note, melody, model, options, goal):
    """Filter the entire arrival gesture, not just its last snapshot.

    A leading tone immediately before the final note receives a dominant
    destination. Other approaches remain available to the phrase decoder.
    Intermediate inversions are permitted inside the final tonic gesture.
    """
    if goal is None:
        return options
    final = note == melody.notes[-1]
    leading = (
        len(melody.notes) > 1
        and note == melody.notes[-2]
        and (note.pitch - melody.tonic) % 12 == 11
        and melody.notes[-1].pitch - note.pitch == 1
        and abs(note.end - melody.notes[-1].start) < 1e-7
    )
    if not final and not leading:
        return options
    target = goal if final else {"root_degree": 7, "quality": "major"}
    root = (melody.tonic + target["root_degree"]) % 12
    pcs = {(root + x) % 12 for x in (0, 3 if target["quality"] == "minor" else 4, 7)}
    candidates = list(options)
    candidates.extend(
        (events, cost, -5 if identity == -1 else identity)
        for events, cost, identity in cadence_choices(note, melody, model, target, 0.7)
    )
    accepted = []
    for events, cost, identity in candidates:
        times = sorted(
            {0, 1, *(a for _, a, _, _ in events), *(b for _, _, b, _ in events)}
        )
        valid = True
        for a, b in pairwise(times):
            sounding = sorted(note.pitch - o for o, s, e, _ in events if s <= a < e)
            if not sounding or not {p % 12 for p in sounding} <= pcs:
                valid = False
                break
            if (a == 0 or b == 1) and sounding[0] % 12 != root:
                valid = False
                break
        if valid:
            accepted.append((events, cost, identity))
    return accepted


def sustain_terminal_tail(path, melody, goal):
    if goal is None or melody.notes[-1].end >= melody.length:
        return path
    note, events, identity = path[-1]
    terminal = (melody.length - note.start) / note.duration
    events = [(o, a, terminal if b == 1 else b, held) for o, a, b, held in events]
    return [*path[:-1], (note, events, identity)]
