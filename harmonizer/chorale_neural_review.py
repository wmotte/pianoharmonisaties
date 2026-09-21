"""Independent local piano-model audit with intentionally poor control settings."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .aria import make_model, score_sequence, tokenize
from .audit import read_arrangement
from .chorale_lab import export, load_entry
from .corpus import digest
from .model import Event, write_json


def negative_controls(arrangement, melody):
    bass = min(n.pitch for n in melody.notes) - 24
    bass -= (bass - melody.tonic) % 12
    controls = {
        "melody_only": list(melody.notes),
        "octave_doubling": list(melody.notes)
        + [Event(n.pitch - 24, n.start, n.duration, 72, "bass") for n in melody.notes],
        "tonic_pedal": list(melody.notes)
        + [
            Event(bass + offset, 0, melody.length, 72, "bass")
            for offset in (0, 3 if melody.mode in ("minor", "dorian") else 4, 7)
        ],
    }
    return {
        name: replace(
            arrangement,
            notes=sorted(notes, key=lambda n: (n.start, n.pitch)),
            harmony=[],
        )
        for name, notes in controls.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory.")
    args.output.mkdir(parents=True, exist_ok=True)
    model, tokenizer = make_model(args.checkpoint)
    write_json(
        args.output / "protocol.json",
        {
            "checkpoint_sha256": digest(args.checkpoint),
            "context": 512,
            "metric": "mean token negative log likelihood; lower is more probable, not necessarily better music",
            "training": "No training or adapters; existing local base checkpoint.",
            "scope": "Previously examined validation excerpts; no authorship or independent generalization claim.",
        },
    )
    rows = []
    for entry in json.loads(args.corpus.read_text())["entries"]:
        if entry["split"] != "validation":
            continue
        _, melody, _ = load_entry(entry)
        source = args.review / entry["tune"]
        arrangement = read_arrangement(source / "after.arrangement.json")
        directory = args.output / entry["tune"]
        directory.mkdir()
        paths = {
            "reference": source / "reference.mid",
            "generated": source / "after.mid",
        }
        for name, control in negative_controls(arrangement, melody).items():
            export(control, melody, directory, name, "Koraal")
            paths[name] = directory / (name + ".mid")
        row = {"tune": entry["tune"], "scores": {}}
        for name, path in paths.items():
            ids = tokenize(path, tokenizer)
            row["scores"][name] = {
                "tokens": len(ids),
                "nll": score_sequence(model, ids, 512),
                "midi_sha256": digest(path),
            }
        row["lowest_nll"] = min(row["scores"], key=lambda k: row["scores"][k]["nll"])
        rows.append(row)
        write_json(args.output / "scores.json", rows)
        print(
            entry["tune"],
            row["lowest_nll"],
            {k: round(v["nll"], 3) for k, v in row["scores"].items()},
            flush=True,
        )


if __name__ == "__main__":
    main()
