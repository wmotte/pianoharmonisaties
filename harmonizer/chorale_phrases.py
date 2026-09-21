"""Harmonic completion and ordered inner-voice connections for chorale phrases."""

import math
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
from itertools import combinations, pairwise
from statistics import median
from types import SimpleNamespace

from .chorale_model import _hand_split, snapshots
from .model import MODES, Event
from .profile import identify_chord

CHORDS = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "dim": (0, 3, 6),
    "dom7": (0, 4, 7, 10),
    "min7": (0, 3, 7, 10),
    "maj7": (0, 4, 7, 11),
}


def fit_phrases(model, references):
    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError("Phrase training must use exactly the disclosed training IDs.")
    counts = defaultdict(Counter)
    patterns = Counter()
    profiles = []
    pattern_evidence = []
    for entry, melody, arrangement in references:
        rows = list(snapshots(arrangement, melody))
        evidence = []
        patterns.update(
            measure_patterns(
                melody, arrangement, stable_harmony=True, evidence=evidence
            )
        )
        pattern_evidence.extend(
            dict(
                row,
                source_id=entry["source_id"],
                group=entry.get("group"),
                source_sha256=entry.get("source_sha256"),
            )
            for row in evidence
        )
        for _, ps in rows:
            chord = identify_chord(ps)
            if chord and chord[1] in CHORDS:
                counts[melody.mode][f"{(chord[0] - melody.tonic) % 12}:{chord[1]}"] += 1
        profiles.append(
            {
                "source_id": entry["source_id"],
                "mode": melody.mode,
                "melody_register": median(n.pitch for n in melody.notes),
                "bass_gap": median(n.pitch - ps[0] for n, ps in rows),
            }
        )
    result = deepcopy(model)
    result.update(
        decoder="phrase_harmony_v1",
        phrase_chords={k: dict(v) for k, v in counts.items()},
        register_profiles=profiles,
        status="experimental_phrase_candidate",
        sustain_common_inner=True,
        bar_pattern_evidence=pattern_evidence,
        bar_patterns=[
            {"meter": [n, d], "events": list(events), "count": count}
            for (n, d, events), count in sorted(patterns.items())
        ],
    )
    if "harmonic_window_transitions" in model:
        result = fit_harmonic_transitions(result, references)
    return result


def pattern_harmony(arrangement, start, end):
    """Conservative evidence for one chord, never a pooled seventh alone.

    A union of two successive triads can look like a seventh chord. Reject
    conflicting identifiable vertical harmonies even if the union fits.
    Passing notes may cause abstention. They are not declared musical errors.
    """
    notes = [n for n in arrangement.notes if n.start < end and n.end > start]
    pcs = {n.pitch % 12 for n in notes}
    compatible = [
        (root, quality)
        for root in range(12)
        for quality, intervals in CHORDS.items()
        if pcs == {(root + p) % 12 for p in intervals}
    ]
    labels = set()
    for t in {start, *(n.start for n in notes if n.start >= start)}:
        label = identify_chord([n.pitch for n in notes if n.start <= t + 1e-7 < n.end])
        if label:
            labels.add(label)
    if len(labels) > 1:
        status = "changing_harmony"
    elif len(compatible) == 1 and (not labels or labels == set(compatible)):
        status = "single_chord_evidence"
    else:
        status = "unresolved"
    return {
        "status": status,
        "pooled_chords": compatible,
        "vertical_chords": sorted(labels),
    }


def harmonic_window_label(arrangement, start, end, tonic):
    """Label one supported harmonic window, including compatible broken chords."""
    evidence = pattern_harmony(arrangement, start, end)
    if evidence["status"] != "single_chord_evidence":
        return ""
    root, quality = evidence["pooled_chords"][0]
    return f"{(root - tonic) % 12}:{quality}"


def fit_harmonic_transitions(model, references):
    """Opt into equal harmonic observations in training and gesture decoding.

    Existing models retain their onset-trained transition table. Unknown or
    changing windows interrupt a transition, as do rests and phrase boundaries.
    This evidence policy does not certify the generated music's style.
    """
    references = list(references)
    if Counter(e["source_id"] for e, _, _ in references) != Counter(
        model["training_ids"]
    ):
        raise ValueError(
            "Transition training must use exactly the disclosed training IDs."
        )
    counts = Counter()
    windows = known = 0
    for _, melody, arrangement in references:
        previous, previous_note = "", None
        for note in melody.notes:
            current = harmonic_window_label(
                arrangement, note.start, note.end, melody.tonic
            )
            windows += 1
            known += bool(current)
            if (
                previous
                and current
                and previous_note is not None
                and abs(previous_note.end - note.start) < 1e-6
                and note.start not in melody.phrases
            ):
                counts[previous + ">" + current] += 1
            previous, previous_note = current, note
    result = deepcopy(model)
    result["harmonic_window_transitions"] = dict(counts)
    result["harmonic_window_evidence"] = {
        "policy": "single_chord_evidence_over_melody_note_window",
        "windows": windows,
        "supported_windows": known,
        "transitions": sum(counts.values()),
    }
    return result


