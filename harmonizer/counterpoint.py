"""Contextual line checks and bounded countervoice search over an existing score."""

import random
from collections import defaultdict
from dataclasses import replace
from itertools import combinations, pairwise

from .model import Event, MODES
from .motifs import extract_motifs, scale_pitch, scale_position
from .profile import QUALITIES

EPS = 1e-7


class CompositionError(ValueError):
    """No valid candidate in the disclosed search budget."""


def parallel(a, b, c, d):
    return (None not in (a, b, c, d) and a != c and b != d
            and abs(a - b) % 12 == abs(c - d) % 12
            and abs(a - b) % 12 in (0, 7))


def transition_valid(before, after):
    """Named voices, including antiparallel perfect intervals under repo policy."""
    for a, b in combinations(before.keys() & after.keys(), 2):
        if parallel(before[a], before[b], after[a], after[b]):
            return False
    if "bass" in before and "bass" in after and abs(after["bass"] - before["bass"]) > 12:
        return False
    top = "motif" if "motif" in before and "motif" in after else "melody"
    if all(k in before and k in after for k in ("bass", top)):
        dt, db = after[top] - before[top], after["bass"] - before["bass"]
        if abs(dt) > 2 and dt * db > 0 and (after[top] - after["bass"]) % 12 in (0, 7):
            return False
    for role in ("alto", "tenor"):
        if role in before and role in after:
            leap = abs(after[role] - before[role])
            if leap == 6 or leap > 9:
                return False
    if ("alto" in before) != ("alto" in after) or ("tenor" in before) != ("tenor" in after):
        if any(abs(a - b) == 6 for k, a in before.items() for j, b in after.items()
               if k in ("alto", "tenor") and j in ("alto", "tenor")):
            return False
    return True


def leading_tones(tonic, mode):
    from music21 import key
    from .notation import notation_key

    ks = key.KeySignature(notation_key(tonic, mode).sharps)
    return tuple(sorted({(tonic + 11) % 12,
                         ks.asKey("major").getLeadingTone().pitchClass,
                         ks.asKey("minor").getLeadingTone().pitchClass}))


def harmonic_pcs(h):
    return {(h.root + x) % 12 for x in QUALITIES[h.quality]}


def harmony_at(harmonies, time):
    return next((h for h in harmonies if h.start <= time + EPS < h.end), None)


def strong_beat(meters, time):
    start, num, den = next(m for m in reversed(meters) if m[0] <= time + EPS)
    beat = 4 / den
    position = (time - start) % (num * beat)
    group = (3 * beat if den == 8 and num >= 6 and num % 3 == 0 else
             2 * beat if num == 4 else 3 * beat if num == 3 else beat)
    return abs(position / group - round(position / group)) < EPS


def voice_lanes(notes):
    """Retain named voices; split chordal source roles into nonoverlapping lanes."""
    groups = defaultdict(list)
    for n in notes:
        groups[(n.part, n.role)].append(n)
    lanes = {}
    for key, values in groups.items():
        built = []
        for n in sorted(values, key=lambda n: (n.start, n.pitch)):
            eligible = [lane for lane in built if lane[-1].end <= n.start + EPS]
            lane = min(eligible, key=lambda lane: abs(lane[-1].pitch - n.pitch), default=None)
            if lane is None:
                lane = []
                built.append(lane)
            lane.append(n)
        for i, lane in enumerate(built):
            lanes[(*key, i)] = lane
    return lanes


def sounding(lane, time):
    return next((n for n in lane if n.start <= time + EPS < n.end), None)


