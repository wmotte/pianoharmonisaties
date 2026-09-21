"""Traceable cadence contexts from training scores, separate from crop endings."""

import json
import math
from collections import defaultdict
from copy import deepcopy
from itertools import combinations, pairwise
from pathlib import Path

from music21 import converter, expressions

from .chorale_corpus import crop_events, part_events, separate_melody
from .chorale_model import _hand_split
from .corpus import digest
from .profile import identify_chord
from .score_style import explicit_sections, score_timeline


def collect(model, entries, historical_path, splits_path):
    historical = {x["title"]: x for x in json.loads(Path(historical_path).read_text())}
    splits = json.loads(Path(splits_path).read_text())
    rows, rejected = [], []
    for entry in entries:
        if entry["source_id"] not in model["training_ids"]:
            continue
        if entry["split"] != "train":
            raise ValueError("Cadence source is not a training entry.")
        path = Path(entry["source_path"])
        if digest(path) != entry["source_sha256"]:
            raise ValueError("Cadence source changed since corpus selection.")
        score = converter.parse(path)
        timeline = score_timeline(score)
        measures = timeline["measures"]
        explicit = explicit_sections(
            timeline, path.stem, splits, float(score.duration.quarterLength)
        )
        ranges = [(x["start"], x["end"]) for x in explicit if x["name"] == "Koraal"]
        boundary = "explicit_section"
        hist = historical.get(path.stem)
        if not ranges and hist and hist["bars"] == len(measures):
            ranges = [
                (
                    measures[x["start"]]["start"],
                    measures[x["end"]]["start"]
                    if x["end"] < len(measures)
                    else float(score.duration.quarterLength),
                )
                for x in hist["sections"]
                if x["name"].startswith("koraal")
                and x["end"] - x["start"] >= 4
                and x["start"] > 0
            ]
            boundary = "historical_section_proposal"
        right, left = map(part_events, score.parts)
        for n in score.parts[0].recurse().notes:
            if not any(isinstance(x, expressions.Fermata) for x in n.expressions):
                continue
            a = float(n.getOffsetInHierarchy(score.parts[0]))
            b = a + float(n.quarterLength)
            region = next(((lo, hi) for lo, hi in ranges if lo <= a and b <= hi), None)
            if region is None:
                continue
            start = max(region[0], b - 24)
            try:
                top = separate_melody(
                    crop_events(right, start, b), crop_events(left, start, b)
                )
            except ValueError as error:
                rejected.append(
                    {"source_id": entry["source_id"], "end": b, "reason": str(error)}
                )
                continue
            if abs(top[-1][2] - (b - start)) > 1e-6 or top[-1][0] != max(
                p.midi for p in n.pitches
            ):
                rejected.append(
                    {
                        "source_id": entry["source_id"],
                        "end": b,
                        "reason": "Fermata is not on the extracted top voice.",
                    }
                )
                continue
            ps = sorted({p for p, c, d in right + left if c < b - 1e-6 < d})
            context = score.measures(
                max(1, n.measureNumber - 5), n.measureNumber
            ).analyze("key")
            tonic, mode = context.tonic.pitchClass, context.mode
            if entry["tune"] == "psalm_37":
                tonic, mode = 0, "dorian"
            chord = identify_chord(ps)
            # Retain incomplete observations for audit, but do not invent roots.
            rows.append(
                {
                    "source_id": entry["source_id"],
                    "group": entry["group"],
                    "source_path": str(path),
                    "source_sha256": entry["source_sha256"],
                    "start": start,
                    "end": b,
                    "measure": n.measureNumber,
                    "boundary_method": boundary,
                    "tonic": tonic,
                    "mode": mode,
                    "key_method": "explicit C dorian"
                    if entry["tune"] == "psalm_37"
                    else "inferred local six-measure context",
                    "pitches": ps,
                    "melody": [list(x) for x in top[-4:]],
                    "degree": (top[-1][0] - tonic) % 12,
                    "root_degree": (chord[0] - tonic) % 12 if chord else None,
                    "quality": chord[1] if chord else None,
                    "status": "provisional_transcription",
                }
            )
    result = deepcopy(model)
    result["decoder"] = "cadence_context_v1"
    result["cadence_contexts"] = rows
    result["cadence_rejected"] = rejected
    result["cadence_source_hashes"] = {
        str(historical_path): digest(Path(historical_path)),
        str(splits_path): digest(Path(splits_path)),
    }
    return result


