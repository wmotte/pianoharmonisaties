"""Phrase-level harmonic search, piano voicing and thematic introduction/coda."""

import hashlib
import itertools
import json
import math
import random
from dataclasses import dataclass, field, replace

from .model import MODES, Event, satb_coverage
from .profile import QUALITIES


@dataclass(frozen=True)
class Harmony:
    start: float
    end: float
    root: int
    quality: str
    bass: int
    inner: tuple[int, ...]


@dataclass
class Arrangement:
    notes: list[Event]
    harmony: list[Harmony]
    sections: list[dict]
    meters: list[tuple]
    phrases: list[float]
    fermatas: list[float]
    bpm: float
    score: float
    seed: int
    melody_offset: float
    length: float
    diagnostics: dict
    tonic: int = 0
    mode: str = "major"
    tempos: list[tuple[float, float]] = field(default_factory=list)


def pitch_class_near(pc, center, low, high):
    candidates = [n for n in range(low, high + 1) if n % 12 == pc]
    return min(candidates, key=lambda n: abs(n - center)) if candidates else None


def chord_options(melody):
    scale = [(melody.tonic + x) % 12 for x in MODES[melody.mode]]
    result = []
    for i, root in enumerate(scale):
        intervals = tuple(sorted((scale[(i + j) % 7] - root) % 12 for j in (0, 2, 4)))
        quality = next((q for q, v in QUALITIES.items() if v == intervals), None)
        if quality:
            result.append((root, quality))
    # Secondary dominants and colour tones are candidates, not imposed modulations.
    for root in scale:
        result.extend(
            (root, q) for q in ("major", "sus2", "sus4", "dom7", "add9", "min7", "maj7")
        )
    return list(dict.fromkeys(result))


def windows(melody):
    boundaries = sorted(
        {
            0.0,
            melody.length,
            *melody.phrases,
            *(n.start for n in melody.notes),
            *(n.end for n in melody.notes),
        }
    )
    return [
        (start, end)
        for start, end in itertools.pairwise(boundaries)
        if any(n.start < end and n.end > start for n in melody.notes)
    ]


def melodic_cost(notes, start, end, pcs):
    total = 0
    for n in notes:
        overlap = min(n.end, end) - max(n.start, start)
        if overlap > 0:
            if n.pitch % 12 in pcs:
                total -= overlap * 0.6
            else:
                index = notes.index(n)
                before = notes[index - 1] if index else None
                after = notes[index + 1] if index + 1 < len(notes) else None
                resolving = (
                    after
                    and after.pitch % 12 in pcs
                    and abs(after.pitch - n.pitch) <= 2
                )
                passing = (
                    before
                    and resolving
                    and before.pitch % 12 in pcs
                    and abs(before.pitch - n.pitch) <= 2
                )
                suspension = before and resolving and before.pitch == n.pitch
                weight = (
                    0.35 if n.duration <= 1 and passing else 0.7 if suspension else 2.5
                )
                total += overlap * weight
    return total


def voice(
    root, quality, lowmel, previous, tonic, profile, highmel=None, root_position=False
):
    """Exactly B<T<A<S, with named inner lines and playable two-hand spans.

    Pitch-class doubling is allowed: four voices do not require a seventh chord.
    An impossible register is rejected rather than reduced to three voices.
    """
    pcs = [(root + i) % 12 for i in QUALITIES[quality]]
    highmel = lowmel if highmel is None else highmel
    bass_pcs = (root,) if root_position else (root, pcs[1], pcs[2])
    candidates = []
    for bass in range(21, min(60, lowmel - 3)):
        if bass % 12 not in bass_pcs:
            continue
        for tenor in range(bass + 3, min(bass + 12, lowmel - 2) + 1):
            if tenor % 12 not in pcs:
                continue
            for alto in range(
                max(tenor + 1, highmel - 12), min(lowmel - 1, tenor + 12) + 1
            ):
                if alto % 12 not in pcs:
                    continue
                inner = (tenor, alto)
                present = {bass % 12, tenor % 12, alto % 12, lowmel % 12}
                completeness = len(set(pcs) - present)
                cost = 2 * completeness + (0.6 if bass % 12 != root else 0)
                cost += 0.025 * abs(bass - max(28, min(48, lowmel - 24)))
                if previous and len(previous.inner) == 2:
                    # Compare tenor to tenor and alto to alto, never nearest-note matching.
                    moves = (
                        abs(bass - previous.bass),
                        abs(tenor - previous.inner[0]),
                        abs(alto - previous.inner[1]),
                    )
                    cost += 0.08 * moves[0] + 0.13 * (moves[1] + moves[2])
                    cost += 0.25 * sum(max(0, jump - 7) for jump in moves[1:])
                    cost -= 0.06 * math.log1p(
                        profile.get("bass_steps", {}).get(str(bass - previous.bass), 0)
                    )
                # Doubling the root is normal in a four-part triad. Avoid unnecessary
                # doubling of an active major third when a fuller voicing is available.
                cost += 0.25 * (
                    sum(p % 12 == pcs[1] for p in (bass, tenor, alto, lowmel)) > 1
                )
                shape = ",".join(
                    map(str, (0, tenor - bass, alto - bass, lowmel - bass))
                )
                cost -= 0.12 * math.log1p(profile.get("voicings", {}).get(shape, 0))
                candidates.append((cost, bass, inner))
    if not candidates:
        return None, (), math.inf
    cost, bass, inner = min(candidates)
    return bass, inner, cost