@lru_cache(maxsize=65536)
def gesture_harmonic_window(events, top, tonic):
    """Apply the training observation to a normalized accompaniment gesture."""
    notes = [Event(top, 0, 1)] + [
        Event(top - offset, max(0, a), min(1, b) - max(0, a))
        for offset, a, b, _ in events
        if a < 1 and b > 0
    ]
    return harmonic_window_label(SimpleNamespace(notes=notes), 0, 1, tonic)


def measure_patterns(melody, arrangement, *, stable_harmony=False, evidence=None):
    """Learn complete, regular bass figures without source pitches or tune IDs."""
    found = []
    melody_start = min((note.start for note in melody.notes), default=math.inf)
    melody_end = max((note.end for note in melody.notes), default=-math.inf)
    for i, (offset, n, d) in enumerate(melody.meters):
        limit = melody.meters[i + 1][0] if i + 1 < len(melody.meters) else melody.length
        length = n * 4 / d
        start = offset
        while start + length <= limit + 1e-6:
            attacks = []
            for x in arrangement.notes:
                if (
                    x.role == "melody"
                    or not start - 1e-6 <= x.start < start + length - 1e-6
                ):
                    continue
                active = [
                    y.pitch
                    for y in arrangement.notes
                    if y.start <= x.start + 1e-7 < y.end
                ]
                if x.pitch == min(active):
                    attacks.append((round(x.start - start, 6), x.pitch))
            attacks = sorted(set(attacks))
            if (
                2 <= len(attacks) <= 4
                and attacks[0][0] == 0
                and all(b[0] - a[0] >= 0.5 for a, b in pairwise(attacks))
                and len({p for _, p in attacks}) >= 2
            ):
                base = attacks[0][1]
                shape = tuple((t, p - base) for t, p in attacks)
                if all(0 <= delta <= 12 for _, delta in shape):
                    check = pattern_harmony(arrangement, start, start + length)
                    inside_melody = (
                        start >= melody_start - 1e-6
                        and start + length <= melody_end + 1e-6
                    )
                    if not inside_melody:
                        check["status"] = "outside_annotated_melody_span"
                    if evidence is not None:
                        evidence.append(
                            dict(
                                check,
                                start=start,
                                end=start + length,
                                meter=[n, d],
                                events=shape,
                            )
                        )
                    if inside_melody and (
                        not stable_harmony or check["status"] == "single_chord_evidence"
                    ):
                        found.append((n, d, shape))
            start += length
    return found


def patterned_voicing(n, melody, ps, pcs, model):
    from .chorale_gestures import _playable

    offset, numerator, denominator = next(
        m for m in reversed(melody.meters) if m[0] <= n.start + 1e-7
    )
    length = numerator * 4 / denominator
    continuous_patterns = model.get("continuous_bar_patterns", False)
    if n.duration < 1.5 and not continuous_patterns:
        return []
    choices = []
    for pattern_index, pattern in enumerate(model.get("bar_patterns", [])):
        if pattern["meter"] != [numerator, denominator]:
            continue
        shape = pattern["events"]
        if any(
            (ps[0] + delta) % 12 not in pcs or ps[0] + delta >= ps[1]
            for _, delta in shape
        ):
            continue
        first_bar = offset + math.floor((n.start - offset) / length) * length
        attacks = []
        bar = first_bar
        while bar < n.end - 1e-7:
            attacks.extend((bar + t, ps[0] + delta) for t, delta in shape)
            bar += length
        attacks.append((n.end, None))
        events = [(n.pitch - p, 0, 1, False) for p in ps[1:]]
        for (start, pitch), (end, _) in pairwise(attacks):
            a, b = max(n.start, start), min(n.end, end)
            if a < b - 1e-7:
                events.append(
                    (
                        n.pitch - pitch,
                        (a - n.start) / n.duration,
                        (b - n.start) / n.duration,
                        start < n.start,
                    )
                )
        if (
            not continuous_patterns and len({a for _, a, _, _ in events}) < 2
        ) or not _playable(events, n.pitch):
            continue
        # Preserve the legacy preference for reproducible archived models.
        # Disabling the bonus keeps the same figures available, at the same
        # base cost as a sustained voicing. A single observed figure does not
        # establish how often it should replace sustained accompaniment.
        discount = 0.0
        if model.get("pattern_bonus", True):
            discount = 0.55 + min(0.25, 0.12 * math.log1p(pattern["count"]))
            if model.get("pattern_prior_per_bar"):
                discount *= n.duration / length
        choices.append(
            (
                events,
                discount,
                -10 - pattern_index,
            )
        )
    return choices


