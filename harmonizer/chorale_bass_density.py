"""Measure sounding bass register separately from attack and chord density."""

from collections import defaultdict
from itertools import pairwise


def bass_density(notes, start, end):
    """Profile accompaniment, including melody rests. C4 is MIDI 60.

    Bass means the lowest sounding accompaniment pitch, not a hand label.
    An exposed sustained note is not a new attack. Histogram weights are
    quarter-note durations, so tempo does not change the register estimate.
    """
    if end <= start:
        raise ValueError("A positive observation interval is required")
    notes = [n for n in notes if n.role != "melody" and n.start < end and n.end > start]
    times = sorted({start, end, *(max(start, n.start) for n in notes),
                    *(min(end, n.end) for n in notes)})
    duration = defaultdict(float)
    attacks = defaultdict(int)
    low_note_time = low_polyphony_time = octave_time = 0.0
    for a, b in pairwise(times):
        active = [n for n in notes if n.start <= a < n.end]
        if not active:
            continue
        bass = min(n.pitch for n in active)
        duration[bass] += b - a
        low = {n.pitch for n in active if n.pitch < 48}
        low_note_time += len(low) * (b - a)
        low_polyphony_time += (len(low) >= 2) * (b - a)
        octave_time += (bass + 12 in {n.pitch for n in active}) * (b - a)
        if any(n.pitch == bass and n.start == a for n in active):
            attacks[bass] += 1
    sounding = sum(duration.values())
    total_attacks = sum(attacks.values())
    def quantile(q):
        cumulative = 0.0
        for pitch, weight in sorted(duration.items()):
            cumulative += weight
            if cumulative >= q * sounding:
                return pitch
        return None
    return {
        "length_quarters": end - start,
        "bass_sounding_quarters": sounding,
        "bass_pitch_quarters": dict(sorted(duration.items())),
        "bass_attack_counts": dict(sorted(attacks.items())),
        "bass_attacks_per_quarter": total_attacks / (end - start),
        "bass_quantiles_midi": [quantile(q) for q in (.1, .5, .9)],
        "bass_below_fractions": {
            str(cut): sum(v for p, v in duration.items() if p < cut) / sounding
            if sounding else None for cut in (36, 40, 48)
        },
        "low_note_quarters_per_quarter": low_note_time / (end - start),
        "multiple_notes_below_c3_time_fraction": low_polyphony_time / (end - start),
        "bass_octave_doubling_sounding_fraction": octave_time / sounding if sounding else None,
    }
