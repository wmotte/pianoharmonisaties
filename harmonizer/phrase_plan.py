"""Compose complete phrases with a stable accompaniment and directed cadences."""

import math
from dataclasses import asdict, replace
from itertools import pairwise, product

from .counterpoint import (CompositionError, hand_assignment, leading_tones, line_issues,
                           strong_beat, transition_valid)
from .model import Event, Melody, MODES
from .motifs import Motif, extract_motifs, scale_pitch, scale_position, transform
from .profile import QUALITIES

EPS = 1e-7


def _triad(melody, degree):
    scale = MODES[melody.mode]
    root = (melody.tonic + scale[degree % 7]) % 12
    intervals = tuple(sorted((scale[(degree + i) % 7] - scale[degree % 7]) % 12 for i in (0, 2, 4)))
    quality = next((q for q in ("major", "minor") if QUALITIES[q] == intervals), None)
    return (root, quality) if quality else None


def _material(melody, material, bar):
    bank = [Motif.from_data(m) for m in material] if material else extract_motifs(melody, limit=64)
    opening = [m for m in bank if m.source_start == melody.notes[0].start]
    main = min(opening or bank, key=lambda m: (abs(len(m.tones) - 4), abs(m.span - 2 * bar)))
    answers = [m for m in bank if m.source_start != main.source_start
               and len(set(t.degree for t in m.tones)) >= 3]
    other = min(answers, key=lambda m: (max(abs(b.degree - a.degree) for a, b in pairwise(m.tones)),
                                       len(m.tones) != 3, -m.source_end), default=main)
    return [main, other]


def _cell(motif, start, span, melody, *, center=69, transpose=0, invert=False, previous_pitch=None):
    factor = 1.0
    while motif.span * factor > span + EPS:
        factor /= 2
    while motif.span * factor * 2 <= span + EPS:
        factor *= 2
    cell = transform(motif, transpose=transpose, invert=invert, time_scale=factor)
    raw = [scale_pitch(t.degree, melody.tonic, melody.mode, t.alteration) for t in cell.tones]
    octaves = [n for n in range(-48, 49, 12) if min(raw) + n >= 48 and max(raw) + n <= 79]
    if not octaves:
        raise CompositionError("Het motief past niet als geheel in het gekozen pianoregister.")
    shift = min(octaves, key=lambda n: abs(sum(raw) / len(raw) + n - center)
                + (2 * abs(raw[0] + n - previous_pitch) if previous_pitch is not None else 0))
    notes = [Event(p + shift, start + t.offset, t.duration, role="motif") for p, t in zip(raw, cell.tones)]
    # Complete the musical unit before starting its answer. Never tile a 4.5-beat
    # cell over a four-beat metre just to fill the requested section length.
    notes[-1] = replace(notes[-1], duration=start + span - notes[-1].start)
    return notes


