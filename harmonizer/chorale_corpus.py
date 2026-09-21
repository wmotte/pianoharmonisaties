"""Traceable chorale excerpts and melody extraction without reharmonized references."""

import argparse
import json
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

from music21 import converter, expressions, stream

from .annotations import validate_splits
from .corpus import digest
from .engine import Arrangement
from .midi import save_midi, validate_export
from .model import Event, Melody, write_json
from .notation import _sounding, save_musicxml
from .score_style import explicit_sections, score_timeline


def part_events(part):
    score = stream.Score()
    score.insert(0, deepcopy(part))
    return _sounding(score)


def crop_events(events, start, end):
    return sorted(
        (p, max(a, start) - start, min(b, end) - start)
        for p, a, b in events
        if a < end - 1e-7 and b > start + 1e-7
    )


def boundary_clips(events, start, end):
    """Disclose source durations changed by cropping, in source coordinates."""
    if end <= start:
        raise ValueError("Crop end must follow start")
    return [
        {
            "pitch": p,
            "source_start": a,
            "source_end": b,
            "retained_start": max(a, start),
            "retained_end": min(b, end),
            "clipped_start": a < start,
            "clipped_end": b > end,
        }
        for p, a, b in events
        if a < end and b > start and (a < start or b > end)
    ]


def separate_melody(right, left):
    """Use complete highest RH attacks, rejecting overlapping/ambiguous melody.

    No source pitches or durations are changed to make an excerpt qualify.
    Cropping is done beforehand and recorded in the provenance.
    """
    attacks = defaultdict(list)
    for event in right:
        attacks[event[1]].append(event)
    top = []
    for _, group in sorted(attacks.items()):
        candidate = max(group, key=lambda n: n[0])
        if top and candidate[1] < top[-1][2] - 1e-6:
            if candidate[0] <= top[-1][0]:
                # An inner voice can move underneath a held melody note.
                continue
            raise ValueError(
                "Een nieuwe hogere noot overlapt de aangehouden bovenstem."
            )
        top.append(candidate)
    if len(top) < 8:
        raise ValueError("Minder dan acht melodienoten.")
    if any(a[2] > b[1] + 1e-6 for a, b in pairwise(top)):
        raise ValueError("Overlappende bovenstem: handmatige melodiecontrole nodig.")
    for p, a, b in top:
        if any(q > p and c < b - 1e-6 and d > a + 1e-6 for q, c, d in right + left):
            raise ValueError("De gekozen melodie is niet consequent de bovenstem.")
    events = right + left
    for i, (p, a, b) in enumerate(events):
        if any(q == p and c < b - 1e-6 and d > a + 1e-6 for q, c, d in events[i + 1 :]):
            raise ValueError(
                "Overlappende unisono-noten maken MIDI-identiteit dubbelzinnig."
            )
    return top


