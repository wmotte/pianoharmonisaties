"""Trace possible ornaments in an upper strand above a repeated LH note."""

from collections import Counter, defaultdict


def arpeggio_evidence(notes, start, end):
    """Return evidence only. Do not remove notes or assign chord labels.

    The bass role denotes source left-hand notes in these corpus experiments.
    A unique repeated pitch and a monophonic upper attack strand are required.
    Supplied window boundaries are hypotheses owned by the caller.
    """
    if end <= start:
        raise ValueError("Arpeggio evidence needs a positive window.")
    active = [
        (i, n)
        for i, n in enumerate(notes)
        if n.role == "bass" and start <= n.start < end
    ]
    counts = Counter(n.pitch for _, n in active)
    repeated = [
        p for p, count in counts.items() if count >= 3 and count == max(counts.values())
    ]
    result = {"repeated_pitch": None, "strand_indices": [], "ornaments": []}
    if len(repeated) != 1:
        return result
    pedal = repeated[0]
    by_onset = defaultdict(list)
    for i, n in active:
        if n.pitch > pedal:
            by_onset[n.start].append((i, n))
    # Multiple upper notes at one attack do not establish one melodic strand.
    if any(len(group) != 1 for group in by_onset.values()):
        return result
    strand = [group[0] for _, group in sorted(by_onset.items())]
    result.update(repeated_pitch=pedal, strand_indices=[i for i, _ in strand])
    for (left_id, left), (index, note), (right_id, right) in zip(
        strand, strand[1:], strand[2:]
    ):
        if (
            note.duration > 1
            or left.end > note.start + 1e-7
            or note.end > right.start + 1e-7
            or note.start - left.start > 2
            or right.start - note.start > 2
        ):
            continue
        before, after = note.pitch - left.pitch, right.pitch - note.pitch
        if abs(before) not in (1, 2) or abs(after) not in (1, 2):
            continue
        kind = (
            "neighbor"
            if left.pitch == right.pitch
            else "passing"
            if before * after > 0
            else None
        )
        if kind:
            result["ornaments"].append(
                {
                    "index": index,
                    "kind": kind,
                    "left_index": left_id,
                    "right_index": right_id,
                }
            )
    return result