def register_gap(melody, model):
    register = median(n.pitch for n in melody.notes)
    pool = [p for p in model["register_profiles"] if p["mode"] == melody.mode]
    pool = sorted(pool, key=lambda p: abs(p["melody_register"] - register))[:3]
    return median(p["bass_gap"] for p in pool) if pool else model["bass_gap"]


@lru_cache(maxsize=8192)
def ordered_motion(before, after):
    """Order-preserving edit distance. One voice cannot explain several arrivals."""
    previous = [i * 3.0 for i in range(len(after) + 1)]
    for i, p in enumerate(before, 1):
        current = [i * 3.0]
        for j, q in enumerate(after, 1):
            current.append(
                min(
                    previous[j - 1] + min(12, abs(p - q)),
                    previous[j] + 3,
                    current[j - 1] + 3,
                )
            )
        previous = current
    return previous[-1]


def family(events):
    return "moving" if any(a > 0 for _, a, _, _ in events) else "held"


def _label(events, top, tonic):
    chord = identify_chord([top, *{top - offset for offset, _, _, _ in events}])
    return f"{(chord[0] - tonic) % 12}:{chord[1]}" if chord else ""


@lru_cache(maxsize=4096)
def _voicings(top, root, quality, gap):
    pcs = {(root + i) % 12 for i in CHORDS[quality]}
    if top % 12 not in pcs:
        return ()
    result = []
    for bass in range(max(28, top - int(gap) - 7), min(top - 7, top - int(gap) + 8)):
        if bass % 12 not in pcs:
            continue
        upper = [p for p in range(max(bass + 3, top - 17), top) if p % 12 in pcs]
        for count in (1, 2):
            for inner in combinations(upper, count):
                ps = (bass, *inner)
                if {top % 12, *(p % 12 for p in ps)} != pcs or _hand_split(
                    ps, top
                ) is None:
                    continue
                cost = 0.035 * abs(top - bass - gap) + 0.08 * (bass % 12 != root)
                upper_line = (*inner, top)
                cost += 0.025 * sum(max(0, b - a - 7) for a, b in pairwise(upper_line))
                result.append((ps, cost))
    return tuple(sorted(result, key=lambda x: x[1])[:24])


def harmonic_vocabulary(mode, model):
    vocabulary = dict(model["phrase_chords"].get(mode, {}))
    if model.get("diatonic_vocabulary"):
        scale = MODES[mode]
        for i, root in enumerate(scale):
            intervals = {
                0,
                (scale[(i + 2) % 7] - root) % 12,
                (scale[(i + 4) % 7] - root) % 12,
            }
            quality = next(
                (q for q in ("major", "minor", "dim") if set(CHORDS[q]) == intervals),
                None,
            )
            if quality is not None:
                # Zero observations: the existing add-one prior supplies the
                # fallback probability without inventing source occurrences.
                vocabulary.setdefault(f"{root}:{quality}", 0)
    return vocabulary