def line_issues(line, accompaniment, harmonies, meters):
    """Check held notes at harmony changes as well as new attacks."""
    issues, classifications = [], []
    line = sorted(line, key=lambda n: n.start)
    lanes = voice_lanes(accompaniment)
    def motion(old_n, old, n, current, time):
        findings = []
        for k, a in current.items():
            b = old.get(k)
            if a and b and parallel(old_n.pitch, b.pitch, n.pitch, a.pitch):
                findings.append({"code": "countervoice_parallel", "beat": time, "against": str(k)})
        old_pitches = [x.pitch for x in old.values() if x]
        new_pitches = [x.pitch for x in current.values() if x]
        if old_pitches and new_pitches and old_n.pitch >= max(old_pitches) and n.pitch >= max(new_pitches):
            b1, b2 = min(old_pitches), min(new_pitches)
            dt, db = n.pitch - old_n.pitch, b2 - b1
            if abs(dt) > 2 and dt * db > 0 and (n.pitch - b2) % 12 in (0, 7) and (old_n.pitch - b1) % 12 != (n.pitch - b2) % 12:
                findings.append({"code": "countervoice_hidden_perfect", "beat": time})
        return findings
    times = sorted({t for n in [*line, *accompaniment] for t in (n.start, n.end)}
                   | {t for h in harmonies for t in (h.start, h.end)})
    previous = None
    for time in times:
        n = sounding(line, time)
        current = {k: sounding(lane, time) for k, lane in lanes.items()}
        if previous and n:
            old_n, old = previous
            if old_n:
                issues.extend(motion(old_n, old, n, current, time))
        previous = n, current
        if n is None:
            continue
        h = harmony_at(harmonies, time)
        if h is None:
            # A melody pickup can intentionally have no harmony underneath.
            continue
        if n.pitch % 12 in harmonic_pcs(h):
            continue
        i = line.index(n)
        before = line[i - 1] if i else None
        after = line[i + 1] if i + 1 < len(line) else None
        adjoining = (before and after and abs(before.end - n.start) < EPS
                     and abs(n.end - after.start) < EPS)
        nh = harmony_at(harmonies, after.start) if after else None
        ph = harmony_at(harmonies, before.start) if before else None
        resolves = (after and nh and after.pitch % 12 in harmonic_pcs(nh)
                    and 0 < abs(after.pitch - n.pitch) <= 2)
        prepared = (before and ph and before.pitch % 12 in harmonic_pcs(ph))
        kind = None
        if adjoining and resolves and prepared:
            if before.pitch == n.pitch and after.pitch < n.pitch:
                kind = "suspension"
            elif not strong_beat(meters, n.start) and n.duration <= 1.5:
                if 0 < abs(n.pitch - before.pitch) <= 2:
                    if (n.pitch - before.pitch) * (after.pitch - n.pitch) > 0:
                        kind = "passing"
                    elif before.pitch == after.pitch:
                        kind = "neighbour"
        if kind:
            classifications.append({"beat": time, "kind": kind})
        else:
            issues.append({"code": "unresolved_countervoice_dissonance", "beat": time,
                           "pitch": n.pitch})
    # Match the existing STUK controller's attack-to-attack policy as well.
    # A short written breath alone must not conceal consecutive perfect intervals.
    previous = None
    attacks = sorted({n.start for n in [*line, *accompaniment]})
    for time in attacks:
        n = sounding(line, time)
        current = {k: sounding(lane, time) for k, lane in lanes.items()}
        if previous and n and previous[0]:
            old_n, old = previous
            for issue in motion(old_n, old, n, current, time):
                if issue not in issues:
                    issues.append(issue)
        previous = n, current
    for a, b in pairwise(line):
        h, nh = harmony_at(harmonies, a.start), harmony_at(harmonies, b.start)
        if not h or not nh or b.start - a.end > EPS:
            continue
        # Active thirds in a dominant resolving up a fourth are leading tones.
        leading = (4 in QUALITIES[h.quality] and (nh.root - h.root) % 12 == 5
                   and a.pitch % 12 == (h.root + 4) % 12)
        seventh = len(QUALITIES[h.quality]) >= 4 and (a.pitch - h.root) % 12 in (10, 11)
        if leading and b.pitch - a.pitch not in (0, 1):
            issues.append({"code": "countervoice_leading_tone", "beat": b.start})
        if seventh and b.pitch - a.pitch not in (0, -1, -2):
            issues.append({"code": "countervoice_seventh", "beat": b.start})
    return {"valid": not issues, "issues": issues, "classified_dissonances": classifications}


