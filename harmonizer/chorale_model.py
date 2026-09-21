"""Chorale-only empirical voicing model with versioned, auditable adaptation."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import replace
from functools import lru_cache
from itertools import pairwise

import numpy as np

from .engine import Arrangement, Harmony, accompaniment, harmonize
from .model import MODES, Event
from .profile import identify_chord

FEATURE_SCALES = {
    "density": 0.5,
    "density_spread": 0.35,
    "bass_gap": 4,
    "inner_gap": 3,
    "bass_motion": 2,
    "common_tones": 0.15,
    "accompaniment_attacks": 0.4,
    "bass_attacks": 0.25,
    "root_position": 0.15,
    "chromatic": 0.08,
    "sevenths": 0.12,
    "suspensions": 0.12,
    "parallel_perfects": 0.12,
}


def snapshots(arrangement, melody):
    for n in melody.notes:
        pitches = sorted(
            {
                x.pitch
                for x in arrangement.notes
                if x.start <= n.start + 1e-7
                and x.end > n.start + 1e-7
                and x.pitch <= n.pitch
            }
        )
        if n.pitch not in pitches:
            raise ValueError("De vaste melodie ontbreekt op een aanslag.")
        yield n, pitches


def features(arrangement, melody):
    rows = list(snapshots(arrangement, melody))
    below = [[p for p in ps if p < n.pitch] for n, ps in rows]
    density = [len(ps) for _, ps in rows]
    bass = [ps[0] for _, ps in rows]
    motion = [abs(b - a) for a, b in pairwise(bass)]
    common = [
        len(set(a) & set(b)) / max(1, len(set(a) | set(b))) for a, b in pairwise(below)
    ]
    chords = [identify_chord(ps) for _, ps in rows]
    defined = [(ps, ch) for (_, ps), ch in zip(rows, chords) if ch]
    scale = {(melody.tonic + x) % 12 for x in MODES[melody.mode]}
    total = sum(len(ps) for ps in below)
    accompaniment_notes = [n for n in arrangement.notes if n.role != "melody"]
    parallels = 0
    for (na, pa), (nb, pb) in pairwise(rows):
        if len(pa) < 2 or len(pb) < 2:
            continue
        if (
            (na.pitch - pa[0]) % 12 in (0, 7)
            and (na.pitch - pa[0]) % 12 == (nb.pitch - pb[0]) % 12
            and (nb.pitch - na.pitch) * (pb[0] - pa[0]) > 0
        ):
            parallels += 1
    f = {
        "density": float(np.mean(density)),
        "density_spread": float(np.std(density)),
        "bass_gap": float(np.mean([n.pitch - ps[0] for n, ps in rows])),
        "inner_gap": float(np.mean([n.pitch - ps[-2] for n, ps in rows if len(ps) > 1]))
        if total
        else 0,
        "bass_motion": float(np.mean(motion)) if motion else 0,
        "common_tones": float(np.mean(common)) if common else 0,
        "accompaniment_attacks": len(accompaniment_notes) / max(1, len(melody.notes)),
        "bass_attacks": sum(
            n.pitch
            == min(
                x.pitch
                for x in arrangement.notes
                if x.start <= n.start + 1e-7 and x.end > n.start + 1e-7
            )
            for n in accompaniment_notes
        )
        / max(1, len(melody.notes)),
        "root_position": sum(ps[0] % 12 == ch[0] for ps, ch in defined)
        / max(1, len(defined)),
        "chromatic": sum(p % 12 not in scale for ps in below for p in ps)
        / max(1, total),
        "sevenths": sum(
            ch and ch[1] in ("dom7", "maj7", "min7") or False for ch in chords
        )
        / len(rows),
        "suspensions": sum(ch and ch[1] in ("sus2", "sus4") or False for ch in chords)
        / len(rows),
        "parallel_perfects": parallels / max(1, len(rows) - 1),
    }
    for degree in range(12):
        f[f"bass_degree_{degree}"] = sum(
            (p - melody.tonic) % 12 == degree for p in bass
        ) / len(bass)
    for count in range(1, 7):
        f[f"density_{count}"] = sum(min(6, x) == count for x in density) / len(density)
    return f


def feature_distance(a, b):
    return sum(min(5, abs(a[k] - b[k]) / FEATURE_SCALES.get(k, 0.15)) for k in a) / len(
        a
    )


def fit(references, revision=0, parameters=None):
    shapes = Counter()
    cadences = Counter()
    counts = Counter()
    transitions = Counter()
    motion = []
    gaps = []
    subdivisions = []
    for entry, melody, arrangement in references:
        previous = None
        previous_end = None
        for n, ps in snapshots(arrangement, melody):
            if previous_end is not None and (
                abs(n.start - previous_end) > 1e-6 or n.start in melody.phrases
            ):
                previous = None
            previous_end = n.end
            offsets = tuple(n.pitch - p for p in ps if p < n.pitch)
            if 1 <= len(offsets) <= 4:
                shapes[(melody.mode, (n.pitch - melody.tonic) % 12, offsets)] += 1
                if any(abs(n.end - f) < 1e-6 for f in melody.fermatas):
                    cadences[(melody.mode, (n.pitch - melody.tonic) % 12, offsets)] += 1
                gaps.append(max(offsets))
            chord = identify_chord(ps)
            if chord:
                label = f"{(chord[0] - melody.tonic) % 12}:{chord[1]}"
                counts[label] += 1
                if previous:
                    transitions[previous + ">" + label] += 1
                previous = label
            else:
                # Unknown harmony interrupts an observed transition. Joining
                # the surrounding chords would invent evidence across the gap.
                previous = None
            subdivisions.append(
                any(
                    x.role != "melody" and n.start + 0.001 < x.start < n.end - 0.001
                    for x in arrangement.notes
                )
            )
        motion.extend(
            abs(b[1][0] - a[1][0])
            for a, b in pairwise(list(snapshots(arrangement, melody)))
        )
    return {
        "schema_version": 1,
        "revision": revision,
        "status": "experimental_unreviewed",
        "training_ids": [e["source_id"] for e, _, _ in references],
        "training_groups": [e["group"] for e, _, _ in references],
        "templates": [
            {
                "mode": m,
                "degree": d,
                "offsets": list(o),
                "count": c,
                "cadence_count": cadences[(m, d, o)],
            }
            for (m, d, o), c in sorted(shapes.items())
        ],
        "chords": dict(counts),
        "transitions": dict(transitions),
        "bass_gap": float(np.mean(gaps)) if gaps else 24,
        "subdivision_rate": float(np.mean(subdivisions)) if subdivisions else 0,
        "parameters": parameters
        or {
            "texture_strength": 0.0,
            "movement_weight": 0.08,
            "hold_common": True,
            "subdivision_scale": 0.0,
        },
    }


def _layout(melody, notes, hs, score, seed, tempos=None):
    return Arrangement(
        sorted(notes, key=lambda n: (n.start, n.pitch)),
        hs,
        [{"name": "Koraal", "start": 0, "end": melody.length}],
        melody.meters,
        melody.phrases,
        melody.fermatas,
        melody.bpm,
        score,
        seed,
        0,
        melody.length,
        {"method": "empirical_chorale", "fixed_four_voices": False},
        melody.tonic,
        melody.mode,
        tempos or [(0, melody.bpm)],
    )


def _candidates(n, melody, model):
    templates = model["templates"]
    degree = (n.pitch - melody.tonic) % 12
    matching = [
        t for t in templates if t["mode"] == melody.mode and t["degree"] == degree
    ]
    if not matching:
        matching = [t for t in templates if t["degree"] == degree] or templates
    denominator = sum(t["count"] for t in matching)
    scale = {(melody.tonic + x) % 12 for x in MODES[melody.mode]}
    candidates = {}
    density = Counter()
    for t in matching:
        density[len(t["offsets"])] += t["count"]
    strength = model["parameters"]["texture_strength"]
    for t in matching:
        pitches = tuple(sorted(n.pitch - x for x in t["offsets"]))
        if not pitches or min(pitches) < 21 or max(pitches) >= n.pitch:
            continue
        # Two-hand geometry: all notes must fit in two spans of at most an octave.
        if _hand_split(pitches, n.pitch) is None:
            continue
        cost = -strength * math.log((t["count"] + 1) / (denominator + len(matching)))
        cost += 0.55 * sum(p % 12 not in scale for p in pitches)
        cost += 0.02 * abs(n.pitch - pitches[0] - model["bass_gap"])
        cost += (1 - strength) * 0.75 * abs(len(pitches) - 3)
        cost -= (
            strength * 0.3 * math.log((density[len(pitches)] + 1) / (denominator + 4))
        )
        if any(abs(n.end - f) < 1e-6 for f in melody.fermatas):
            cost -= strength * 0.25 * math.log1p(t.get("cadence_count", 0))
        candidates[pitches] = min(candidates.get(pitches, math.inf), cost)
    if not candidates:
        # A transparent diatonic fallback, without an obligatory fourth voice.
        bass = max(21, n.pitch - 24)
        bass = min(
            (
                p
                for p in range(max(21, bass - 5), min(n.pitch, bass + 6))
                if p % 12 in scale
            ),
            key=lambda p: abs(p - bass),
        )
        candidates[(bass,)] = 2.0
    return sorted(candidates.items(), key=lambda x: x[1])[:24]


def _hand_split(pitches, top):
    return next(
        (
            i
            for i in range(1, len(pitches) + 1)
            if pitches[i - 1] - pitches[0] <= 12
            and (i == len(pitches) or top - pitches[i] <= 12)
        ),
        None,
    )


def generate_chorale(melody, model, seed=0, tempos=None):
    if model.get("cadence_relative_preparations") and not model.get(
        "cadence_destination_contracts"
    ):
        raise ValueError("Relative cadence preparations require destination contracts")
    gesture_decoders = (
        "corpus_gestures_v1",
        "corpus_gestures_v2",
        "cadence_context_v1",
        "phrase_harmony_v1",
        "phrase_continuity_v1",
    )
    if model.get("octave_register"):
        from .chorale_octave_register import refine_octaves

        if model.get("decoder") not in gesture_decoders:
            raise ValueError("Octave register refinement requires a gesture decoder")
        if not model.get("register_density_profiles") or not model.get("training_ids"):
            raise ValueError(
                "Octave register refinement requires disclosed corpus densities"
            )
        original_model = dict(model)
        original_model.pop("octave_register")
        arrangement = generate_chorale(melody, original_model, seed, tempos)
        return refine_octaves(
            arrangement,
            melody,
            model["register_density_profiles"],
            model["training_ids"],
        )
    if (
        model.get("cadence_destination_contracts")
        and model.get("decoder") not in gesture_decoders
    ):
        raise ValueError(
            "This decoder does not implement cadence destination contracts"
        )
    if (
        model.get("terminal_cadence") is not None
        and model.get("decoder") not in gesture_decoders
    ):
        raise ValueError("This decoder does not implement terminal_cadence")
    if (
        model.get("decoder") not in gesture_decoders
        and model.get("gesture_search") is not None
    ):
        raise ValueError("This decoder does not implement gesture search controls")
    if model.get("structural_search") and model.get("decoder") not in (
        *gesture_decoders,
        "whole_phrase_transfer_v1",
    ):
        raise ValueError("This decoder does not implement structural search controls")
    if model.get("decoder") == "structural_figures_v1":
        from .chorale_figures import generate

        return generate(melody, model, seed, tempos)
    if model.get("decoder") == "phrase_rhythm_v1":
        from .chorale_rhythm_plan import generate

        return generate(melody, model, seed, tempos)
    if model.get("decoder") == "two_pass_bass_v1":
        from .chorale_bass_plan import generate

        return generate(melody, model, seed, tempos)
    if model.get("decoder") == "whole_phrase_transfer_v1":
        from .chorale_phrase_transfer import generate

        return generate(melody, model, seed, tempos)
    if model.get("decoder") in (
        "corpus_gestures_v1",
        "corpus_gestures_v2",
        "cadence_context_v1",
        "phrase_harmony_v1",
        "phrase_continuity_v1",
    ):
        from .chorale_gestures import generate

        return generate(melody, model, seed, tempos)
    if model.get("decoder"):
        raise ValueError("Unknown chorale decoder version.")
    melody.validate()
    params = model["parameters"]

    @lru_cache(maxsize=1024)
    def chord_label(pitches, top):
        ch = identify_chord([*pitches, top])
        return f"{(ch[0] - melody.tonic) % 12}:{ch[1]}" if ch else ""

    if params["texture_strength"] == 0:
        hs, score = harmonize(melody, model, seed, beam_width=16)
        notes = melody.notes + accompaniment(hs, melody, seed, {})
        # Normalize role representation and attack strength for a fair score test.
        notes = [
            replace(
                n,
                role="bass"
                if n.role == "tenor"
                else "inner"
                if n.role == "alto"
                else n.role,
                velocity=72,
            )
            for n in notes
        ]
        return _layout(melody, notes, hs, score, seed, tempos)
    blocks = []
    for n in melody.notes:
        cuts = [n.start, n.end]
        decision = (
            int(hashlib.sha256(f"{seed}:{n.start}".encode()).hexdigest()[:8], 16)
            / 0xFFFFFFFF
        )
        if (
            n.duration >= 2
            and decision < model["subdivision_rate"] * params["subdivision_scale"]
        ):
            cuts.insert(1, n.start + n.duration / 2)
        blocks.extend((a, b, n) for a, b in pairwise(cuts))
    beam = [(0.0, [])]
    for a, b, n in blocks:
        extensions = []
        options = _candidates(n, melody, model)
        for cost, path in beam:
            for pitches, local in options:
                transition = 0
                if path:
                    before = path[-1][2]
                    transition += (
                        params["movement_weight"] * abs(pitches[0] - before[0]) * 0.5
                    )
                    transition += params["movement_weight"] * sum(
                        min(abs(p - q) for q in before) for p in pitches[1:]
                    )
                    transition -= 0.16 * len(set(before) & set(pitches))
                    transition -= 0.12 * math.log1p(
                        model["transitions"].get(
                            chord_label(before, path[-1][3])
                            + ">"
                            + chord_label(pitches, n.pitch),
                            0,
                        )
                    )
                    # Avoid parallel outer fifths/octaves unless corpus likelihood
                    # outweighs the soft penalty. No Bach-style prohibition.
                    oldtop = path[-1][3]
                    if (
                        (oldtop - before[0]) % 12 in (0, 7)
                        and (oldtop - before[0]) % 12 == (n.pitch - pitches[0]) % 12
                        and (n.pitch - oldtop) * (pitches[0] - before[0]) > 0
                    ):
                        transition += 0.45
                extensions.append(
                    (cost + local + transition, path + [(a, b, pitches, n.pitch)])
                )
        beam = sorted(extensions, key=lambda x: x[0])[:16]
    score, path = beam[0]
    voices = defaultdict(list)
    hs = []
    for a, b, pitches, top in path:
        split = _hand_split(pitches, top)
        for i, p in enumerate(pitches):
            role = "bass" if i < split else "inner"
            lane = voices[(role, p)]
            if (
                params["hold_common"]
                and lane
                and abs(lane[-1].end - a) < 1e-6
                and a not in melody.phrases
            ):
                lane[-1] = replace(lane[-1], duration=b - lane[-1].start)
            else:
                lane.append(Event(p, a, b - a, 72, role))
        ch = identify_chord([*pitches, top]) or (pitches[0] % 12, "major")
        hs.append(Harmony(a, b, ch[0], ch[1], pitches[0], tuple(pitches[1:])))
    notes = list(melody.notes) + [n for lane in voices.values() for n in lane]
    result = _layout(melody, notes, hs, score / max(1, len(path)), seed, tempos)
    result.diagnostics["model_revision"] = model["revision"]
    return result


def model_hash(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()
