"""Conservative evidence for resolution of close upper-voice seconds.

This audit does not classify every second as a harmonic error. It only tests
whether an unambiguous inner voice steps to consonant outer-voice intervals.
"""

from itertools import pairwise


def upper_second_resolutions(notes, *, deadline=1.5):
    if deadline <= 0:
        raise ValueError("Resolution deadline must be positive")
    times = sorted({t for n in notes for t in (n.start, n.end)})
    episodes = []
    for start, end in pairwise(times):
        active = [i for i, n in enumerate(notes) if n.start <= start < n.end]
        inner = [i for i in active if notes[i].role == "inner"]
        top = [i for i in active if notes[i].role == "melody"]
        if len(inner) != 1 or len(top) != 1:
            continue
        i, j = inner[0], top[0]
        if not 0 < notes[j].pitch - notes[i].pitch <= 2:
            continue
        if (
            episodes
            and episodes[-1]["end"] == start
            and episodes[-1]["indices"] == (i, j)
        ):
            episodes[-1]["end"] = end
        else:
            episodes.append({"start": start, "end": end, "indices": (i, j)})
    result = []
    for episode in episodes:
        i, j = episode["indices"]
        note = notes[i]
        t = note.end
        row = dict(
            episode,
            inner_pitch=note.pitch,
            melody_pitch=notes[j].pitch,
            expires_at=episode["start"] + deadline,
        )
        # A held inner note need not move when the melody resolves the clash.
        # Assess the actual end of the dissonant episode before waiting for
        # the (possibly much later) release of that inner note.
        episode_end = episode["end"]
        next_top = [
            n for n in notes if n.role == "melody" and n.start <= episode_end < n.end
        ]
        if (
            note.end > episode_end
            and len(next_top) == 1
            and next_top[0].pitch != notes[j].pitch
        ):
            row["resolution_voice"] = "melody"
            row["target_pitch"] = next_top[0].pitch
            stop = min(note.end, next_top[0].end)
            checks = []
            for a, _ in pairwise(
                sorted(
                    {episode_end, stop, *(x for x in times if episode_end < x < stop)}
                )
            ):
                inner = [n for n in notes if n.role == "inner" and n.start <= a < n.end]
                bass = [
                    n.pitch
                    for n in notes
                    if n.role not in ("inner", "melody") and n.start <= a < n.end
                ]
                if len(inner) != 1 or not bass:
                    checks.append("context_missing")
                elif not min(bass) < note.pitch < next_top[0].pitch:
                    checks.append("crossing_or_unison")
                elif (next_top[0].pitch - note.pitch) % 12 not in (3, 4, 7, 8, 9) or (
                    note.pitch - min(bass)
                ) % 12 not in (0, 3, 4, 7, 8, 9):
                    checks.append("tension_remains")
                else:
                    checks.append("consonant")
            row["following_context"] = checks
            row["resolution_span"] = [episode_end, stop]
            row["status"] = (
                "deadline_missed"
                if episode_end > row["expires_at"] + 1e-7
                else "melody_changed_without_confirmed_step_resolution"
                if abs(next_top[0].pitch - notes[j].pitch) not in (1, 2)
                else "confirmed_melody_step_resolution"
                if checks and set(checks) == {"consonant"}
                else "unclassified_context"
                if "context_missing" in checks
                else "no_confirmed_resolution"
            )
            result.append(row)
            continue
        following = [n for n in notes if n.role == "inner" and n.start <= t < n.end]
        preceding = [n for n in notes if n.role == "inner" and n.start < t <= n.end]
        if len(following) != 1 or len(preceding) != 1 or following[0].start != t:
            row["status"] = "unclassified_continuation"
        elif t > row["expires_at"] + 1e-7:
            row["status"] = "deadline_missed"
        elif not 0 < abs(following[0].pitch - note.pitch) <= 2:
            row["status"] = "not_a_step"
        else:
            nxt = following[0]
            row["target_pitch"] = nxt.pitch
            # Check the entire following note, including outer-voice changes.
            checks = []
            for a, b in pairwise(
                sorted({t, nxt.end, *(x for x in times if t < x < nxt.end)})
            ):
                top = [
                    n.pitch
                    for n in notes
                    if n.role == "melody" and n.start <= a < n.end
                ]
                bass = [
                    n.pitch
                    for n in notes
                    if n.role not in ("melody", "inner") and n.start <= a < n.end
                ]
                if len(top) != 1 or not bass:
                    checks.append("context_missing")
                elif not min(bass) < nxt.pitch < top[0]:
                    checks.append("crossing_or_unison")
                elif (top[0] - nxt.pitch) % 12 not in (3, 4, 7, 8, 9) or (
                    nxt.pitch - min(bass)
                ) % 12 not in (0, 3, 4, 7, 8, 9):
                    checks.append("tension_remains")
                else:
                    checks.append("consonant")
            row["following_context"] = checks
            row["status"] = (
                "confirmed_step_resolution"
                if checks and set(checks) == {"consonant"}
                else "unclassified_context"
                if "context_missing" in checks
                else "no_confirmed_resolution"
            )
        result.append(row)
    return result