def hand_assignment(notes):
    """Plan whole-note hand assignments across time, retaining held-note continuity."""
    from .chorale_hand_plan import assign_hands

    piano = [n for n in notes if n.part == "piano"]
    hands = assign_hands(piano, keep_melody_right=False,
                         pinned_roles={"bass": "LH", "descant": "RH"},
                         preferred_roles={"tenor": "RH"})
    if hands is None:
        return None
    return {f"{n.role}:{n.start:.7f}:{n.pitch}": hand for n, hand in zip(piano, hands)}


def _slots(melody, seed):
    """Complement the sung rhythm, with a short breath at each phrase end."""
    rng = random.Random(seed)
    result = []
    left = 0
    for pi, end in enumerate(melody.phrases):
        notes = [n for n in melody.notes if left <= n.start < end]
        if not notes:
            left = end
            continue
        cursor = notes[0].start
        breath = min(0.5, (end - cursor) / 8)
        while cursor < end - breath - EPS:
            sung = next((n for n in notes if n.start <= cursor + EPS < n.end), None)
            active = sung and sung.duration < 2
            duration = rng.choice((1.5, 2.0)) if active else rng.choice((0.5, 1.0))
            duration = min(duration, end - breath - cursor)
            result.append((cursor, duration, pi))
            cursor += duration
        left = end
    return result