def extract(path, source, historical, splits):
    score = converter.parse(path)
    if len(score.parts) != 2:
        raise ValueError("Twee pianobalken vereist.")
    timeline = score_timeline(score)
    measures = timeline["measures"]
    explicit = explicit_sections(
        timeline, path.stem, splits, float(score.duration.quarterLength)
    )
    if explicit:
        ranges = [
            (
                sum(m["start"] < s["start"] for m in measures),
                sum(m["start"] < s["end"] for m in measures),
            )
            for s in explicit
            if s["name"] == "Koraal"
        ]
        boundary_method = "explicit_section"
    elif historical and historical["bars"] == len(measures):
        ranges = [
            (s["start"], s["end"])
            for s in historical["sections"]
            if s["name"].startswith("koraal")
            and s["end"] - s["start"] >= 4
            and s["start"] > 0
        ]
        boundary_method = "historical_repetition_proposal_same_measure_count"
    else:
        raise ValueError("Geen actuele of structureel passende koraalgrenzen.")
    if not ranges:
        raise ValueError("Geen bruikbaar koraalvoorstel.")
    # Prefer coherent couplet-sized regions to tiny repeated introductory motifs.
    longest = max(b - a for a, b in ranges)
    if longest >= 16:
        ranges = [(a, b) for a, b in ranges if b - a >= max(16, longest * 0.6)]
    right, left = map(part_events, score.parts)
    proposals = []
    for lo, hi in ranges:
        for a in range(lo, max(lo + 1, hi - 3)):
            b = min(hi, a + 8)
            if b - a < 4:
                continue
            start = measures[a]["start"]
            end = (
                measures[b]["start"]
                if b < len(measures)
                else float(score.duration.quarterLength)
            )
            r, l = crop_events(right, start, end), crop_events(left, start, end)
            try:
                melody = separate_melody(r, l)
            except ValueError:
                continue
            jumps = sum(abs(x[0] - y[0]) > 7 for x, y in pairwise(melody)) / max(
                1, len(melody) - 1
            )
            if jumps > 0.3:
                continue
            occupancy = sum(t - s for _, s, t in melody) / (end - start)
            if occupancy < 0.65:
                continue
            # Favor a longer coherent passage, away from detected introductions.
            value = (b - a) * 2 + occupancy - jumps * 5 - abs(a - lo) * 0.03
            proposals.append((value, a, b, start, end, r, l, melody))
    if not proposals:
        raise ValueError(
            "Alle koraalvoorstellen hebben onduidelijke bovenstem of te veel overlap."
        )
    _, lo, hi, start, end, right, left, top = max(proposals, key=lambda x: x[0])
    part = score.measures(measures[lo]["number"], measures[hi - 1]["number"])
    inferred = part.analyze("key")
    tonic, mode = inferred.tonic.pitchClass, inferred.mode
    if source["tune"] == "psalm_37":
        tonic, mode = 0, "dorian"
    meters = [(0, *next(m[1:] for m in reversed(timeline["meters"]) if m[0] <= start))]
    meters += [(t - start, n, d) for t, n, d in timeline["meters"] if start < t < end]
    tempos = [
        (
            0,
            next(
                t["quarter_bpm"]
                for t in reversed(timeline["tempos"])
                if t["start"] <= start
            ),
        )
    ]
    tempos += [
        (t["start"] - start, t["quarter_bpm"])
        for t in timeline["tempos"]
        if start < t["start"] < end
    ]
    fermatas = []
    for el in score.parts[0].recurse().notes:
        time = float(el.getOffsetInHierarchy(score.parts[0])) + float(el.quarterLength)
        if (
            start < time <= end
            and any(isinstance(e, expressions.Fermata) for e in el.expressions)
            and not any(
                a < time - start - 1e-7 and b > time - start + 1e-7 for _, a, b in top
            )
        ):
            fermatas.append(time - start)
    length = end - start
    phrases = sorted(set(fermatas + [length]))
    melody = Melody(
        [Event(p, a, b - a, 72, "melody") for p, a, b in top],
        length,
        meters,
        phrases,
        tonic,
        mode,
        tempos[0][1],
        sorted(set(fermatas)),
        "Koraalmelodie",
    )
    melody.validate()
    remaining = Counter(right) - Counter(top)
    notes = (
        list(melody.notes)
        + [
            Event(p, a, b - a, 72, "inner")
            for (p, a, b), count in remaining.items()
            for _ in range(count)
        ]
        + [Event(p, a, b - a, 72, "bass") for p, a, b in left]
    )
    assert Counter((n.pitch, n.start, n.end) for n in notes) == Counter(right + left)
    arrangement = Arrangement(
        sorted(notes, key=lambda n: (n.start, n.pitch)),
        [],
        [{"name": "Koraal", "start": 0, "end": length}],
        meters,
        phrases,
        melody.fermatas,
        melody.bpm,
        0,
        0,
        0,
        length,
        {},
        tonic,
        mode,
        tempos,
    )
    provenance = {
        "boundary_note_clips": {
            "right": boundary_clips(part_events(score.parts[0]), start, end),
            "left": boundary_clips(part_events(score.parts[1]), start, end),
        },
        "source_id": source["id"],
        "group": source["group"],
        "tune": source["tune"],
        "split": source["split"],
        "source_path": str(path),
        "source_sha256": digest(path),
        "source_measure_count": len(measures),
        "measure_start": measures[lo]["number"],
        "measure_end": measures[hi - 1]["number"],
        "source_start_quarters": start,
        "source_end_quarters": end,
        "boundary_method": boundary_method,
        "melody_method": "highest complete RH attacks; overlaps and crossings rejected",
        "reference_notes_unchanged_after_crop": True,
        "source_note_count": len(notes),
        "gold_status": "provisional_transcription_reference",
        "human_verified": False,
        "normalization": {
            "velocity": 72,
            "pedal": False,
            "notation": "shared_exporter",
        },
        "key_method": "explicit C dorian"
        if source["tune"] == "psalm_37"
        else "inferred from excerpt",
        "melody_notes": len(top),
        "limitations": [
            "Sectievoorstel en transcriptie zijn geen geverifieerde boekuitgave."
        ],
    }
    return melody, arrangement, provenance