def aligned_cadence_contexts(
    entry, melody, arrangement, canonical, *, allow_root_third=False
):
    """Extract local phrase evidence without repairing mismatched source notes."""
    from .chorale_harmony_audit import VOCABULARY
    from .chorale_harmony_evidence import chord_candidates
    from .genevan_alignment import align

    alignment = align(canonical, melody.notes)
    matches = {
        r["canonical_index"]: r["observed_index"]
        for r in alignment["alignment"]
        if r["kind"] == "match"
    }
    origin = entry["source_start_quarters"]
    contexts, endings, rejected = [], [], []
    for i, note in enumerate(canonical):
        if i + 1 < len(canonical) and note.end >= canonical[i + 1].start:
            continue
        indices = [matches.get(j) for j in range(i - 3, i + 1)]
        if (
            i < 3
            or None in indices
            or indices != list(range(indices[0], indices[0] + 4))
        ):
            rejected.append(
                {
                    "canonical_index": i,
                    "reason": "No exact consecutive four-note melodic context",
                }
            )
            continue
        notes = [melody.notes[j] for j in indices]
        last = notes[-1]
        endings.append((last.pitch, origin + last.start, origin + last.end))
        pitches = sorted(
            {n.pitch for n in arrangement.notes if n.start < last.end - 1e-6 < n.end}
        )
        pcs = {p % 12 for p in pitches}
        complete = [
            (root, quality)
            for root, quality in chord_candidates(pcs)
            if pcs == {(root + x) % 12 for x in VOCABULARY[quality]}
            and quality in ("major", "minor", "dom7")
        ]
        interpretation = {}
        if not complete and allow_root_third and len(pcs) == 2:
            # An observed bass plus its third can suggest a root-position
            # triad without asserting that an absent fifth was played.
            root = min(pitches) % 12
            for third, quality in ((3, "minor"), (4, "major")):
                if pcs == {root, (root + third) % 12}:
                    complete = [(root, quality)]
                    interpretation = {
                        "harmonic_evidence": "root_and_third_only_root_position_assumption",
                        "missing_fifth_pc": (root + 7) % 12,
                    }
        if len(complete) != 1:
            rejected.append(
                {
                    "canonical_index": i,
                    "reason": "No unique complete supported chord",
                    "pitches": pitches,
                }
            )
            continue
        root, quality = complete[0]
        start = notes[0].start
        canonical_final = i == len(canonical) - 1
        next_index = matches.get(i + 1)
        following = melody.notes[next_index] if next_index is not None else None
        contexts.append(
            {
                "source_id": entry["source_id"],
                "group": entry["group"],
                "source_path": entry["source_path"],
                "source_sha256": entry["source_sha256"],
                "start": origin + start,
                "end": origin + last.end,
                "boundary_method": "independently_aligned_Genevan_phrase_end",
                "canonical_index": i,
                "canonical_final": canonical_final,
                "continuation_status": (
                    "canonical_melody_end_not_performance_end"
                    if canonical_final
                    else "aligned_next_melody_note"
                    if following is not None
                    else "next_canonical_note_unmatched"
                ),
                "following_melody": (
                    [following.pitch, origin + following.start, origin + following.end]
                    if following is not None
                    else None
                ),
                "tonic": melody.tonic,
                "mode": melody.mode,
                "pitches": pitches,
                "melody": [(n.pitch, n.start - start, n.end - start) for n in notes],
                "degree": (last.pitch - melody.tonic) % 12,
                "root_degree": (root - melody.tonic) % 12,
                "quality": quality,
                "status": "provisional_transcription_with_aligned_phrase_boundary",
                **interpretation,
            }
        )
    return {
        "contexts": contexts,
        "phrase_endings": endings,
        "rejected": rejected,
        "alignment_counts": alignment["counts"],
        "transpose": alignment["transpose"],
    }


