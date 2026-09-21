"""Observed harmonic pairs across independently supplied phrase boundaries."""

from collections import Counter, defaultdict
from copy import deepcopy

from .chorale_continuity import gap_boundary


def boundary_key(melody, previous, following, before, after, *, timing="exact"):
    """Keep mode, melodic direction, relative timing, harmony and inversion.

    Register and uniform tempo scaling may differ. Incomplete observed chords
    stay incomplete; no root inference or missing fifth is introduced.
    """
    if timing not in ("exact", "harmonic"):
        raise ValueError("Boundary timing must be exact or harmonic")
    if not before or not after or previous.end > following.start + 1e-7:
        return None
    if not gap_boundary(melody, previous.end, following.start)[0]:
        return None
    if max(before) >= previous.pitch or max(after) >= following.pitch:
        return None
    relative = lambda pitch: (pitch - melody.tonic) % 12
    fields = (
        melody.mode,
        relative(previous.pitch),
        following.pitch - previous.pitch,
        round((following.start - previous.end) / previous.duration, 7),
        round(following.duration / previous.duration, 7),
        tuple(sorted({relative(previous.pitch), *(relative(p) for p in before)})),
        relative(min(before)),
        tuple(sorted({relative(following.pitch), *(relative(p) for p in after)})),
        relative(min(after)),
    )
    if timing == "harmonic":
        # Harmonic evidence does not prescribe note lengths. Still distinguish
        # a breathing space from a connected melodic phrase boundary.
        fields = fields[:3] + (following.start - previous.end > 1e-7,) + fields[5:]
    return repr(fields)


def fit_boundary_links(model, references):
    """Refit only from disclosed sources, counting distinct source recordings."""
    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError(
            "Boundary-link references must match model training identities"
        )
    recordings = defaultdict(set)
    evidence = []
    for entry, melody, arrangement in references:
        for previous, following in zip(melody.notes, melody.notes[1:]):
            before = sorted(
                n.pitch
                for n in arrangement.notes
                if n.role != "melody" and n.start <= previous.end - 1e-6 < n.end
            )
            after = sorted(
                n.pitch
                for n in arrangement.notes
                if n.role != "melody" and n.start <= following.start + 1e-7 < n.end
            )
            key = boundary_key(
                melody,
                previous,
                following,
                before,
                after,
                timing=model.get("phrase_boundary_timing", "exact"),
            )
            if key is None:
                continue
            recording = entry.get("recording_id") or entry.get("source_sha256")
            if not recording:
                raise ValueError("Boundary links need disclosed recording provenance")
            recordings[key].add(recording)
            evidence.append(
                {
                    "key": key,
                    "source_id": entry["source_id"],
                    "group": entry["group"],
                    "recording": recording,
                    "source_origin": entry.get("source_start_quarters", 0),
                    "release": previous.end,
                    "following_start": following.start,
                    "before": before,
                    "after": after,
                    "status": "observed_pair_not_a_complete_phrase_plan",
                }
            )
    result = deepcopy(model)
    result["phrase_boundary_links"] = {k: len(v) for k, v in sorted(recordings.items())}
    result["phrase_boundary_link_evidence"] = evidence
    return result


def boundary_support(model, melody, previous, following, before, after):
    if previous is None or not model.get("phrase_boundary_links"):
        return 0
    key = boundary_key(
        melody,
        previous,
        following,
        before,
        after,
        timing=model.get("phrase_boundary_timing", "exact"),
    )
    return model["phrase_boundary_links"].get(key, 0)
