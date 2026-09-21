"""Extend disclosed chorale references without altering source notes or splits."""

import argparse
import json
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from music21 import converter, expressions, key

from .chorale_corpus import crop_events, part_events, separate_melody
from .chorale_lab import export, load_entry
from .chorale_review import verify_score
from .corpus import digest
from .engine import Arrangement
from .model import Event, Melody, write_json
from .score_style import score_timeline


def extend(entry, proposal):
    if (
        entry["split"] != "train"
        or entry["source_id"] != proposal["source_id"]
        or entry["group"] != proposal["group"]
    ):
        raise ValueError("Expansion must preserve the training source and group.")
    _, old_melody, old_arrangement = load_entry(entry)
    source = Path(entry["source_path"])
    if digest(source) != proposal["source_sha256"]:
        raise ValueError("Expansion proposal source hash changed.")
    candidates = [
        (a, b)
        for a, b in proposal["candidate_ranges"]
        if a <= entry["source_start_quarters"] and b >= entry["source_end_quarters"]
    ]
    if len(candidates) != 1:
        raise ValueError("Exactly one enclosing source region is required.")
    start, end = candidates[0]
    score = converter.parse(source)
    if len(score.parts) != 2:
        raise ValueError("Expected two source staves.")
    if not 0 <= start < end <= float(score.duration.quarterLength) + 1e-6:
        raise ValueError("Proposed region exceeds the source score.")
    timeline = score_timeline(score)
    right, left = map(part_events, score.parts)
    right, left = crop_events(right, start, end), crop_events(left, start, end)
    top = separate_melody(right, left)
    old_start = entry["source_start_quarters"] - start
    old_end = entry["source_end_quarters"] - start
    if Counter(crop_events(top, old_start, old_end)) != Counter(
        (n.pitch, n.start, n.end) for n in old_melody.notes
    ):
        raise ValueError("The expanded melody disagrees with the retained excerpt.")
    if Counter(crop_events(right + left, old_start, old_end)) != Counter(
        (n.pitch, n.start, n.end) for n in old_arrangement.notes
    ):
        raise ValueError("The expanded score disagrees with the retained excerpt.")
    signatures = sorted(
        (float(k.getOffsetInHierarchy(score.parts[0])), k.sharps)
        for k in score.parts[0].recurse().getElementsByClass(key.KeySignature)
    )
    initial = next((s for t, s in reversed(signatures) if t <= start), None)
    if any(start < t < end and s != initial for t, s in signatures):
        raise ValueError("A key-signature change requires separate tonal regions.")
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
    for n in score.parts[0].recurse().notes:
        at = float(n.getOffsetInHierarchy(score.parts[0])) + float(n.quarterLength)
        if (
            start < at <= end
            and any(isinstance(x, expressions.Fermata) for x in n.expressions)
            and not any(
                a < at - start - 1e-7 and b > at - start + 1e-7 for _, a, b in top
            )
        ):
            fermatas.append(at - start)
    length = end - start
    melody = Melody(
        [Event(p, a, b - a) for p, a, b in top],
        length,
        meters,
        sorted(set(fermatas + [length])),
        old_melody.tonic,
        old_melody.mode,
        tempos[0][1],
        sorted(set(fermatas)),
        old_melody.title,
    )
    melody.validate()
    remainder = Counter(right) - Counter(top)
    notes = (
        list(melody.notes)
        + [
            Event(p, a, b - a, 72, "inner")
            for (p, a, b), count in remainder.items()
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
        melody.phrases,
        melody.fermatas,
        melody.bpm,
        0,
        0,
        0,
        length,
        {},
        melody.tonic,
        melody.mode,
        tempos,
    )
    result = deepcopy(entry)
    result.update(
        source_start_quarters=start,
        source_end_quarters=end,
        measure_start=next(
            m["number"] for m in timeline["measures"] if abs(m["start"] - start) < 1e-6
        ),
        measure_end=max(m["number"] for m in timeline["measures"] if m["start"] < end),
        source_note_count=len(notes),
        melody_notes=len(top),
        key_method="inherited provisional excerpt mode; no notated key-signature change",
        expansion={
            "old_start": entry["source_start_quarters"],
            "old_end": entry["source_end_quarters"],
            "retained_excerpt_exact": True,
            "full_source_notes_preserved_after_crop": True,
            "score_reviewed_by_assistant": False,
            "human_verified": False,
        },
    )
    return result, melody, arrangement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--musescore")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory.")
    corpus = json.loads(args.corpus.read_text())
    queue = json.loads(args.queue.read_text())
    entries = {e["source_id"]: e for e in corpus["entries"]}
    selected = set(args.source_id) or {
        e["source_id"]
        for e in queue["entries"]
        if e["section_method"] == "explicit_section"
    }
    if not selected <= set(queue["training_ids"]):
        parser.error("Undisclosed training source requested.")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for proposal in queue["entries"]:
        sid = proposal["source_id"]
        if sid not in selected:
            continue
        try:
            entry, melody, arrangement = extend(entries[sid], proposal)
        except ValueError as error:
            results.append(
                {"source_id": sid, "status": "rejected", "reason": str(error)}
            )
            continue
        directory = args.output / sid
        checks = export(arrangement, melody, directory, "reference", "Koraal")
        melody.save(directory / "melody.json")
        write_json(directory / "reference.json", asdict(arrangement))
        entry["directory"] = str(directory)
        entry["artifact_sha256"] = {
            name: digest(directory / name)
            for name in (
                "melody.json",
                "reference.json",
                "reference.mid",
                "reference.musicxml",
            )
        }
        row = {
            "source_id": sid,
            "tune": entry["tune"],
            "status": "extracted_not_promoted",
            "quarters": melody.length,
            "notes": len(arrangement.notes),
            "export": checks,
        }
        if args.musescore:
            row["musescore"] = verify_score(
                directory / "reference.musicxml", args.musescore
            )
        entries[sid] = entry
        results.append(row)
        write_json(args.output / "results.json", results)
        print(entry["tune"], melody.length, "quarters", flush=True)
    corpus["entries"] = [entries[e["source_id"]] for e in corpus["entries"]]
    corpus["expansion_provenance"] = {
        "original_index_sha256": digest(args.corpus),
        "queue_sha256": digest(args.queue),
        "code_sha256": digest(Path(__file__)),
        "selected_training_ids": sorted(selected),
        "promoted": False,
    }
    write_json(args.output / "index.json", corpus)
    write_json(args.output / "results.json", results)


if __name__ == "__main__":
    main()
