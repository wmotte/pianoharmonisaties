"""Fit transparent style statistics using only the training partition."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pretty_midi

from .alignment import align_melody
from .annotations import (
    segment_group,
    segment_split,
    validate_reviewed,
    validate_splits,
)
from .corpus import digest
from .model import MODES, write_json

QUALITIES = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "dim": (0, 3, 6),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "dom7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10),
    "add9": (0, 2, 4, 7),
}


def identify_chord(pitches):
    pcs = {p % 12 for p in pitches}
    if len(pcs) < 3:
        return None
    bass = min(pitches) % 12
    best = None
    for root in range(12):
        for name, intervals in QUALITIES.items():
            chord = {(root + i) % 12 for i in intervals}
            score = (
                2 * len(chord & pcs)
                - 2.5 * len(chord - pcs)
                - 1.5 * len(pcs - chord)
                + 0.25 * (root == bass)
            )
            if best is None or score > best[0]:
                best = (score, root, name)
    return best[1:] if best[0] >= 4 else None


def inferred_key(notes):
    """Draft-only pitch-class fit, never presented as an annotated modal analysis."""
    hist = np.zeros(12)
    for n in notes:
        hist[n.pitch % 12] += min(n.end - n.start, 2)
    major = np.array(
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    )
    minor = np.array(
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
    )
    candidates = [
        (float(np.dot(hist, np.roll(v / np.linalg.norm(v), tonic))), tonic, name)
        for tonic in range(12)
        for name, v in (("major", major), ("minor", minor))
    ]
    return max(candidates)[1:]


def onset_groups(notes, tolerance=0.065):
    groups = []
    for n in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if not groups or n.start - groups[-1][0].start > tolerance:
            groups.append([n])
        else:
            groups[-1].append(n)
    return groups


def fit_profile(manifest_path, annotations_path, output, draft=False):
    manifest = json.loads(Path(manifest_path).read_text())
    annotations = json.loads(Path(annotations_path).read_text())
    sources = {s["id"]: s for s in manifest["sources"]}
    validate_splits(sources)
    tune_splits = {}
    for s in sources.values():
        if s["split"] != "excluded":
            previous = tune_splits.setdefault(s["tune"], s["split"])
            if previous != s["split"]:
                raise ValueError("Dezelfde melodie staat in meerdere splits.")
    chords, transitions, bass_steps, patterns = (
        Counter(),
        Counter(),
        Counter(),
        Counter(),
    )
    mode_chords, mode_transitions = defaultdict(Counter), defaultdict(Counter)
    section_ratios, velocity_envelopes = defaultdict(list), []
    melody_chords, alignments = Counter(), []
    references = {}
    single_onsets = total_onsets = 0
    velocities, spreads, durations, pedals, onset_offsets = [], [], [], [], []
    provenance, seen_hashes = [], set()
    for seg in annotations["segments"]:
        src = sources[seg["source_id"]]
        if seg.get("exclude") or seg.get("duplicate_of"):
            continue
        if segment_split(seg, src, sources) != "train":
            continue
        if not seg.get("reviewed") and not draft:
            continue
        if not src["midi"]:
            continue
        if digest(src["midi"]) != src["midi_sha256"]:
            raise ValueError(
                "Ruwe MIDI gewijzigd sinds inventarisatie. Maak eerst een nieuwe inventaris."
            )
        start, end = float(seg["start"]), float(seg["end"])
        if not 0 <= start < end <= src["duration"] + 0.1:
            raise ValueError("Ongeldig segmentbereik.")
        unique = (src["midi_sha256"], start, end)
        if unique in seen_hashes:
            continue
        seen_hashes.add(unique)
        pm = pretty_midi.PrettyMIDI(src["midi"])
        notes = [
            n
            for i in pm.instruments
            if not i.is_drum
            for n in i.notes
            if start <= n.start < end and n.velocity >= 15
        ]
        if not notes:
            continue
        validate_reviewed(seg, src)
        if seg.get("key"):
            from music21 import key

            k = key.Key(*seg["key"].split())
            tonic, mode = k.tonic.pitchClass, k.mode
        else:
            tonic, mode = inferred_key(notes)
        if mode not in MODES:
            raise ValueError("Onbekende modus in annotatie.")
        groups = onset_groups(notes)
        total_onsets += len(groups)
        single_onsets += sum(len(g) == 1 for g in groups)
        tops = [max(n.pitch for n in g) for g in groups]
        for j in range(len(tops) - 12):
            intervals = [tops[k + 1] - tops[k] for k in range(j, j + 12)]
            signature = hashlib.sha256(json.dumps(intervals).encode()).hexdigest()[:20]
            references.setdefault(
                signature, {"source_id": src["id"], "start": groups[j][0].start}
            )
        if seg.get("reviewed"):
            sections = seg["sections"]
            for section in sections:
                if section["name"] != "Koraal":
                    continue
                chorale_groups = [
                    g for g in groups if section["start"] <= g[0].start < section["end"]
                ]
                if not chorale_groups:
                    continue
                melody_path = section.get("melody_midi", seg["melody_midi"])
                explicit_melody, pairs, alignment = align_melody(
                    melody_path, chorale_groups
                )
                alignment.update(
                    {"source_id": src["id"], "section_start": section["start"]}
                )
                alignments.append(alignment)
                if alignment["matched_fraction"] < 0.85:
                    raise ValueError(
                        "Minder dan 85% van de gecontroleerde melodie is teruggevonden. Controleer sectiegrenzen, melodieversie en transcriptie."
                    )
                for ni, gi in pairs:
                    group = chorale_groups[gi]
                    found = identify_chord([n.pitch for n in group])
                    if found:
                        root, quality = found
                        degree = (explicit_melody[ni].pitch - tonic) % 12
                        label = f"{(root - tonic) % 12}:{quality}"
                        melody_chords[f"{mode}|{degree}>{label}"] += 1
            chorale_duration = sum(
                s["end"] - s["start"] for s in sections if s["name"] == "Koraal"
            )
            if chorale_duration:
                for name in ("Voorspel", "Naspel"):
                    durations_in_section = [
                        s["end"] - s["start"] for s in sections if s["name"] == name
                    ]
                    if durations_in_section:
                        section_ratios[name].append(
                            sum(durations_in_section) / chorale_duration
                        )
            phrase_start = start
            for phrase_end in seg["phrases"]:
                phrase_notes = [
                    n for n in notes if phrase_start <= n.start < phrase_end
                ]
                if len(phrase_notes) >= 8:
                    center = float(np.median([n.velocity for n in phrase_notes]))
                    envelope = []
                    for bin_index in range(4):
                        lo = phrase_start + (phrase_end - phrase_start) * bin_index / 4
                        hi = (
                            phrase_start
                            + (phrase_end - phrase_start) * (bin_index + 1) / 4
                        )
                        values = [
                            n.velocity for n in phrase_notes if lo <= n.start < hi
                        ]
                        envelope.append(
                            float(np.median(values)) - center if values else 0
                        )
                    velocity_envelopes.append(envelope)
                phrase_start = phrase_end
        previous_chord, previous_bass = None, None
        for group in groups:
            pitches = [n.pitch for n in group]
            velocities.extend(n.velocity for n in group)
            spreads.append(
                max(n.velocity for n in group) - min(n.velocity for n in group)
            )
            durations.extend(n.end - n.start for n in group)
            onset_offsets.extend(n.start - min(m.start for m in group) for n in group)
            found = identify_chord(pitches)
            if found:
                root, quality = found
                label = f"{(root - tonic) % 12}:{quality}"
                chords[label] += 1
                mode_chords[mode][label] += 1
                if previous_chord:
                    transitions[previous_chord + ">" + label] += 1
                    mode_transitions[mode][previous_chord + ">" + label] += 1
                previous_chord = label
                low = min(pitches)
                if previous_bass is not None:
                    bass_steps[str(low - previous_bass)] += 1
                previous_bass = low
                # Store chord-relative voicing shapes, not complete musical passages.
                shape = tuple(sorted({p - low for p in pitches if p - low <= 36}))
                patterns[",".join(map(str, shape))] += 1
        for ins in pm.instruments:
            down, held = None, 0
            for cc in sorted(
                (c for c in ins.control_changes if c.number == 64), key=lambda c: c.time
            ):
                if cc.time >= end:
                    break
                if cc.value >= 64 and down is None:
                    down = max(start, cc.time)
                elif cc.value < 64 and down is not None:
                    held += max(0, cc.time - down)
                    down = None
            if down is not None:
                held += end - down
            if any(c.number == 64 for c in ins.control_changes):
                pedals.append(min(1, held / (end - start)))
        provenance.append(
            {
                "source_id": src["id"],
                "group": segment_group(seg, src, sources),
                "tune": seg["tune"],
                "midi_sha256": src["midi_sha256"],
                "midi": src["midi"],
                "start": start,
                "end": end,
                "reviewed": bool(seg.get("reviewed")),
                "key_source": "annotation" if seg.get("key") else "heuristic",
                "tonic": tonic,
                "mode": mode,
            }
        )
    if not provenance:
        raise ValueError(
            "Geen gecontroleerde trainingssegmenten. Annoteer eerst, of gebruik expliciet --draft voor een technische proef."
        )

    def quantile(xs, p, default):
        return float(np.quantile(xs, p)) if xs else default

    profile = {
        "schema_version": 1,
        "status": "draft" if any(not p["reviewed"] for p in provenance) else "reviewed",
        "manifest_sha256": digest(manifest_path),
        "annotations_sha256": digest(annotations_path),
        "sources": provenance,
        "chords": dict(chords),
        "transitions": dict(transitions),
        "mode_chords": {k: dict(v) for k, v in mode_chords.items()},
        "mode_transitions": {k: dict(v) for k, v in mode_transitions.items()},
        "melody_chords": dict(melody_chords),
        "melody_alignments": alignments,
        "reference_contours": references,
        "section_ratios": {k: float(np.median(v)) for k, v in section_ratios.items()},
        "texture": {"single_onset_fraction": single_onsets / max(1, total_onsets)},
        "bass_steps": dict(bass_steps),
        "voicings": dict(patterns.most_common(128)),
        "expression": {
            "velocity": quantile(velocities, 0.5, 70),
            "velocity_spread": quantile(spreads, 0.5, 10),
            "onset_spread_seconds": min(0.04, quantile(onset_offsets, 0.75, 0.012)),
            "pedal_fraction": quantile(pedals, 0.5, 0.8),
            "phrase_velocity_envelope": np.median(velocity_envelopes, axis=0).tolist()
            if velocity_envelopes
            else None,
        },
        "limitations": [
            "Akkoordlabels uit aanslaggroepen zijn schattingen.",
            "Microtiming en velocity zijn transcripties, geen originele toetsmetingen.",
            "Vorm en frase-expressie gebruiken nog expliciete compositieregels.",
        ],
    }
    write_json(output, profile)
    return profile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--manifest",
        type=Path,
        default=Path("private_data/harmonizer/corpus/manifest.json"),
    )
    p.add_argument(
        "--annotations",
        type=Path,
        default=Path("private_data/harmonizer/corpus/annotations.json"),
    )
    p.add_argument(
        "--output", type=Path, default=Path("private_data/harmonizer/profile.json")
    )
    p.add_argument("--draft", action="store_true")
    a = p.parse_args()
    profile = fit_profile(a.manifest, a.annotations, a.output, a.draft)
    print(
        f"{profile['status']}: {len(profile['sources'])} trainingssegmenten, {len(profile['chords'])} akkoordlabels"
    )


if __name__ == "__main__":
    main()
