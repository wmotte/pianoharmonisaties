"""Monotone alignment of an explicit melody with polyphonic performance attacks."""

from itertools import pairwise

import numpy as np
import pretty_midi


def align_melody(melody_path, groups):
    """Return proposed (melody-note, attack-group) pairs, never infer a melody.

    Extra accompaniment attacks can be skipped. Missing melody notes remain
    missing instead of being replaced by a highest-note heuristic. The position
    term discourages matches with a distant repeated phrase.
    """
    midi = pretty_midi.PrettyMIDI(str(melody_path))
    notes = sorted(
        [n for i in midi.instruments if not i.is_drum for n in i.notes],
        key=lambda n: n.start,
    )
    if not notes or not groups:
        raise ValueError("Lege melodie of uitvoering bij uitlijning.")
    if any(a.end > b.start + 0.03 for a, b in pairwise(notes)):
        raise ValueError("Gecontroleerde melodie-MIDI moet eenstemmig zijn.")
    n, m = len(notes), len(groups)
    score_length = max(notes[-1].end - notes[0].start, 0.01)
    audio_length = max(groups[-1][0].start - groups[0][0].start, 0.01)
    dp = np.full((n + 1, m + 1), np.inf)
    action = np.zeros((n + 1, m + 1), dtype=np.uint8)
    dp[0, :] = np.arange(m + 1) * 0.03
    dp[:, 0] = np.arange(n + 1) * 2
    action[0, 1:] = 1
    action[1:, 0] = 2
    for i, note in enumerate(notes, 1):
        relative = (note.start - notes[0].start) / score_length
        for j, group in enumerate(groups, 1):
            matched = any(p.pitch == note.pitch for p in group)
            time = (group[0].start - groups[0][0].start) / audio_length
            candidates = (
                dp[i, j - 1] + 0.03,
                dp[i - 1, j] + 2,
                dp[i - 1, j - 1] + (0 if matched else 5) + abs(relative - time),
            )
            index = int(np.argmin(candidates))
            dp[i, j] = candidates[index]
            action[i, j] = index + 1
    i, j, pairs = n, m, []
    while i or j:
        step = action[i, j]
        if step == 1:
            j -= 1
        elif step == 2:
            i -= 1
        elif step == 3:
            if any(p.pitch == notes[i - 1].pitch for p in groups[j - 1]):
                pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        else:
            raise AssertionError("Ongeldig uitlijnpad.")
    pairs.reverse()
    return (
        notes,
        pairs,
        {
            "matched_fraction": len(pairs) / n,
            "melody_notes": n,
            "matched_notes": len(pairs),
            "status": "automatic_alignment_proposal",
        },
    )