def validate_context_boundaries(model, source_phrase_endings):
    """Filter audited sources against independently aligned phrase-end notes.

    Each supplied source ID maps to absolute (pitch, start, end) tuples.
    Missing source IDs remain unaudited; an empty list approves no contexts.
    This verifies the melodic boundary, not the recorded harmony or timing.
    """
    result = deepcopy(model)
    retained, decisions = [], []
    for row in model.get("cadence_contexts", []):
        source = row["source_id"]
        if source not in source_phrase_endings:
            retained.append(row)
            continue
        last = row["melody"][-1] if row["melody"] else None
        match = last is not None and any(
            pitch == last[0]
            and abs(start - (row["start"] + last[1])) < 1e-6
            and abs(end - (row["start"] + last[2])) < 1e-6
            and abs(end - row["end"]) < 1e-6
            for pitch, start, end in source_phrase_endings[source]
        )
        decisions.append(
            {
                "source_id": source,
                "end": row["end"],
                "accepted": match,
                "reason": "aligned_phrase_end"
                if match
                else "not_an_aligned_phrase_end",
            }
        )
        if match:
            retained.append(row)
    result["cadence_contexts"] = retained
    result["cadence_boundary_validation"] = {
        "audited_sources": sorted(source_phrase_endings),
        "decisions": decisions,
        "scope": "Melodic boundary correspondence; no harmonic gold certification",
    }
    return result


def phrase_goals(melody, model):
    goals = [propose(melody, end, model) for end in melody.fermatas]
    if model.get("phrase_cadences"):
        for boundary in melody.phrases:
            if boundary >= melody.length or any(
                n.start < boundary < n.end for n in melody.notes
            ):
                continue
            notes = [n for n in melody.notes if n.end <= boundary]
            if not notes or any(abs(notes[-1].end - f) < 1e-6 for f in melody.fermatas):
                continue
            goals.append(
                propose(melody, notes[-1].end, model, phrase_boundary=boundary)
            )
    return [g for g in goals if g is not None]


