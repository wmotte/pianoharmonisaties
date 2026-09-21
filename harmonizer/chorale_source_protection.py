"""Protect resolution figures only after exact aligned source-context matching."""

from .chorale_resolution import steps_to_bass_octave


def _context(notes, start, end, origin, transpose=0):
    return sorted(
        (
            n.pitch + transpose,
            round(n.start - origin, 7),
            round(n.end - origin, 7),
            n.role,
        )
        for n in notes
        if n.start < end and n.end > start
    )


def source_supported_resolutions(notes, source_contexts):
    """Return provenance and input identities for source-exact octave steps.

    Each context supplies events in local donor time, its target_start and
    length, and source_id/source_sha256/source_start. Only the aligned passage
    is checked. All overlapping notes, including melody and their full timings,
    must agree under one chromatic transposition. Added notes prevent a match.
    This establishes source fidelity, not harmonic suitability in a new phrase.
    """
    output = []
    for evidence in steps_to_bass_octave(notes):
        i = evidence["note_index"]
        note = notes[i]
        if note.role != "inner":
            continue
        following = [
            (j, n)
            for j, n in enumerate(notes)
            if n.role == note.role and abs(n.start - note.end) < 1e-7
        ]
        if len(following) != 1:
            continue
        j, nxt = following[0]
        for context in source_contexts:
            offset = context["target_start"]
            if note.start < offset or nxt.end > offset + context["length"]:
                continue
            source = context["events"]
            for original in steps_to_bass_octave(source):
                old = source[original["note_index"]]
                if old.role != note.role or abs(old.start + offset - note.start) > 1e-7:
                    continue
                shift = note.pitch - old.pitch
                if _context(notes, note.start, nxt.end, offset) != _context(
                    source, note.start - offset, nxt.end - offset, 0, shift
                ):
                    continue
                output.append(
                    {
                        "protected_indices": [i, j],
                        "source_id": context["source_id"],
                        "source_sha256": context["source_sha256"],
                        "source_start": context["source_start"],
                        "target_start": offset,
                        "source_resolution_start": context["source_start"] + old.start,
                        "target_resolution_start": note.start,
                        "transpose": shift,
                    }
                )
    return output
