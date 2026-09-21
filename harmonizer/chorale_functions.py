"""Conservative source evidence for dominant-to-root connections.

Only an actual bass fourth plus an inner leading tone resolving up a semitone
is recorded. This imposes no tonic ending on an arbitrary target excerpt.
"""


def dominant_links(donor):
    notes = donor["notes"]
    links = []
    for time in sorted({a for _, a, _, _ in notes if a > 0}):
        before = [
            (i, p, role)
            for i, (p, a, b, role) in enumerate(notes)
            if a <= time - 1e-6 < b
        ]
        after = [
            (i, p, role)
            for i, (p, a, b, role) in enumerate(notes)
            if a <= time + 1e-7 < b
        ]
        if not before or not after:
            continue
        old_bass = min(before, key=lambda n: n[1])
        new_bass = min(after, key=lambda n: n[1])
        if (new_bass[1] - old_bass[1]) % 12 != 5:
            continue
        for old in before:
            if old[2] == "bass" or (old[1] - old_bass[1]) % 12 != 4:
                continue
            resolutions = [
                n
                for n in after
                if n[2] == old[2]
                and n[1] == old[1] + 1
                and n[1] % 12 == new_bass[1] % 12
            ]
            if len(resolutions) == 1:
                links.append(
                    {
                        "time": time,
                        "bass_before": old_bass[0],
                        "bass_after": new_bass[0],
                        "leading": old[0],
                        "resolution": resolutions[0][0],
                    }
                )
    return links


def preserves_links(events, links, start, end):
    for link in links:
        time = link["time"]
        if not start < time < end:
            continue
        pitches = {}
        for name, at in (
            ("bass_before", time - 1e-6),
            ("leading", time - 1e-6),
            ("bass_after", time + 1e-7),
            ("resolution", time + 1e-7),
        ):
            pitch = next(
                (
                    n.pitch
                    for i, n in events
                    if i == link[name] and n.start <= at < n.end
                ),
                None,
            )
            if pitch is None:
                return False
            pitches[name] = pitch
        if (
            (pitches["bass_after"] - pitches["bass_before"]) % 12 != 5
            or (pitches["leading"] - pitches["bass_before"]) % 12 != 4
            or pitches["resolution"] - pitches["leading"] != 1
            or pitches["resolution"] % 12 != pitches["bass_after"] % 12
        ):
            return False
    return True