def prepare(manifest_path, scores, historical_path, splits_path, output):
    if "midi_gecorrigeerd" in Path(scores).parts:
        raise ValueError(
            "Automatisch herharmoniseerde partituren zijn geen bronreferenties."
        )
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Kies een lege corpusmap.")
    manifest = json.loads(Path(manifest_path).read_text())["sources"]
    validate_splits({s["id"]: s for s in manifest})
    historical = {r["title"]: r for r in json.loads(Path(historical_path).read_text())}
    splits = json.loads(Path(splits_path).read_text())
    entries, excluded, seen = [], [], set()
    for source in sorted(manifest, key=lambda s: s["id"]):
        if (
            source["compilation"]
            or source["split"] == "excluded"
            or source["group"] in seen
        ):
            continue
        path = Path(scores) / (Path(source["audio"]).stem + ".musicxml")
        if not path.exists():
            continue
        try:
            melody, reference, provenance = extract(
                path, source, historical.get(path.stem), splits
            )
        except (ValueError, IndexError) as error:
            excluded.append(
                {
                    "source_id": source["id"],
                    "tune": source["tune"],
                    "reason": str(error),
                }
            )
            continue
        directory = output / source["id"]
        directory.mkdir(parents=True, exist_ok=True)
        melody.save(directory / "melody.json")
        write_json(directory / "reference.json", asdict(reference))
        write_json(directory / "provenance.json", provenance)
        for name, a in [
            ("reference", reference),
            (
                "melody",
                Arrangement(
                    melody.notes,
                    [],
                    reference.sections,
                    melody.meters,
                    melody.phrases,
                    melody.fermatas,
                    melody.bpm,
                    0,
                    0,
                    0,
                    melody.length,
                    {},
                    melody.tonic,
                    melody.mode,
                    reference.tempos,
                ),
            ),
        ]:
            mid = directory / f"{name}.mid"
            save_midi(a, mid, {})
            validate_export(mid, a)
            save_musicxml(
                a,
                directory / f"{name}.musicxml",
                melody.tonic,
                melody.mode,
                "Koraal" if name == "reference" else "Melodie",
            )
        provenance["artifact_sha256"] = {
            name: digest(directory / name)
            for name in (
                "melody.json",
                "reference.json",
                "reference.mid",
                "reference.musicxml",
            )
        }
        write_json(directory / "provenance.json", provenance)
        entries.append({**provenance, "directory": str(directory)})
        seen.add(source["group"])
        print(
            source["split"],
            source["tune"],
            provenance["measure_start"],
            provenance["measure_end"],
            len(melody.notes),
            flush=True,
        )
    result = {
        "schema_version": 1,
        "status": "provisional_references",
        "manifest_sha256": digest(manifest_path),
        "entries": entries,
        "excluded": excluded,
        "counts": dict(Counter(e["split"] for e in entries)),
    }
    write_json(output / "index.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--manifest",
        type=Path,
        default=Path("private_data/harmonizer/corpus/manifest.json"),
    )
    p.add_argument("--scores", type=Path, default=Path("private_data/midi_controle"))
    p.add_argument(
        "--historical", type=Path, default=Path("private_data/stijlanalyse.json")
    )
    p.add_argument("--splits", type=Path, default=Path("splits.json"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = prepare(a.manifest, a.scores, a.historical, a.splits, a.output)
    print(result["counts"])


if __name__ == "__main__":
    main()
