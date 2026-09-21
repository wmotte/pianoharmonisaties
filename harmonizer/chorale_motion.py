"""Preserve motion in unambiguous monophonic source-role connections."""


def source_motion_pairs(donor, *, extended=False):
    notes = donor["notes"]
    result = []
    for time in sorted({s for _, s, _, _ in notes}):
        for role in {r for _, _, _, r in notes}:
            before = [
                (i, p, e)
                for i, (p, s, e, r) in enumerate(notes)
                if r == role and s < time and e >= time
            ]
            after = [
                (i, p, s)
                for i, (p, s, e, r) in enumerate(notes)
                if r == role and s <= time < e
            ]
            if len(before) != 1 or len(after) != 1:
                continue
            a, b = before[0], after[0]
            if a[2] == time and b[2] == time and a[1] != b[1]:
                result.append((a[0], b[0]))
    if extended:
        result.extend(
            (row["left"], row["right"]) for row in extended_motion_evidence(donor)
        )
    return sorted(set(result))


def extended_motion_evidence(donor):
    """Trace held-anchor ordering and the unique sounding bass envelope.

    Bass links describe the lowest source note, not an inferred tenor/alto
    assignment. Upper chord connections without held anchors stay unresolved.
    """
    notes = donor["notes"]
    evidence = []
    for time in sorted({s for _, s, _, _ in notes}):
        before = sorted((p, i) for i, (p, s, e, _) in enumerate(notes) if s < time <= e)
        after = sorted((p, i) for i, (p, s, e, _) in enumerate(notes) if s <= time < e)
        if before and after:
            left, right = before[0][1], after[0][1]
            unique = (len(before) == 1 or before[1][0] != before[0][0]) and (
                len(after) == 1 or after[1][0] != after[0][0]
            )
            if (
                unique
                and notes[left][3] == notes[right][3] == "bass"
                and notes[left][2] == time
                and notes[right][1] == time
                and notes[left][0] != notes[right][0]
            ):
                evidence.append(
                    {
                        "left": left,
                        "right": right,
                        "time": time,
                        "kind": "bass_envelope",
                    }
                )
        for role in {n[3] for n in notes}:
            old = [(p, i) for p, i in before if notes[i][3] == role]
            new = [(p, i) for p, i in after if notes[i][3] == role]
            if len(old) < 2 or len(old) != len(new):
                continue
            if len({p for p, _ in old}) != len(old) or len({p for p, _ in new}) != len(
                new
            ):
                continue
            held = {i for _, i in old} & {i for _, i in new}
            if not held or any(
                a != b for (_, a), (_, b) in zip(old, new) if a in held or b in held
            ):
                continue
            for (p, left), (q, right) in zip(old, new):
                if p != q and notes[left][2] == time and notes[right][1] == time:
                    evidence.append(
                        {
                            "left": left,
                            "right": right,
                            "time": time,
                            "kind": "held_anchor",
                            "anchors": sorted(held),
                        }
                    )
    return evidence


def has_collapsed_motion(events, pairs):
    """Check identities, including source notes split at decoder boundaries."""
    by_id = {}
    for identity, note in events:
        by_id.setdefault(identity, []).append(note)
    return any(
        before.pitch == after.pitch and abs(before.end - after.start) < 1e-7
        for left, right in pairs
        for before in by_id.get(left, [])
        for after in by_id.get(right, [])
    )


def has_displaced_anchor(events, evidence, source_notes):
    """Keep mapped bass identities lowest and held-anchor order intact."""
    for row in evidence:
        time = row["time"]
        before = {i: n for i, n in events if n.start < time <= n.end}
        after = {i: n for i, n in events if n.start <= time < n.end}
        left, right = row["left"], row["right"]
        if left not in before or right not in after:
            continue
        if row["kind"] == "bass_envelope":
            if before[left].pitch != min(n.pitch for n in before.values()) or after[
                right
            ].pitch != min(n.pitch for n in after.values()):
                return True
        else:
            for anchor in row["anchors"]:
                if anchor not in before or anchor not in after:
                    continue
                if before[anchor].pitch != after[anchor].pitch:
                    return True
                for identity, current in ((left, before), (right, after)):
                    old = source_notes[identity][0] - source_notes[anchor][0]
                    new = current[identity].pitch - current[anchor].pitch
                    if old * new <= 0:
                        return True
    return False


def has_distorted_contour(events, pairs, source_notes):
    """Require the source direction and do not enlarge its interval band.

    Bands are at most 2, 4, 7 or 12 semitones. Larger source intervals may
    shrink but cannot grow. This is an optional adaptation constraint, not
    a claim that a different contour is inherently unmusical.
    """
    by_id = {}
    for identity, note in events:
        by_id.setdefault(identity, []).append(note)
    for left, right in pairs:
        original = source_notes[right][0] - source_notes[left][0]
        limit = next((n for n in (2, 4, 7, 12) if abs(original) <= n), abs(original))
        for before in by_id.get(left, []):
            for after in by_id.get(right, []):
                if abs(before.end - after.start) >= 1e-7:
                    continue
                changed = after.pitch - before.pitch
                if original * changed <= 0 or abs(changed) > limit:
                    return True
    return False


def bass_motion_pairs(source_notes, pairs):
    """Select pairs belonging to the uniquely lowest sounding source notes."""
    selected = []
    for left, right in pairs:
        time = source_notes[right][1]
        if abs(source_notes[left][2] - time) > 1e-7:
            continue
        before = [
            (p, i) for i, (p, a, b, _) in enumerate(source_notes) if a < time <= b
        ]
        after = [(p, i) for i, (p, a, b, _) in enumerate(source_notes) if a <= time < b]
        if not before or not after:
            continue
        low_before = [i for p, i in before if p == min(x[0] for x in before)]
        low_after = [i for p, i in after if p == min(x[0] for x in after)]
        if low_before == [left] and low_after == [right]:
            selected.append((left, right))
    return selected