def harmonize(
    melody, profile, seed, beam_width=16, final_root=None, closed_ending=False
):
    rng = random.Random(seed)
    options = chord_options(melody)
    ws = windows(melody)
    counts = profile.get("mode_chords", {}).get(melody.mode, profile.get("chords", {}))
    transitions = profile.get("mode_transitions", {}).get(
        melody.mode, profile.get("transitions", {})
    )
    beam = [(0.0, [])]
    tonic_pcs = {(melody.tonic + i) % 12 for i in MODES[melody.mode]}
    cadence_roots = {}
    last_cadence = None
    for boundary in melody.phrases:
        last_note = max(
            (n for n in melody.notes if n.start < boundary), key=lambda n: n.start
        )
        viable = list(
            dict.fromkeys(
                r
                for r, q in options
                if q in ("major", "minor")
                and last_note.pitch % 12 in {(r + x) % 12 for x in QUALITIES[q]}
                and {(r + x) % 12 for x in QUALITIES[q]} <= tonic_pcs
            )
        )
        choices = [r for r in viable if r != last_cadence] or viable
        last_cadence = rng.choice(choices) if choices else melody.tonic
        cadence_roots[boundary] = last_cadence
    for wi, (start, end) in enumerate(ws):
        sounding = [n for n in melody.notes if n.start < end and n.end > start]
        lowmel = min((n.pitch for n in sounding), default=72)
        highmel = max((n.pitch for n in sounding), default=72)
        final = wi == len(ws) - 1
        target = melody.tonic if final_root is None else final_root
        scored = []
        for root, quality in options:
            if final and root != target:
                continue
            if (
                final
                and closed_ending
                and quality != ("major" if MODES[melody.mode][2] == 4 else "minor")
            ):
                continue
            pcs = {(root + i) % 12 for i in QUALITIES[quality]}
            label = f"{(root - melody.tonic) % 12}:{quality}"
            cost = melodic_cost(melody.notes, start, end, pcs)
            cost += 0.65 * len(pcs - tonic_pcs)
            cost -= 0.16 * math.log1p(counts.get(label, 0))
            conditional = profile.get("melody_chords", {})
            for n in sounding:
                degree = (n.pitch - melody.tonic) % 12
                cost -= (
                    0.12
                    * math.log1p(conditional.get(f"{melody.mode}|{degree}>{label}", 0))
                    / len(sounding)
                )
            if any(abs(end - b) < 1e-6 for b in melody.phrases):
                cost -= 1.1 if root == cadence_roots[end] else 0
                if sounding and sounding[-1].pitch % 12 not in pcs:
                    cost += 2
            if final and quality in (
                "sus2",
                "sus4",
                "dom7",
                "maj7",
                "min7",
                "add9",
                "dim",
            ):
                cost += 3
            scored.append((cost, root, quality, label))
        extensions = []
        # Cache expensive voicings for shared previous states.
        cache = {}
        for oldscore, path in beam:
            previous = path[-1] if path else None
            for cost, root, quality, label in sorted(scored)[:10]:
                prevlabel = (
                    f"{(previous.root - melody.tonic) % 12}:{previous.quality}"
                    if previous
                    else ""
                )
                transition = -0.15 * math.log1p(
                    transitions.get(prevlabel + ">" + label, 0)
                )
                if previous:
                    same = previous.root == root and previous.quality == quality
                    mt, numerator, denominator = next(
                        m for m in reversed(melody.meters) if m[0] <= start
                    )
                    bar_length = numerator * 4 / denominator
                    strong = abs((start - mt) % bar_length) < 1e-7
                    if numerator >= 4:
                        strong |= abs((start - mt) % bar_length - bar_length / 2) < 1e-7
                    transition += (
                        (-0.5 if same else 0.7)
                        if not strong
                        else (-0.05 if same else 0)
                    )
                    if len(path) >= 4 and all(
                        (h.root, h.quality) == (root, quality) for h in path[-4:]
                    ):
                        transition += 0.35
                key = (
                    root,
                    quality,
                    previous.bass if previous else None,
                    previous.inner if previous else (),
                )
                if key not in cache:
                    cache[key] = voice(
                        root,
                        quality,
                        lowmel,
                        previous,
                        melody.tonic,
                        profile,
                        highmel,
                        root_position=final and closed_ending,
                    )
                bass, inner, vcost = cache[key]
                if bass is None:
                    continue
                if previous:
                    # Contrary and stepwise bass motion are preferred, not required.
                    transition += 0.04 * abs(bass - previous.bass)
                    previous_top = next(
                        (
                            n.pitch
                            for n in melody.notes
                            if n.start <= previous.start < n.end
                        ),
                        lowmel,
                    )
                    old_voices = (previous.bass, *previous.inner, previous_top)
                    new_voices = (bass, *inner, lowmel)
                    for x, y in itertools.combinations(range(4), 2):
                        interval = (old_voices[y] - old_voices[x]) % 12
                        if (
                            interval in (0, 7)
                            and (new_voices[y] - new_voices[x]) % 12 == interval
                            and (new_voices[x] - old_voices[x])
                            * (new_voices[y] - old_voices[y])
                            > 0
                        ):
                            transition += 1.25
                value = oldscore + cost + transition + 0.25 * vcost
                extensions.append(
                    (
                        value + rng.uniform(-0.35, 0.35),
                        value,
                        path + [Harmony(start, end, root, quality, bass, inner)],
                    )
                )
        if not extensions:
            raise ValueError("Geen speelbare zetting gevonden voor dit melodiebereik.")
        beam = [
            (value, path)
            for _, value, path in sorted(extensions, key=lambda x: x[0])[:beam_width]
        ]
    score, path = beam[0]
    return path, score / max(1, len(ws))