def phrase_schedule(melody, length, bar, motifs, section, settings, seed):
    ends, cursor = [], 0.0
    while cursor < length - EPS:
        cursor = min(length, cursor + 4 * bar)
        ends.append(cursor)
    phases, notes = [], []
    start = 0.0
    minor = MODES[melody.mode][2] == 3
    for i, end in enumerate(ends):
        last = i == len(ends) - 1
        if section == "Voorspel":
            target = "dominant" if last or i % 3 == 0 else "tonic" if i % 3 == 1 else "contrast"
        else:
            target = "tonic" if last or i == 0 else "contrast" if i % 2 else "dominant"
        function = "statement" if i == 0 else "cadence" if last else "return" if i == len(ends) - 2 else "sequence" if i % 2 else "answer"
        root, quality = (_triad(melody, 2 if minor else 3) if target == "contrast" else
                         ((settings.get("arrival_root", melody.tonic) + 7) % 12, "major") if target == "dominant" else
                         (melody.tonic, settings.get("terminal_quality", "minor" if minor else "major")
                          if last and section == "Naspel" else "minor" if minor else "major"))
        span = end - start
        center = sum(scale_pitch(t.degree, melody.tonic, melody.mode, t.alteration)
                     for t in motifs[0].tones) / len(motifs[0].tones)
        if function == "sequence":
            center += 2
        density = 4 if function == "sequence" or last else 3
        call_span = min(2 * bar, span / 2)
        family = 0 if function in ("statement", "return", "cadence") else 1
        entry_transpose = 0
        if i == 0 and section == "Naspel" and settings.get("departure_voices"):
            family = 1
            departure_pitch = settings["departure_voices"]["motif"]
            anchor, _ = scale_position(departure_pitch - 2, melody.tonic, melody.mode)
            relative_floor = min(t.degree - motifs[family].tones[0].degree for t in motifs[family].tones)
            while scale_pitch(anchor + relative_floor, melody.tonic, melody.mode) < 48:
                anchor += 1
            entry_transpose = anchor - motifs[family].tones[0].degree
            center = max(48, departure_pitch - 3)
        if function == "sequence" and span >= 4 * bar - EPS:
            family = 0 if seed % 3 == 1 else 1
            displacement = seed % 3 - 1
            first = _cell(motifs[family], start, bar, melody, center=center, transpose=displacement,
                          previous_pitch=notes[-1].pitch if notes else None)
            second = _cell(motifs[family], start + bar, bar, melody, center=center + 1, transpose=displacement + 1,
                           previous_pitch=first[-1].pitch)
            call = first + second
        else:
            call = _cell(motifs[family], start, call_span, melody, center=center,
                         transpose=entry_transpose,
                         invert=function == "answer" and seed % 2 == 1,
                         previous_pitch=notes[-1].pitch if notes else None)
        notes.extend(call)
        answer_start = start + call_span
        answer_span = end - answer_start
        if answer_span > EPS:
            # A short response gives way to a long cadence note. Its contour is
            # derived from the cell rather than another endlessly repeated loop.
            response = _cell(motifs[1 - family], answer_start, answer_span, melody, center=call[-1].pitch - 1)
            head = response[:3]
            cadence_start = max(answer_start, end - bar)
            head_span = cadence_start - answer_start
            pcs = {(root + x) % 12 for x in QUALITIES[quality]}
            center_end = (settings.get("arrival_voices", {}).get("motif", melody.notes[0].pitch) - 1
                          if last and section == "Voorspel" else
                          melody.notes[-1].pitch if last else melody.notes[0].pitch + 2)
            terminal_pcs = {(root + 4) % 12} if target == "dominant" else pcs
            pitch = min((p for p in range(48 if last else 60, 80) if p % 12 in terminal_pcs),
                        key=lambda p: abs(p - center_end))
            if head_span > EPS:
                weights = (1, 1, 2)[:len(head)]
                at = answer_start
                goal, _ = scale_position(pitch, melody.tonic, melody.mode)
                direction = 1 if pitch > call[-1].pitch else -1
                for j, (event, weight) in enumerate(zip(head, weights)):
                    duration = head_span * weight / sum(weights)
                    linked_pitch = scale_pitch(goal - direction * (len(head) - 1 - j), melody.tonic, melody.mode)
                    notes.append(replace(event, pitch=linked_pitch, start=at, duration=duration))
                    at += duration
            if target == "dominant" and end - cadence_start >= bar - EPS:
                suspended = pitch + (1 if pitch % 12 == (root + 4) % 12 else 0)
                if suspended == pitch:
                    pitch = min((p for p in range(48 if last else 60, 80) if p % 12 == (root + 4) % 12),
                                key=lambda p: abs(p - center_end))
                    suspended = pitch + 1
                split = bar * (2 / 3 if settings["meter"][0] == 3 else 0.5)
                notes.extend((Event(suspended, cadence_start, split, role="motif"),
                              Event(pitch, cadence_start + split, end - cadence_start - split, role="motif")))
            else:
                notes.append(Event(pitch, cadence_start, end - cadence_start, role="motif"))
        phases.append({"start": start, "end": end, "function": function, "motif": family,
                       "density": density, "pedal_point": False,
                       "cadence": target, "cadence_root": root, "cadence_quality": quality,
                       "cells": [{"start": start, "end": answer_start, "source": family,
                                  "transform": function, "fragment": False}]})
        start = end
    return phases, notes


def harmonic_options(melody, phase, index, count):
    tonic = _triad(melody, 0)
    def degrees(values):
        return list(dict.fromkeys(c for d in values if (c := _triad(melody, d))))
    target = phase["cadence_root"], phase["cadence_quality"]
    if count <= 2:
        return [target]
    if phase["cadence"] == "dominant":
        if index == count - 2:
            return [(target[0], "sus4")]
        if index == count - 1:
            return [target]
    else:
        if index >= count - 2:
            return [target]
        if index == count - 3:
            return [((target[0] + 7) % 12, "major")]
        if index == count - 4:
            return [((target[0] + 7) % 12, "sus4")]
    if index == 0:
        return [tonic]
    if index == 1:
        return degrees((0, 2, 5))
    if index == 2:
        return degrees((0, 2, 3, 1))
    if index % 3 == 2:
        return degrees((3, 1, 5))
    if index % 3 == 0:
        return degrees((0, 2, 3))
    return degrees((1, 3, 5))