def _countervoice(arrangement, melody, profile="flute", seed=0, beam_width=32):
    """Return an independently checked variant; never return a weakened fallback."""
    if profile not in ("flute", "piano"):
        raise ValueError("Tegenstemprofiel moet flute of piano zijn.")
    offset = arrangement.melody_offset
    low, high = (62, 76) if profile == "flute" else (74, 79)
    part = "flute" if profile == "flute" else "piano"
    leading = leading_tones(melody.tonic, melody.mode)
    source = extract_motifs(melody)[0]
    contour = [t.degree - source.tones[0].degree for t in source.tones]
    slots = []
    for start, duration, phrase in _slots(melody, seed):
        cuts = sorted({start, start + duration,
                       *(h.start - offset for h in arrangement.harmony
                         if start + EPS < h.start - offset < start + duration - EPS),
                       *(h.end - offset for h in arrangement.harmony
                         if start + EPS < h.end - offset < start + duration - EPS)})
        slots.extend((a, b - a, phrase) for a, b in pairwise(cuts))
    base = [n for n in arrangement.notes if n.role != "descant"]
    removed = []
    if profile == "piano":
        # Replace upper accompaniment locally, preserving every bass/melody event.
        removed = [n for n in base if n.role in ("alto", "tenor", "inner")
                   and offset <= n.start < offset + melody.length]
        base = [n for n in base if n not in removed]
    beam = [(0.0, [])]
    check_cache = {}
    rng = random.Random(seed)
    for si, (start, duration, phrase) in enumerate(slots):
        time, end = start + offset, start + offset + duration
        overlapping = [h for h in arrangement.harmony if h.start < end - EPS and h.end > time + EPS]
        tones = set(range(low, high + 1))
        for h in overlapping:
            tones &= {p for p in tones if p % 12 in harmonic_pcs(h)}
        # Silence is explicit in the written rhythm, not an escape from failed pitch search.
        extensions = []
        sung = next((n for n in melody.notes if n.start <= start + EPS < n.end), None)
        center = (sung.pitch + 4 if sung else (low + high) / 2)
        center = min(high - 2, max(low + 2, center))
        degree, _ = scale_position(round(center), melody.tonic, melody.mode)
        target = scale_pitch(degree - contour[si % len(contour)], melody.tonic, melody.mode)
        for cost, path in beam:
            for pitch in tones:
                n = Event(pitch, time, duration, 78, "descant", part)
                if profile == "piano":
                    if sung and not 0 < pitch - sung.pitch <= 12:
                        continue
                    if pitch % 12 in leading and any(p.pitch % 12 == pitch % 12
                        and p.start < n.end - EPS and p.end > n.start + EPS for p in base):
                        continue
                trial = [*path, n]
                key = (si, path[-1].pitch if path else None, pitch)
                if key not in check_cache:
                    first = trial[-2].start if len(trial) > 1 else n.start
                    local_base = [p for p in base if p.start < n.end - EPS and p.end > first + EPS]
                    local_harmony = [h for h in arrangement.harmony if h.start < n.end - EPS and h.end > first + EPS]
                    check_cache[key] = line_issues(trial[-2:], local_base, local_harmony, arrangement.meters)
                report = check_cache[key]
                if not report["valid"]:
                    continue
                if profile == "piano" and hand_assignment([n, *(p for p in base if p.start < n.end - EPS and p.end > n.start + EPS)]) is None:
                    continue
                move = pitch - path[-1].pitch if path else 0
                if abs(move) > 7:
                    continue
                local = abs(pitch - target) * 0.15 + abs(pitch - center) * 0.05
                if path:
                    local += abs(move) * 0.1 + 0.6 * (move == 0)
                    prev_sung = next((m for m in melody.notes if m.start + offset <= path[-1].start + EPS < m.end + offset), None)
                    if sung and prev_sung:
                        local -= 0.5 * (move * (sung.pitch - prev_sung.pitch) < 0)
                    if len(path) >= 2 and abs(path[-1].pitch - path[-2].pitch) > 4:
                        local += 0 if move * (path[-1].pitch - path[-2].pitch) < 0 and abs(move) <= 2 else 2
                extensions.append((cost + local + rng.uniform(-0.12, 0.12), trial))
        if not extensions:
            exc = CompositionError(f"Geen geldige {profile}-tegenstem bij tel {start:g}; zoekbreedte {beam_width}.")
            exc.beat = time
            raise exc
        distinct = {}
        for cost, path in sorted(extensions, key=lambda row: row[0]):
            distinct.setdefault(tuple(n.pitch for n in path[-2:]), (cost, path))
        beam = list(distinct.values())[:beam_width]
    for cost, line in beam:
        check = line_issues(line, base, arrangement.harmony, arrangement.meters)
        if not check["valid"]:
            continue
        embellishments = []
        for i in reversed(range(len(line) - 1)):
            a, b = line[i:i + 2]
            if i % 3 != seed % 3 or a.duration < 1 or abs(a.end - b.start) > EPS:
                continue
            if abs(b.pitch - a.pitch) not in (3, 4):
                continue
            time = a.end - 0.5
            if strong_beat(arrangement.meters, time):
                continue
            candidates = [p for p in range(min(a.pitch, b.pitch) + 1, max(a.pitch, b.pitch))
                          if (p - melody.tonic) % 12 in MODES[melody.mode]
                          and abs(p - a.pitch) <= 2 and abs(b.pitch - p) <= 2]
            for pitch in candidates:
                proposed = [*line[:i], replace(a, duration=a.duration - 0.5),
                            replace(a, pitch=pitch, start=time, duration=0.5), *line[i + 1:]]
                if line_issues(proposed, base, arrangement.harmony, arrangement.meters)["valid"] and (
                    profile != "piano" or hand_assignment([*base, *proposed]) is not None
                ):
                    line = proposed
                    embellishments.append({"beat": time, "pitch": pitch, "kind": "passing_or_chordal_connection"})
                    break
        # Restore optional inner notes only where both the line and the hands permit them.
        restored = []
        def importance(n):
            h = harmony_at(arrangement.harmony, n.start)
            third = h and (n.pitch - h.root) % 12 in (3, 4)
            return n.start, not third, -n.pitch
        for original in sorted(removed, key=importance):
            for shift in (0, 12, -12, 24):
                n = replace(original, pitch=original.pitch + shift, role="inner")
                sung_notes = [p for p in base if p.role == "melody" and p.start < n.end - EPS and p.end > n.start + EPS]
                upper_notes = [p for p in line if p.start < n.end - EPS and p.end > n.start + EPS]
                if not sung_notes or not upper_notes:
                    continue
                if any(not 0 < n.pitch - p.pitch <= 12 for p in sung_notes):
                    continue
                if any(not 0 < p.pitch - n.pitch <= 12 for p in upper_notes):
                    continue
                if any(sum(p.start <= t + EPS < p.end for p in [*restored, n]) > 1
                       for t in {n.start, *(p.start for p in restored if p.start < n.end and p.end > n.start)}):
                    continue
                optional = sorted([*restored, n], key=lambda p: p.start)
                if n.pitch % 12 in leading and any(p.pitch % 12 == n.pitch % 12
                    and p.start < n.end - EPS and p.end > n.start + EPS for p in [*base, *line]):
                    continue
                if any(abs(a.pitch - b.pitch) == 6 or abs(a.pitch - b.pitch) > 9 for a, b in pairwise(optional)):
                    continue
                if not line_issues(optional, [*base, *line], arrangement.harmony, arrangement.meters)["valid"]:
                    continue
                proposed = [*base, *restored, n]
                if line_issues(line, proposed, arrangement.harmony, arrangement.meters)["valid"] and hand_assignment([*proposed, *line]) is not None:
                    restored.append(n)
                    break
        restored_source_count = len(restored)
        if profile == "piano":
            # A long source inner note may not fit beneath a moving descant.
            # Fill its usable subspans separately, preferring the chord third.
            cuts = sorted({t for n in [*base, *line, *restored] for t in (n.start, n.end)}
                          | {t for h in arrangement.harmony for t in (h.start, h.end)})
            for a, b in pairwise(cuts):
                if any(n.start <= a + EPS < n.end for n in restored):
                    continue
                sung = next((n for n in base if n.role == "melody" and n.start <= a + EPS < n.end), None)
                upper = sounding(line, a)
                h = harmony_at(arrangement.harmony, a)
                if not sung or not upper or not h:
                    continue
                active = [n for n in [*base, *line] if n.start <= a + EPS < n.end]
                thirds = {(h.root + i) % 12 for i in QUALITIES[h.quality] if i in (3, 4)}
                if not thirds or any(n.pitch % 12 in thirds for n in active):
                    continue
                pitches = [p for p in range(sung.pitch + 1, upper.pitch)
                           if p % 12 in thirds and upper.pitch - p <= 12
                           and p - sung.pitch <= 12]
                pitches.sort(key=lambda p: (not ((p - h.root) % 12 in (3, 4)),
                                            min((abs(p - n.pitch) for n in restored if n.end <= a + EPS), default=0)))
                for pitch in pitches:
                    if pitch % 12 in leading and any(n.pitch % 12 == pitch % 12 for n in active):
                        continue
                    n = Event(pitch, a, b - a, 62, "inner")
                    optional = sorted([*restored, n], key=lambda x: x.start)
                    if any(abs(x.pitch - y.pitch) == 6 or abs(x.pitch - y.pitch) > 9 for x, y in pairwise(optional)):
                        continue
                    if not line_issues(optional, [*base, *line], arrangement.harmony, arrangement.meters)["valid"]:
                        continue
                    if not line_issues(line, [*base, *optional], arrangement.harmony, arrangement.meters)["valid"]:
                        continue
                    if hand_assignment([*base, *optional, *line]) is not None:
                        restored.append(n)
                        break
        notes = sorted([*base, *restored, *line], key=lambda n: (n.start, n.pitch, n.part))
        hands = hand_assignment(notes) if profile == "piano" else None
        if profile == "piano" and hands is None:
            continue
        diagnostics = {**arrangement.diagnostics, "countervoice": {
            "profile": profile, "seed": seed, "range": [low, high], "source_motif": source.data(),
            "check": line_issues(line, [*base, *restored], arrangement.harmony, arrangement.meters),
            "embellishments": embellishments, "beam_width": beam_width, "score": cost,
            "removed_inner_notes": len(removed) - restored_source_count,
            "new_inner_fragments": len(restored) - restored_source_count,
            "harmonic_changes": [], "listening_acceptance": "pending"}}
        if hands is not None:
            diagnostics["hand_assignment"] = hands
        return replace(arrangement, notes=notes, seed=seed, diagnostics=diagnostics)
    raise CompositionError("De volledige tegenstem voldoet niet aan de eindcontrole.")