def options(n, melody, model, base, gap):
    from .chorale_gestures import beat_class

    strong = beat_class(melody, n.start) != "offbeat" or n.duration >= 1.5
    scale = {(melody.tonic + x) % 12 for x in MODES[melody.mode]}
    vocabulary = harmonic_vocabulary(melody.mode, model)
    total = sum(vocabulary.values())
    result = []
    for events, cost, identity in base:
        original_cost = cost
        sounding = {
            n.pitch % 12,
            *{(n.pitch - offset) % 12 for offset, _, _, _ in events},
        }
        # Broken chords can provide their harmonic support across time.
        cost += (0.8 if strong else 0.35) * max(0, 3 - len(sounding))
        if not _label(events, n.pitch, melody.tonic):
            cost += 0.25 if strong else 0
        result.append((events, cost, identity))
        # Complete a partial recorded figure before replacing it with a generic
        # block voicing. Existing bass attacks and inner movements stay intact.
        for label, count in vocabulary.items():
            degree, quality = label.split(":")
            root = (melody.tonic + int(degree)) % 12
            pcs = {(root + i) % 12 for i in CHORDS[quality]}
            missing = pcs - sounding
            if not sounding <= pcs or len(missing) != 1:
                continue
            for pitch in range(max(28, n.pitch - 16), n.pitch):
                if pitch % 12 not in missing:
                    continue
                completed = [*events, (n.pitch - pitch, 0, 1, False)]
                from .chorale_gestures import _playable

                if not _playable(completed, n.pitch):
                    continue
                prior = -0.1 * math.log((count + 1) / (total + len(vocabulary)))
                extra = 0.18 + prior + 0.4 * (pitch % 12 not in scale)
                result.append((completed, original_cost + extra, identity))
    for label, count in vocabulary.items():
        degree, quality = label.split(":")
        root = (melody.tonic + int(degree)) % 12
        for ps, layout_cost in _voicings(n.pitch, root, quality, round(gap)):
            prior = -0.2 * math.log((count + 1) / (total + len(vocabulary)))
            cost = (
                1.1 + prior + layout_cost + 0.4 * sum(p % 12 not in scale for p in ps)
            )
            cost += 0.15 * abs(len(ps) + 1 - (4 if strong else 3))
            result.append(([(n.pitch - p, 0, 1, False) for p in ps], cost, -2))
            pcs = {(root + i) % 12 for i in CHORDS[quality]}
            for patterned, discount, pattern_id in patterned_voicing(
                n, melody, ps, pcs, model
            ):
                result.append((patterned, cost - discount, pattern_id))
    groups = defaultdict(list)
    for choice in sorted(result, key=lambda x: x[1]):
        key = (_label(choice[0], n.pitch, melody.tonic), family(choice[0]))
        if len(groups[key]) < 6:
            groups[key].append(choice)
    choices = sorted(
        [x for group in groups.values() for x in group], key=lambda x: x[1]
    )[:64]
    if model.get("bass_activity_prior"):
        from .chorale_bass_plan import activity_options

        choices = activity_options(n, melody, model, choices)
    return choices


def connection(before, after, previous_events, events, top, previous_top, tonic, model):
    cost = 0.075 * ordered_motion(tuple(before[1:]), tuple(after[1:]))
    cost += 0.22 * (family(previous_events) != family(events))
    if family(previous_events) == family(events) == "moving":
        old_rhythm = sorted(
            {(round(a, 6), round(b, 6)) for _, a, b, _ in previous_events}
        )
        new_rhythm = sorted({(round(a, 6), round(b, 6)) for _, a, b, _ in events})
        cost += 0.12 * (old_rhythm != new_rhythm)
    if "harmonic_window_transitions" in model:
        first = gesture_harmonic_window(
            tuple(map(tuple, previous_events)), previous_top, tonic
        )
        second = gesture_harmonic_window(tuple(map(tuple, events)), top, tonic)
        transitions = model["harmonic_window_transitions"]
    else:
        first = _label(previous_events, previous_top, tonic)
        second = _label(events, top, tonic)
        transitions = model["transitions"]
    if first and second:
        cost -= 0.2 * math.log1p(transitions.get(first + ">" + second, 0))
    return cost


def phrase_bass_connection(before, after, previous, current):
    """A phrase label does not erase motion between contiguous sounding notes."""
    if not before or not after or abs(previous.end - current.start) > 1e-6:
        return 0.0
    movement = abs(after[0] - before[0])
    old_interval = (previous.pitch - before[0]) % 12
    if movement > 12 or (
        old_interval in (0, 7)
        and (current.pitch - after[0]) % 12 == old_interval
        and (current.pitch - previous.pitch) * (after[0] - before[0]) > 0
    ):
        return math.inf
    return 0.065 * movement + 0.12 * max(0, movement - 7)


def phrase_checks(arrangement, melody):
    rows = list(snapshots(arrangement, melody))
    chords = [identify_chord(ps) for _, ps in rows]
    rhythms = [
        any(
            x.role != "melody" and n.start + 1e-6 < x.start < n.end - 1e-6
            for x in arrangement.notes
        )
        for n, _ in rows
    ]
    continuous = [
        i
        for i in range(1, len(rows))
        if abs(rows[i - 1][0].end - rows[i][0].start) < 1e-6
        and rows[i][0].start not in melody.phrases
    ]
    return {
        "mean_sounding_notes_at_melody_attack": sum(len(ps) for _, ps in rows)
        / len(rows),
        "identified_chord_fraction": sum(c is not None for c in chords) / len(rows),
        "inner_voice_count_changes": sum(
            len(rows[i - 1][1]) != len(rows[i][1]) for i in continuous
        ),
        "texture_switches": sum(rhythms[i - 1] != rhythms[i] for i in continuous),
    }
