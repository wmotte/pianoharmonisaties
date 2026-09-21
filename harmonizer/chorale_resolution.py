"""Conservative evidence for a short step into a sustained bass octave.

This describes a note pattern, not its stylistic or harmonic acceptability.
Polyphonic roles without an unambiguous continuation remain unclassified.
"""


def steps_to_bass_octave(notes):
    result = []
    for index, note in enumerate(notes):
        if note.duration > 1:
            continue
        before = [
            n for n in notes if n.role == note.role and n.start < note.end <= n.end
        ]
        after = [
            n for n in notes if n.role == note.role and n.start <= note.end < n.end
        ]
        if len(before) != 1 or len(after) != 1:
            continue
        following = after[0]
        if abs(following.start - note.end) > 1e-7:
            continue
        if abs(following.pitch - note.pitch) != 1:
            continue
        anchors = [
            n
            for n in notes
            if n.pitch < min(note.pitch, following.pitch)
            and n.start <= note.start
            and n.end >= following.end
            and (following.pitch - n.pitch) % 12 == 0
        ]
        for anchor in anchors:
            if any(
                n.pitch < anchor.pitch
                and n.start < following.end
                and n.end > note.start
                for n in notes
            ):
                continue
            result.append(
                {
                    "note_index": index,
                    "start": note.start,
                    "end": note.end,
                    "pitch": note.pitch,
                    "resolution_pitch": following.pitch,
                    "bass_pitch": anchor.pitch,
                    "role": note.role,
                }
            )
            break
    return result