def _blocks(length, bar, num):
    result, a = [], 0.0
    while a < length - EPS:
        split = bar * 2 / 3 if num == 3 else bar / 2
        result.append((a, min(length, a + split)))
        if a + split < min(length, a + bar) - EPS:
            result.append((a + split, min(length, a + bar)))
        a += bar
    return result


def _lines(items, root, quality, final=False):
    pcs = {(root + x) % 12 for x in QUALITIES[quality]}
    choices = []
    for n in items:
        floor = max(48, min(60, n.pitch))
        pitches = sorted((p for p in range(floor, 80) if p % 12 in pcs), key=lambda p: abs(p - n.pitch))
        pitches = pitches[:7] if final else [p for p in pitches[:4] if abs(p - n.pitch) <= 4]
        choices.append(pitches)
    rows = []
    for pitches in product(*choices):
        if any(abs(b - a) > 7 or abs(b - a) == 6 for a, b in pairwise(pitches)):
            continue
        cost = 1.8 * sum(abs(p - n.pitch) for n, p in zip(items, pitches))
        for i, (a, b) in enumerate(pairwise(pitches)):
            intended = items[i + 1].pitch - items[i].pitch
            cost += 1.5 * (a == b and intended != 0)
            cost += 2 * ((b - a) * intended < 0)
        rows.append((cost, pitches))
    return sorted(rows)[:8]


def _candidates(melody, items, root, quality, density, final, leading):
    from .thematic import _voicings
    candidates = []
    pcs = {(root + x) % 12 for x in QUALITIES[quality]}
    for melodic_cost, pitches in _lines(items, root, quality, final):
        for local, voices in _voicings(root, quality, pitches[0], density, final, leading):
            inner = [p for role, p in voices.items() if role in ("alto", "tenor")]
            if inner and max(inner) >= min(pitches):
                continue
            if "alto" in voices and max(pitches) - voices["alto"] > 12:
                continue
            if "tenor" in voices and max(pitches) - voices["tenor"] > 12 and voices["tenor"] - voices["bass"] > 12:
                continue
            fixed = [p for role, p in voices.items() if role != "motif"]
            if any(p % 12 in leading and sum(x % 12 == p % 12 for x in [*fixed, p]) > 1 for p in pitches):
                continue
            if density >= 3:
                defining = (root + (4 if quality == "major" else 3 if quality == "minor" else 5)) % 12
                if any(defining not in {p % 12 for p in [*fixed, top]} for top in pitches):
                    continue
            cost = (melodic_cost + local + abs(voices["bass"] - 48) * 0.16
                    + 1.8 * (voices["bass"] % 12 != root))
            candidates.append((cost, voices, pitches))
    # Keep enough different basses/inner positions for whole-phrase voice leading.
    return sorted(candidates, key=lambda c: c[0])[:80]


def _connection(before, after, old_chord, chord):
    before, after = dict(before), dict(after)
    if "motif" not in before and "alto" in before:
        before["motif"] = before["alto"]
    if "motif" not in after and "alto" in after:
        after["motif"] = after["alto"]
    if not transition_valid(before, after):
        return False
    if old_chord and old_chord[1] == "sus4" and old_chord[0] == chord[0] and chord[1] in ("major", "minor"):
        third = (chord[0] + (4 if chord[1] == "major" else 3)) % 12
        if any(p % 12 == (chord[0] + 5) % 12 and role in after
               and (after[role] - p not in (-1, -2) or after[role] % 12 != third)
               for role, p in before.items()):
            return False
    if old_chord and old_chord[1] == "major" and (chord[0] - old_chord[0]) % 12 == 5:
        if any(p % 12 == (old_chord[0] + 4) % 12 and role in after and after[role] - p not in (0, 1)
               for role, p in before.items() if role in ("bass", "motif")):
            return False
    return True