def propose(melody, end, model, exclude_group=None, *, phrase_boundary=None):
    """Rank complete observed cadences by their preceding melodic contour.

    Mode transfer is a marked backoff: major/minor tonic functions can transfer,
    while their thirds must be adapted. Never transfer chromatic pitch offsets.
    """
    explicit_phrase = (
        phrase_boundary is not None
        and phrase_boundary in melody.phrases
        and phrase_boundary < melody.length
        and not any(n.start < phrase_boundary < n.end for n in melody.notes)
        and end
        == max((n.end for n in melody.notes if n.end <= phrase_boundary), default=-1)
    )
    if not explicit_phrase and not any(abs(end - f) < 1e-6 for f in melody.fermatas):
        return None
    notes = [n for n in melody.notes if n.end <= end + 1e-6][-4:]
    if len(notes) < 3 or abs(notes[-1].end - end) > 1e-6:
        return None
    degree = (notes[-1].pitch - melody.tonic) % 12
    contours = [b.pitch - a.pitch for a, b in pairwise(notes)]
    options = []
    interval_sources = set()
    for row in model.get("cadence_contexts", []):
        if row["group"] == exclude_group or row["root_degree"] is None:
            continue
        root, quality = row["root_degree"], row["quality"]
        transferred = row["mode"] != melody.mode
        modal_degree = False
        if (
            model.get("cadence_scale_degree_transfer")
            and transferred
            and root in (0, 7)
            and row["mode"] in ("major", "minor")
            and melody.mode in ("major", "minor")
        ):
            from .chorale_phrases import CHORDS
            from .model import MODES

            source_scale, target_scale = MODES[row["mode"]], MODES[melody.mode]
            target_quality = (
                ("minor" if melody.mode == "minor" else "major")
                if root == 0
                else "major"
            )
            modal_degree = (
                row["degree"] in source_scale
                and degree in target_scale
                and source_scale.index(row["degree"]) == target_scale.index(degree)
                and (degree - root) % 12 in CHORDS[target_quality]
            )
        interval_transfer = row["degree"] != degree and not modal_degree
        if interval_transfer:
            if (
                not model.get("cadence_interval_transfer")
                or row.get("boundary_method")
                != "independently_aligned_Genevan_phrase_end"
            ):
                continue
            from .chorale_phrases import CHORDS
            from .model import MODES

            root = (degree + root - row["degree"]) % 12
            if quality not in CHORDS or not {
                (root + i) % 12 for i in CHORDS[quality]
            } <= set(MODES[melody.mode]):
                continue
            interval_sources.add((row["source_id"], row["end"]))
        if transferred and not interval_transfer:
            if (
                root not in (0, 7)
                or row["mode"] not in ("major", "minor")
                or melody.mode not in ("major", "minor")
            ):
                continue
            quality = (
                ("minor" if melody.mode == "minor" else "major")
                if root == 0
                else "major"
            )
        source = row["melody"]
        source_contour = [b[0] - a[0] for a, b in pairwise(source)]
        count = min(len(contours), len(source_contour))
        distance = (
            sum(
                min(12, abs(a - b)) / 12
                for a, b in zip(contours[-count:], source_contour[-count:])
            )
            / count
        )
        # Match the arrival and its length, rather than guessing closure from
        # the fact that an excerpt happens to end here.
        distance += 0.3 * abs(
            math.log2(notes[-1].duration / (source[-1][2] - source[-1][1]))
        )
        distance += 0.35 * transferred
        distance += 0.35 * interval_transfer
        options.append((distance, root, quality, row, transferred))
    if not options:
        return None
    options.sort(key=lambda x: x[0])
    best = options[0]
    if best[0] > 1.1:
        return None
    support = defaultdict(float)
    for distance, root, quality, _, _ in options[:5]:
        support[(root, quality)] += math.exp(-3 * distance)
    target = max(support, key=support.get)
    evidence = next(x for x in options if x[1:3] == target)
    result = {
        "end": end,
        "root_degree": target[0],
        "quality": target[1],
        "support_fraction": support[target] / sum(support.values()),
        "supporting_contexts": len(options[:5]),
        "supporting_groups": len({x[3]["group"] for x in options[:5]}),
        "distance": evidence[0],
        "source_id": evidence[3]["source_id"],
        "source_end": evidence[3]["end"],
        "mode_transfer": evidence[4],
        "interval_transfer": (evidence[3]["source_id"], evidence[3]["end"])
        in interval_sources,
        "phrase_boundary": phrase_boundary if explicit_phrase else None,
        "status": "inferred_cadence_goal_not_ground_truth",
    }
    if "harmonic_evidence" in evidence[3]:
        result["harmonic_evidence"] = evidence[3]["harmonic_evidence"]
    if (
        model.get("preserve_cadence_bass")
        and evidence[3].get("pitches")
        and "tonic" in evidence[3]
    ):
        row = evidence[3]
        bass_degree = (
            min(row["pitches"]) - row["tonic"] + target[0] - row["root_degree"]
        ) % 12
        from .chorale_phrases import CHORDS

        if model.get("cadence_scale_degree_transfer"):
            bass_degree = transferred_bass_degree(row, target[0], target[1])
        if (
            bass_degree is not None
            and (bass_degree - target[0]) % 12 in CHORDS[target[1]]
        ):
            result["bass_degree"] = bass_degree
    if model.get("cadence_alternatives"):
        alternatives = []
        for (root, quality), weight in sorted(support.items()):
            item = next(x for x in options if x[1:3] == (root, quality))
            row = item[3]
            alternative = {
                "root_degree": root,
                "quality": quality,
                "support_fraction": weight / sum(support.values()),
                "source_id": row["source_id"],
                "source_end": row["end"],
                "distance": item[0],
            }
            if "harmonic_evidence" in row:
                alternative["harmonic_evidence"] = row["harmonic_evidence"]
            if (
                model.get("preserve_cadence_bass")
                and row.get("pitches")
                and "tonic" in row
            ):
                from .chorale_phrases import CHORDS

                bass = (
                    min(row["pitches"]) - row["tonic"] + root - row["root_degree"]
                ) % 12
                if model.get("cadence_scale_degree_transfer"):
                    bass = transferred_bass_degree(row, root, quality)
                if bass is not None and (bass - root) % 12 in CHORDS[quality]:
                    alternative["bass_degree"] = bass
            alternatives.append(alternative)
        result["alternatives"] = alternatives
    return result