def _repairs_at(arrangement, melody, beat):
    """Offer local inversions first, then modal chords, without touching the melody."""
    from .engine import chord_options
    from .thematic import _voicings

    h = harmony_at(arrangement.harmony, beat)
    if h is None:
        return []
    sung = [n for n in arrangement.notes if n.role == "melody" and n.start < h.end and n.end > h.start]
    if not sung:
        return []
    options = [(h.root, h.quality)]
    scale = {(melody.tonic + x) % 12 for x in MODES[melody.mode]}
    for r, q in chord_options(melody):
        if q not in ("major", "minor", "sus2", "sus4", "add9", "min7", "maj7"):
            continue
        if {(r + x) % 12 for x in QUALITIES[q]} <= scale and (r, q) not in options:
            options.append((r, q))
    before = {n.role: n.pitch for n in arrangement.notes if n.start < h.start and n.end >= h.start - EPS and n.role in ("bass", "tenor", "alto", "melody")}
    after = {n.role: n.pitch for n in arrangement.notes if n.start <= h.end + EPS < n.end and n.role in ("bass", "tenor", "alto", "melody")}
    candidates = []
    for root, quality in options:
        pcs = {(root + x) % 12 for x in QUALITIES[quality]}
        if any(n.pitch % 12 not in pcs for n in sung):
            continue
        for local_cost, voices in _voicings(root, quality, min(n.pitch for n in sung), 4, False, leading_tones(melody.tonic, melody.mode)):
            voices = {("melody" if k == "motif" else k): p for k, p in voices.items()}
            if root == h.root and quality == h.quality and voices["bass"] == h.bass:
                continue
            if not transition_valid(before, voices) or not transition_valid(voices, after):
                continue
            revised = []
            for n in arrangement.notes:
                if n.role in ("melody", "motif", "descant") or n.part != "piano" or n.start >= h.end or n.end <= h.start:
                    revised.append(n)
                    continue
                if n.start < h.start:
                    revised.append(replace(n, duration=h.start - n.start))
                if n.end > h.end:
                    revised.append(replace(n, start=h.end, duration=n.end - h.end))
            revised.extend(Event(p, h.start, h.end - h.start, 62, role) for role, p in voices.items() if role != "melody")
            replacement = replace(h, root=root, quality=quality, bass=voices["bass"], inner=(voices["tenor"], voices["alto"]))
            hs = [replacement if old is h else old for old in arrangement.harmony]
            change = {"start": h.start, "end": h.end,
                      "before": {"root": h.root, "quality": h.quality, "bass": h.bass},
                      "after": {"root": root, "quality": quality, "bass": voices["bass"]}}
            cost = 3 * ((root, quality) != (h.root, h.quality)) + abs(voices["bass"] - h.bass) * 0.05 + local_cost
            candidates.append((cost, replace(arrangement, notes=sorted(revised, key=lambda n: (n.start, n.pitch)), harmony=hs), change))
    return sorted(candidates, key=lambda row: row[0])[:12]