def thematic_melody(melody, length, section):
    # Kept as an API for callers inspecting the upper line. Generation uses the
    # accompanying harmonic plan as well, not a second harmonization of this line.
    from .prelude import free_section

    return free_section(melody, length, section)[0]


def accompaniment(harmonies, melody, seed, profile):
    """Keep explicit B/T/A lines, tied common notes and silence at melody rests."""
    notes = []
    for h in harmonies:
        if len(h.inner) != 2:
            raise ValueError("Vierstemmige zetting vereist afzonderlijke tenor en alt.")
        for n in melody.notes:
            start, end = max(h.start, n.start), min(h.end, n.end)
            if end <= start:
                continue
            for role, pitch, velocity in (
                ("bass", h.bass, 62),
                ("tenor", h.inner[0], 58),
                ("alto", h.inner[1], 61),
            ):
                notes.append(Event(pitch, start, end - start, velocity, role))
    result = []
    for role in ("bass", "tenor", "alto"):
        lane = []
        for n in sorted((n for n in notes if n.role == role), key=lambda n: n.start):
            if (
                lane
                and lane[-1].pitch == n.pitch
                and abs(lane[-1].end - n.start) < 1e-7
                and n.start not in melody.phrases
            ):
                lane[-1] = replace(lane[-1], duration=n.end - lane[-1].start)
            else:
                lane.append(n)
        result.extend(lane)
    return result