def transferred_bass_degree(row, root, quality):
    """Keep the chord member in the bass when adapting major/minor thirds."""
    from .chorale_phrases import CHORDS

    source = CHORDS.get(row["quality"], ())
    target = CHORDS.get(quality, ())
    interval = (min(row["pitches"]) - row["tonic"] - row["root_degree"]) % 12
    if interval not in source or source.index(interval) >= len(target):
        return None
    return (root + target[source.index(interval)]) % 12


def terminal_pitch_classes(top, events, root, quality):
    """Borrow chord tones only from the uninterrupted compatible terminal span.

    A complete chord with another root, an outside tone or an accompaniment
    gap ends the span. This is evidence for a target, not a chord label for
    the whole held melody note. Actual terminal bass is assessed separately.
    """
    from .chorale_phrases import CHORDS

    target = {(root + interval) % 12 for interval in CHORDS[quality]}
    times = sorted(
        {0.0, 1.0, *(t for _, a, b, _ in events for t in (a, b) if 0 < t < 1)}
    )
    windows = []
    for a, b in pairwise(times):
        middle = (a + b) / 2
        pitches = [
            top - offset for offset, start, end, _ in events if start <= middle < end
        ]
        windows.append((pitches, {top % 12, *(p % 12 for p in pitches)}))
    result = set(windows[-1][1])
    for pitches, sounding in reversed(windows):
        if not pitches or not sounding <= target:
            break
        complete_roots = {
            candidate
            for candidate in range(12)
            for intervals in CHORDS.values()
            if sounding == {(candidate + interval) % 12 for interval in intervals}
        }
        if complete_roots and root not in complete_roots:
            break
        result.update(sounding)
    return result


def cadence_mixture_penalty(
    top, pitches, tonic, alternatives, *, events=None, defining_tones=False
):
    """Marginalize over supported destinations instead of preselecting one."""
    from .chorale_phrases import CHORDS

    total = sum(a["support_fraction"] for a in alternatives)
    if not alternatives or total <= 0:
        raise ValueError("Cadence alternatives require positive support")
    likelihood = 0.0
    sounding = {top % 12, *(p % 12 for p in pitches)}
    for alternative in alternatives:
        weight = alternative["support_fraction"]
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("Invalid cadence support")
        root = (tonic + alternative["root_degree"]) % 12
        pcs = {(root + i) % 12 for i in CHORDS[alternative["quality"]]}
        observed = (
            terminal_pitch_classes(top, events, root, alternative["quality"])
            if events is not None
            else sounding
        )
        required = pcs - {(root + 7) % 12} if defining_tones else pcs
        mismatch = len(required - observed) + len(observed - pcs)
        bass = (tonic + alternative.get("bass_degree", alternative["root_degree"])) % 12
        distance = 1.1 * mismatch + 0.3 * (not pitches or min(pitches) % 12 != bass)
        likelihood += weight / total * math.exp(-distance)
    return -math.log(likelihood)


def cadence_voicings(top, tonic, goal):
    intervals = {"major": (0, 4, 7), "minor": (0, 3, 7), "dom7": (0, 4, 7, 10)}.get(
        goal["quality"]
    )
    if intervals is None:
        return []
    root = (tonic + goal["root_degree"]) % 12
    pcs = {(root + x) % 12 for x in intervals}
    bass_pc = (tonic + goal.get("bass_degree", goal["root_degree"])) % 12
    if bass_pc not in pcs:
        return []
    if top % 12 not in pcs:
        return []
    options = []
    for bass in range(max(28, top - 36), top - 11):
        if bass % 12 != bass_pc:
            continue
        upper = [p for p in range(max(bass + 3, top - 16), top) if p % 12 in pcs]
        for inner in combinations(upper, len(pcs - {bass_pc, top % 12})):
            ps = (bass, *inner)
            if {top % 12, *(p % 12 for p in ps)} != pcs or _hand_split(ps, top) is None:
                continue
            options.append(ps)
    return options


