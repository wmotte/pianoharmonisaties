"""Private, reproducible evidence packets for free-section composition research.

No automatic analysis certifies melody identity, phrase boundaries, or listening quality.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from music21 import converter, stream

from .annotations import validate_splits
from .corpus import digest
from .model import write_json
from .score_style import analyse_score


def _top_candidates(score, start, end):
    """Proposals grouped by voice, rather than interleaved chord-note maxima."""
    part = score.parts[0]
    voices = {}
    for measure in part.getElementsByClass(stream.Measure):
        for voice in measure.voices or [measure]:
            lane = voices.setdefault(str(voice.id) if voice is not measure else "unvoiced", [])
            for n in voice.notes:
                time = float(n.getOffsetInHierarchy(part))
                if start <= time < end and not (n.tie and n.tie.type in ("continue", "stop")):
                    lane.append((time, float(n.quarterLength), max(n.pitches, key=lambda p: p.midi)))
    candidates = []
    for voice, values in voices.items():
        notes = sorted(values, key=lambda x: x[0])
        grams = Counter()
        positions = {}
        for i in range(max(0, len(notes) - 3)):
            cell = notes[i:i + 4]
            contour = tuple(b[2].diatonicNoteNum - a[2].diatonicNoteNum for a, b in zip(cell, cell[1:]))
            unit = min(n[1] for n in cell)
            rhythm = tuple(round(n[1] / unit, 3) for n in cell)
            token = contour, rhythm
            grams[token] += 1
            positions.setdefault(token, []).append(cell[0][0])
        for (contour, rhythm), count in grams.most_common(8):
            candidates.append({"voice": voice, "contour": contour, "rhythm": rhythm,
                               "count_including_overlaps": count,
                               "positions": positions[(contour, rhythm)], "reviewed": False})
    return candidates


def research_packet(manifest_path, scores, splits_path, previous=None):
    manifest = json.loads(Path(manifest_path).read_text())
    validate_splits({s["id"]: s for s in manifest["sources"]})
    splits = json.loads(Path(splits_path).read_text())
    old = json.loads(Path(previous).read_text()) if previous and Path(previous).exists() else []
    old_by_title = {r["title"]: r for r in old}
    rows, library = [], []
    deep = ("psalm_37", "psalm_85", "psalm_73", "mijn_jezus_ik_hou_van_u", "i_need_thee_every_hour")
    for source in manifest["sources"]:
        audio, raw = Path(source["audio"]), Path(source["midi"])
        path = Path(scores) / (audio.stem + ".musicxml")
        row = {"source_id": source["id"], "tune": source["tune"], "group": source["group"],
               "split": source["split"], "compilation": source["compilation"],
               "audio": str(audio), "raw_midi": str(raw), "score": str(path),
               "audio_hash_matches": audio.is_file() and digest(audio) == source["audio_sha256"],
               "raw_hash_matches": raw.is_file() and digest(raw) == source["midi_sha256"],
               "reviewed": False, "deep_reference": source["tune"] in deep}
        if not path.is_file():
            row["status"] = "score_missing"
            rows.append(row)
            continue
        analysis = analyse_score(path, splits)
        row.update(score_sha256=analysis["sha256"], sections=analysis["sections"],
                   timeline=analysis["timeline"], status="provisional_transcription")
        # Numeric differences are visible evidence of a stale analysis, not new ground truth.
        prior = old_by_title.get(path.stem)
        row["previous_sections"] = ([{k: sec.get(k) for k in ("name", "bars", "start", "end")}
                                     for sec in prior["sections"]] if prior else [])
        if row["deep_reference"]:
            from analyse_stijl import analyse

            fresh = analyse(path, raw, audio_path=audio)
            row["recomputed_form_proposals"] = [
                {k: s.get(k) for k in ("name", "start", "end", "bars", "boundary_source", "first_chords",
                                       "last_chords", "frac8", "rh_size", "lh_size", "rh_top_mean", "rh_top_max")}
                for s in fresh["sections"]]
            row["recomputed_ending"] = {k: fresh.get(k) for k in ("final_chord", "final_quality", "final_seq",
                                                                 "final_n", "final_top_rel", "rit_end")}
            score = converter.parse(path)
            for section in row["sections"]:
                section["motif_proposals"] = _top_candidates(score, section["start"], section["end"])
                spec = next((v for k, v in splits.items() if k in path.stem), None)
                section["audio_window"] = None
                if spec and section["boundary_source"] == "explicit":
                    i = spec["labels"].index(section["name"])
                    cuts = [0, *spec["splits"], source["duration"]]
                    section["audio_window"] = cuts[i:i + 2]
                section["phrase_review"] = "pending"
        if source["split"] == "train" and not source["compilation"]:
            for section in row["sections"]:
                if section["boundary_source"] == "explicit":
                    library.append({**section, "source_id": source["id"], "source_sha256": analysis["sha256"],
                                    "source_path": str(path), "split": "train", "reviewed": False})
        rows.append(row)
    return {"schema_version": 3, "status": "draft", "sources": rows, "section_library": library,
            "summary": {"recordings": len(rows), "independent_recordings": sum(not r["compilation"] for r in rows),
                        "explicit_training_sections": len(library)},
            "limitations": ["Motief- en frasevoorstellen vereisen controle tegen de opname.",
                            "Boekversie en gespeelde versie kunnen verschillen.",
                            "Validatie- en teststukken sturen de compositiekeuzes niet."]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--splits", type=Path, default=Path("splits.json"))
    p.add_argument("--previous", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error("Kies een nieuw rapportpad om eerdere analyses te bewaren.")
    packet = research_packet(args.manifest, args.scores, args.splits, args.previous)
    write_json(args.output, packet)
    print(json.dumps(packet["summary"]))


if __name__ == "__main__":
    main()