def _ornament(top, accompaniment, harmonies, meters, phases, bar, scale_pcs):
    result, decorations, used_bars = list(top), [], set()
    for i in reversed(range(len(result) - 1)):
        a, b = result[i:i + 2]
        phase = next(p for p in phases if p["start"] <= a.start < p["end"])
        bar_index = int(a.start // bar)
        if (a.start < 2 * bar or a.end > phase["end"] - bar + EPS or a.duration < 1
                or abs(a.end - b.start) > EPS or bar_index in used_bars):
            continue
        time = a.end - 0.5
        if strong_beat(meters, time):
            continue
        if abs(b.pitch - a.pitch) in (3, 4):
            choices = [p for p in range(min(a.pitch, b.pitch) + 1, max(a.pitch, b.pitch))
                       if abs(p - a.pitch) <= 2 and abs(b.pitch - p) <= 2]
        elif a.pitch == b.pitch:
            choices = [a.pitch + 2, a.pitch - 2, a.pitch + 1, a.pitch - 1]
        else:
            continue
        for pitch in choices:
            if not 60 <= pitch <= 79 or pitch % 12 not in scale_pcs:
                continue
            if any(n.pitch >= pitch and n.start <= time + EPS < n.end
                   for n in accompaniment):
                continue
            trial = [*result[:i], replace(a, duration=a.duration - 0.5),
                     replace(a, pitch=pitch, start=time, duration=0.5), *result[i + 1:]]
            if not line_issues(trial, accompaniment, harmonies, meters)["valid"]:
                continue
            if hand_assignment([*trial, *accompaniment]) is None:
                continue
            result = trial
            decorations.append({"beat": time, "pitch": pitch, "kind": "passing_or_neighbour"})
            used_bars.add(bar_index)
            break
    return result, decorations


def compose(melody, length, section, seed=0, profile=None, settings=None, material=None):
    from .engine import Harmony
    profile = profile or {}
    settings = settings or {"meter": [4, 4], "quarter_bpm": melody.bpm, "source": {}}
    if not math.isfinite(length) or not 2 <= length <= 512:
        raise ValueError("Een vrij vormdeel vereist 2–512 eindige kwartnoottellen.")
    num, den = settings["meter"]
    bar = num * 4 / den
    motifs = _material(melody, material, bar)
    phases, intended = phrase_schedule(melody, length, bar, motifs, section, settings, seed)
    blocks = _blocks(length, bar, num)
    leading = leading_tones(melody.tonic, melody.mode)
    departure = settings.get("departure_voices", {})
    beam = [(0.0, [], departure, None)]
    for a, b in blocks:
        phase = next(p for p in phases if p["start"] <= a < p["end"])
        phase_blocks = [x for x in blocks if phase["start"] <= x[0] < phase["end"]]
        index = phase_blocks.index((a, b))
        density = phase["density"]
        final = abs(b - length) < EPS
        if a == 0 and section == "Voorspel" and not final:
            density = 2
        if final and section == "Voorspel" and settings.get("piano_descant_entry"):
            density = 3
        items = [replace(n, start=max(a, n.start), duration=min(b, n.end) - max(a, n.start))
                 for n in intended if n.start < b - EPS and n.end > a + EPS]
        active = next((n for n in intended if n.start <= a + EPS < n.end), None)
        held = active is not None and active.start < a - EPS
        resting = not items
        if resting:
            upcoming = next((n for n in intended if n.start >= b - EPS), intended[-1])
            items = [Event(upcoming.pitch, a, b - a, role="motif")]
        extensions = []
        for root, quality in harmonic_options(melody, phase, index, len(phase_blocks)):
            options = _candidates(melody, items, root, quality, 4 if resting else density, final, leading)
            if resting:
                defining = (root + (4 if quality == "major" else 3 if quality == "minor" else 5)) % 12
                options = [(cost, {k: p for k, p in voices.items() if k != "motif"}, ())
                           for cost, voices, _ in options
                           if any(p % 12 == defining for k, p in voices.items() if k != "motif")]
            for old_cost, path, previous, old_chord in beam:
                for cost, voices, pitches in options:
                    if a == 0 and section == "Voorspel" and voices["bass"] % 12 != root:
                        continue
                    if held and previous and previous.get("motif") != pitches[0]:
                        continue
                    if previous and not _connection(previous, voices, old_chord, (root, quality)):
                        continue
                    if pitches and previous and abs(pitches[0] - previous.get("motif", pitches[0])) > 7:
                        continue
                    if pitches and previous and abs(pitches[0] - previous.get("motif", pitches[0])) == 6:
                        continue
                    if final and settings.get("arrival_voices") and not transition_valid(
                            {**voices, "motif": pitches[-1]}, settings["arrival_voices"]):
                        continue
                    motion = sum(abs(p - previous.get(k, p)) * (0.24 if k == "bass" else 0.14)
                                 for k, p in voices.items())
                    history = [n.pitch for block in path[-2:] for n in block[3]]
                    run = 0
                    for p in reversed(history):
                        if not pitches or p != pitches[0]:
                            break
                        run += 1
                    motion += 5 * max(0, run - 1)
                    # A repeated harmony does not call for a new inner-voice gesture.
                    if old_chord == (root, quality):
                        motion += sum(1.0 for k in ("bass", "alto", "tenor")
                                      if k in previous and k in voices and previous[k] != voices[k])
                    top = [replace(n, pitch=p) for n, p in zip(items, pitches)]
                    extensions.append((old_cost + cost + motion,
                                       [*path, (a, b, voices, top, root, quality)],
                                       {**voices, **({"motif": pitches[-1]} if pitches else {})}, (root, quality)))
        if not extensions:
            error = CompositionError(f"Geen complete fraseverbinding in {section} op tel {a:g} (seed {seed}).")
            error.context = {"previous": [(row[2], row[3]) for row in beam[:4]],
                             "items": [(n.pitch, n.start, n.duration) for n in items], "held": held,
                             "options": [(r, q, len(_candidates(melody, items, r, q, density, final, leading)))
                                         for r, q in harmonic_options(melody, phase, index, len(phase_blocks))]}
            raise error
        distinct = {}
        for row in sorted(extensions, key=lambda c: c[0]):
            distinct.setdefault((tuple(sorted(row[2].items())), row[3]), row)
            if len(distinct) >= 40:
                break
        beam = list(distinct.values())
    value, path, _, _ = beam[0]
    top, accompaniment, hs = [], [], []
    for a, b, voices, line, root, quality in path:
        for n in line:
            original = next(x for x in intended if x.start <= n.start + EPS < x.end)
            if top and n.pitch == top[-1].pitch and abs(top[-1].end - n.start) < EPS and original.start < n.start - EPS:
                top[-1] = replace(top[-1], duration=n.end - top[-1].start)
            else:
                top.append(n)
        hs.append(Harmony(a, b, root, quality, voices["bass"], tuple(voices[k] for k in ("tenor", "alto") if k in voices)))
        for role, pitch in voices.items():
            if role == "motif":
                continue
            # Merge only within the same phrase, harmony, and stable hand context.
            prior = next((n for n in reversed(accompaniment) if n.role == role), None)
            same_chord = len(hs) > 1 and (hs[-2].root, hs[-2].quality) == (root, quality)
            if prior and same_chord and prior.pitch == pitch and abs(prior.end - a) < EPS and a not in [p["start"] for p in phases]:
                accompaniment[accompaniment.index(prior)] = replace(prior, duration=b - prior.start)
            else:
                accompaniment.append(Event(pitch, a, b - a, 62, role))
    top, ornaments = _ornament(top, accompaniment, hs, [(0, num, den)], phases, bar,
                               {(melody.tonic + p) % 12 for p in MODES[melody.mode]})
    result = Melody(top, length, [(0, num, den)], [p["end"] for p in phases], melody.tonic, melody.mode, settings["quarter_bpm"])
    result.validate()
    actual = {n.start: n.pitch for n in top}
    realized = [{"start": n.start, "intended_pitch": n.pitch, "realized_pitch": actual.get(n.start)} for n in intended]
    source = settings.get("source", {})
    return result, hs, value / max(1, len(blocks)), {
        "approach": "phrase_motif_development", "planning": "call_response_cadence", "phrases": phases,
        "motifs": [m.data() for m in motifs], "realized_motifs": realized,
        "ornaments": ornaments,
        "exact_pitch_retention": sum(r["intended_pitch"] == r["realized_pitch"] for r in realized) / max(1, len(realized)),
        "accompaniment": [asdict(n) for n in accompaniment],
        "melodic_references": [], "reference_beats": 0, "reference_fraction": 0,
        "source_id": source.get("source_id"), "source_sha256": source.get("source_sha256"),
        "source_reviewed": source.get("reviewed", False),
        "settings": {k: v for k, v in settings.items() if k != "source"},
        "search": {"beam_width": 40, "valid": True},
    }