def cadence_choices(note, melody, model, target, base_cost):
    from .chorale_phrases import CHORDS, patterned_voicing

    result = []
    if target["quality"] not in CHORDS:
        return result
    root = (melody.tonic + target["root_degree"]) % 12
    pcs = {(root + i) % 12 for i in CHORDS[target["quality"]]}
    for pitches in cadence_voicings(note.pitch, melody.tonic, target):
        cost = base_cost + 0.025 * abs(note.pitch - pitches[0] - model["bass_gap"])
        result.append(([(note.pitch - p, 0, 1, False) for p in pitches], cost, -1))
        if model.get("cadence_figures"):
            for events, discount, identity in patterned_voicing(
                note, melody, pitches, pcs, model
            ):
                result.append((events, cost - discount, identity))
    return result


def unsupported_cadence_six_four(top, pitches, tonic, targets):
    """Reject an unsupported triadic second inversion at a planned rest point.

    Other harmonies remain outside this check. Explicit source evidence for
    the same inversion overrides it; this is not a universal inversion ban.
    """
    if not pitches:
        return False
    sounding = {top % 12, *(p % 12 for p in pitches)}
    bass = min(pitches) % 12
    relevant = []
    for target in targets:
        quality = target["quality"]
        if quality not in ("major", "minor"):
            continue
        root = (tonic + target["root_degree"]) % 12
        pcs = {root, (root + (4 if quality == "major" else 3)) % 12, (root + 7) % 12}
        if sounding <= pcs:
            relevant.append((root, target))
    if not relevant:
        return False
    return all(
        bass == (root + 7) % 12
        and (
            "bass_degree" not in target or (tonic + target["bass_degree"]) % 12 != bass
        )
        for root, target in relevant
    )


def linked_arrival_choices(n, melody, model, targets):
    """Transfer a destination's own source figure without changing its intervals."""
    from .chorale_gestures import _active, _playable
    from .chorale_phrases import CHORDS
    from .chorale_search_gates import bass_route
    from .model import MODES

    scale = {(melody.tonic + p) % 12 for p in MODES[melody.mode]}
    choices = []
    seen = set()
    for target in targets:
        pcs = {
            (melody.tonic + target["root_degree"] + p) % 12
            for p in CHORDS[target["quality"]]
        }
        for figure in model.get("arrival_gestures", []):
            if (
                figure["id"] in seen
                or figure["source_id"] != target.get("source_id")
                or figure["source_end"] != target.get("source_end")
                or not any(
                    abs(n.duration / figure["duration"] - r) < 1e-6 for r in (0.5, 1, 2)
                )
            ):
                continue
            events = figure["events"]
            if (
                not _playable(events, n.pitch)
                or bass_route(n.pitch, tuple(map(tuple, events))) is None
            ):
                continue
            if (
                not {n.pitch % 12, *((n.pitch - o) % 12 for o, _, _, _ in events)}
                <= scale
            ):
                continue
            terminal = {
                n.pitch % 12,
                *(p % 12 for p in _active(events, 1 - 1e-6, n.pitch)),
            }
            if terminal != pcs:
                continue
            times = sorted({0, 1, *(t for _, a, b, _ in events for t in (a, b))})
            # Same destination base cost and register coefficient as static
            # cadence choices; integrate the actual moving bass over time.
            cost = 0.7 + sum(
                (b - a)
                * 0.025
                * abs(
                    n.pitch
                    - min(_active(events, (a + b) / 2, n.pitch))
                    - model["bass_gap"]
                )
                for a, b in pairwise(times)
            )
            choices.append((events, cost, figure["id"]))
            seen.add(figure["id"])
    return choices