def build_arrangement(melody, profile, config, seed):
    from .prelude import free_accompaniment, free_section
    from .timing import section_settings

    unknown = set(config.get("sections", {})) - {"intro", "outro"}
    if unknown:
        raise ValueError(f"Onbekende vormdelen: {sorted(unknown)}")
    intro_settings = section_settings(
        melody, profile, config, "Voorspel", random.Random(seed)
    )
    outro_settings = section_settings(
        melody, profile, config, "Naspel", random.Random(seed + 2018)
    )
    intro_length, outro_length = intro_settings["length"], outro_settings["length"]
    chorale_harmony, chorale_score = harmonize(
        melody, profile, seed + 1009, beam_width=16
    )
    intro_settings["arrival_root"] = chorale_harmony[0].root
    intro_settings["arrival_quality"] = chorale_harmony[0].quality
    intro, intro_harmony, intro_score, intro_plan = free_section(
        melody, intro_length, "Voorspel", seed, profile, intro_settings
    )
    outro, outro_harmony, outro_score, outro_plan = free_section(
        melody,
        outro_length,
        "Naspel",
        seed + 2018,
        profile,
        outro_settings,
        intro_plan["motifs"],
    )
    sections, notes, harmonies, phrases, fermatas, meters, tempos = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    cursor, total_score = 0.0, 0.0
    for i, (name, part) in enumerate(
        (("Voorspel", intro), ("Harmonisatie", melody), ("Naspel", outro))
    ):
        if i == 0:
            hs, score = intro_harmony, intro_score
        elif i == 2:
            hs, score = outro_harmony, outro_score
        else:
            hs, score = chorale_harmony, chorale_score
        generated = part.notes + (
            accompaniment(hs, part, seed + i, profile)
            if i == 1
            else free_accompaniment(
                hs, part, intro_plan if i == 0 else outro_plan, profile
            )
        )
        if i == 1 and not satb_coverage(generated)["valid"]:
            raise ValueError("De gegenereerde zetting is niet continu vierstemmig.")
        notes.extend(replace(n, start=n.start + cursor) for n in generated)
        harmonies.extend(
            replace(h, start=h.start + cursor, end=h.end + cursor) for h in hs
        )
        sections.append(
            {
                "name": name,
                "start": cursor,
                "end": cursor + part.length,
                "quarter_bpm": part.bpm,
                "texture": "SATB" if i == 1 else "variable",
            }
        )
        if not tempos or tempos[-1][1] != part.bpm:
            tempos.append((cursor, part.bpm))
        meters.extend((t + cursor, num, den) for t, num, den in part.meters)
        phrases.extend(p + cursor for p in part.phrases)
        fermatas.extend(p + cursor for p in part.fermatas)
        cursor += part.length
        total_score += score
    # The structural melody is copied, never regenerated or post-corrected.
    expected = [
        (n.pitch, round(n.start + intro_length, 7), round(n.duration, 7))
        for n in melody.notes
    ]
    actual = [
        (n.pitch, round(n.start, 7), round(n.duration, 7))
        for n in notes
        if n.role == "melody"
    ]
    if actual != expected:
        raise AssertionError("Interne fout: melodie gewijzigd.")
    matches = []
    for section in sections:
        if section["name"] == "Harmonisatie":
            continue
        motif = [
            n
            for n in notes
            if n.role == "motif" and section["start"] <= n.start < section["end"]
        ]
        for j in range(len(motif) - 12):
            intervals = [motif[k + 1].pitch - motif[k].pitch for k in range(j, j + 12)]
            signature = hashlib.sha256(json.dumps(intervals).encode()).hexdigest()[:20]
            if signature in profile.get("reference_contours", {}):
                matches.append(
                    {
                        "section": section["name"],
                        "beat": motif[j].start,
                        "reference": profile["reference_contours"][signature],
                    }
                )
    total_score += len(matches)
    return Arrangement(
        sorted(notes, key=lambda n: (n.start, n.pitch)),
        harmonies,
        sections,
        meters,
        phrases,
        fermatas,
        melody.bpm,
        total_score / 3,
        seed,
        intro_length,
        cursor,
        {
            "melody_exact": True,
            "profile_status": profile["status"],
            "human_accepted": False,
            "musical_quality": "not_evaluated",
            "reference_contour_matches": matches,
            "novelty_check_scope": "12 successive pitch intervals in introduction/coda only; absence is not proof of originality",
            "form_source": "section-conditioned phrase and motif development; fixed SATB chorale",
            "prelude_plan": intro_plan,
            "postlude_plan": outro_plan,
            "voicing": "SATB chorale; variable free sections",
            "satb_coverage": satb_coverage(
                notes, intro_length, intro_length + melody.length
            ),
        },
        tonic=melody.tonic,
        mode=melody.mode,
        tempos=tempos,
    )


def generate(melody, profile, config):
    number = int(config.get("candidates", 32))
    if not 3 <= number <= 32:
        raise ValueError("candidates moet tussen 3 en 32 liggen.")
    if profile["status"] != "reviewed" and not config.get("allow_draft", False):
        raise ValueError(
            "Dit profiel is niet muzikaal gecontroleerd. Gebruik allow_draft alleen voor proeven."
        )
    seed = int(config.get("seed", 0))
    arrangements = []
    fingerprints = set()
    for i in range(number):
        a = build_arrangement(melody, profile, config, seed + i * 7919)
        from .composition import composition_metrics

        a.diagnostics["composition"] = composition_metrics(a)
        a.score += a.diagnostics["composition"]["penalty"]
        fp = tuple((h.root, h.quality, h.bass, h.inner) for h in a.harmony)
        if fp not in fingerprints:
            fingerprints.add(fp)
            arrangements.append(a)
    return sorted(arrangements, key=lambda a: (a.score, a.seed))