def _local_repairs(arrangement, melody, beat):
    options = _repairs_at(arrangement, melody, beat)
    current = harmony_at(arrangement.harmony, beat)
    if current:
        previous = max((h for h in arrangement.harmony if h.end <= current.start + EPS),
                       key=lambda h: h.end, default=None)
        if previous and current.start - previous.end < EPS:
            options.extend(_repairs_at(arrangement, melody, previous.start))
    return options


def add_countervoice(arrangement, melody, profile="flute", seed=0, beam_width=32):
    current, changes = arrangement, []
    try:
        return _countervoice(current, melody, profile, seed, beam_width)
    except CompositionError as exc:
        failure = exc
    # Bounded local alternatives are reported, never hidden as a simplified fallback.
    seen = set()
    for _ in range(8):
        if not hasattr(failure, "beat"):
            break
        progressed, preparation = None, None
        for _, trial, change in _local_repairs(current, melody, failure.beat):
            token = tuple((h.start, h.end, h.root, h.quality, h.bass) for h in trial.harmony)
            if token in seen:
                continue
            seen.add(token)
            try:
                result = _countervoice(trial, melody, profile, seed, beam_width)
                result.diagnostics["countervoice"]["harmonic_changes"] = [*changes, change]
                return result
            except CompositionError as exc:
                if getattr(exc, "beat", -1) > failure.beat and progressed is None:
                    progressed = trial, change, exc
                    break
                if getattr(exc, "beat", -1) == failure.beat and change["start"] < failure.beat and preparation is None:
                    preparation = trial, change, exc
        if progressed is None:
            progressed = preparation
        if progressed is None:
            break
        current, change, failure = progressed
        changes.append(change)
    raise failure