def planned_options(n, melody, model, options, goals):
    """Offer the destination and its approach before the beam selects a path."""
    goal = next(
        (
            g
            for g in goals
            if g
            and n.end <= g["end"] + 1e-6
            and n in [x for x in melody.notes if x.end <= g["end"] + 1e-6][-3:]
        ),
        None,
    )
    if goal is None:
        return options
    arriving = abs(n.end - goal["end"]) < 1e-6
    alternatives = (
        goal.get("alternatives") if model.get("cadence_alternatives") else None
    )
    offers = list(alternatives) if alternatives else [goal]
    preparations = []
    if not arriving and any(g["root_degree"] == 0 for g in offers):
        preparations = [
            {"root_degree": 7, "quality": "major"},
            {"root_degree": 7, "quality": "dom7"},
        ]
        if not model.get("cadence_destination_contracts"):
            offers += preparations
    result = list(options)
    if arriving and model.get("linked_arrival_figures"):
        result.extend(linked_arrival_choices(n, melody, model, offers))
    for target in offers:
        result.extend(
            cadence_choices(n, melody, model, target, 0.7 if arriving else 1.3)
        )
    if not arriving and model.get("cadence_destination_contracts"):
        from .chorale_cadence_contracts import CadencePreparation, preparation_targets

        for destination in offers:
            if destination["root_degree"] != 0 and not model.get(
                "cadence_relative_preparations"
            ):
                continue
            promise = (goal["end"], destination["root_degree"], destination["quality"])
            for preparation in preparation_targets(destination, melody.mode):
                result.extend(
                    (events, cost, CadencePreparation(identity, promise))
                    for events, cost, identity in cadence_choices(
                        n, melody, model, preparation, 1.3
                    )
                )
    if arriving:
        intervals = {"major": (0, 4, 7), "minor": (0, 3, 7), "dom7": (0, 4, 7, 10)}.get(
            goal["quality"]
        )
        if intervals is None:
            return result
        root = (melody.tonic + goal["root_degree"]) % 12
        pcs = {(root + i) % 12 for i in intervals}
        adjusted = []
        for events, cost, identity in result:
            ps = sorted(
                {n.pitch - offset for offset, a, b, _ in events if a <= 1 - 1e-6 < b}
            )
            if model.get("cadence_inversion_gate") and unsupported_cadence_six_four(
                n.pitch, ps, melody.tonic, alternatives or [goal]
            ):
                continue
            if alternatives:
                adjusted.append(
                    (
                        events,
                        cost
                        + cadence_mixture_penalty(
                            n.pitch,
                            ps,
                            melody.tonic,
                            alternatives,
                            events=events
                            if model.get("temporal_cadence_evidence")
                            else None,
                            defining_tones=model.get("cadence_defining_tones", False),
                        ),
                        identity,
                    )
                )
                continue
            sounding = {n.pitch % 12, *(p % 12 for p in ps)}
            if model.get("temporal_cadence_evidence"):
                sounding = terminal_pitch_classes(
                    n.pitch, events, root, goal["quality"]
                )
            # A supported cadence should actually contain its distinguishing
            # tones. This is a soft goal, never an unconditional tonic rule.
            required = (
                pcs - {(root + 7) % 12} if model.get("cadence_defining_tones") else pcs
            )
            mismatch = len(required - sounding) + len(sounding - pcs)
            cost += goal["support_fraction"] * (
                1.1 * mismatch
                + 0.3
                * (
                    not ps
                    or ps[0] % 12
                    != (melody.tonic + goal.get("bass_degree", goal["root_degree"]))
                    % 12
                )
            )
            adjusted.append((events, cost, identity))
        result = adjusted
    return sorted(result, key=lambda x: x[1])[:64]


def cross_validate(model):
    """Leave an entire source group out of cadence inference, including repeats."""
    from .model import Event, Melody

    rows = []
    for row in model["cadence_contexts"]:
        if row["root_degree"] is None:
            continue
        notes = [Event(p, a, b - a, 72, "melody") for p, a, b in row["melody"]]
        end = notes[-1].end
        melody = Melody(
            notes, end, [(0, 4, 4)], [end], row["tonic"], row["mode"], fermatas=[end]
        )
        prediction = propose(melody, end, model, exclude_group=row["group"])
        rows.append(
            {
                "group": row["group"],
                "source_end": row["end"],
                "actual_root_degree": row["root_degree"],
                "actual_quality": row["quality"],
                "prediction": prediction,
                "correct": None
                if prediction is None
                else (prediction["root_degree"], prediction["quality"])
                == (row["root_degree"], row["quality"]),
            }
        )
    return {
        "method": "leave_one_source_group_out",
        "cases": rows,
        "abstentions": sum(r["prediction"] is None for r in rows),
        "correct": sum(r["correct"] is True for r in rows),
        "incorrect": sum(r["correct"] is False for r in rows),
    }
