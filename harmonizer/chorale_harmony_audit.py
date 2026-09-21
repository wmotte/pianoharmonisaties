"""Conservative duration-weighted harmony audit, independent of generator scores.

Unknown windows stay unknown. Open fifths do not establish major/minor quality.
This audit observes sounding notes over time instead of only melody attacks.
"""

from .profile import identify_chord

VOCABULARY = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "dim": (0, 3, 6),
    "dom7": (0, 4, 7, 10),
    "min7": (0, 3, 7, 10),
    "maj7": (0, 4, 7, 11),
}


def window_harmony(notes, start, end):
    weights = [0.0] * 12
    active = []
    for n in notes:
        duration = min(n.end, end) - max(n.start, start)
        if duration > 1e-7:
            weights[n.pitch % 12] += duration
            active.append(n)
    total = sum(weights)
    onset = [n.pitch for n in active if n.start <= start + 1e-7 < n.end]
    result = {
        "start": start,
        "end": end,
        "pitch_class_durations": weights,
        "onset_label": identify_chord(onset) if onset else None,
        "label": None,
        "candidates": [],
        "status": "insufficient_evidence",
    }
    if not total:
        return result
    candidates = []
    for root in range(12):
        for quality, intervals in VOCABULARY.items():
            pcs = {(root + p) % 12 for p in intervals}
            # A brief ornamental tone cannot establish a seventh chord. Every
            # defining pitch class must account for at least 8% of note-time.
            support = min(weights[p] / total for p in pcs)
            outside = sum(w for p, w in enumerate(weights) if p not in pcs) / total
            if support >= 0.08 and outside <= 0.12:
                candidates.append(
                    {
                        "root": root,
                        "quality": quality,
                        "outside_fraction": outside,
                        "minimum_tone_support": support,
                        "cost": outside + 0.02 * (len(pcs) - 3),
                    }
                )
    candidates.sort(key=lambda row: (row["cost"], row["root"], row["quality"]))
    result["candidates"] = candidates
    if not candidates:
        result["status"] = "incomplete_or_changing_harmony"
    elif len(candidates) > 1 and candidates[1]["cost"] - candidates[0]["cost"] < 0.04:
        result["status"] = "ambiguous"
    else:
        best = candidates[0]
        result["label"] = (best["root"], best["quality"])
        result["status"] = "provisional_identification"
    return result


def analyze(melody, arrangement):
    rows = []
    for i, (offset, num, den) in enumerate(melody.meters):
        stop = melody.meters[i + 1][0] if i + 1 < len(melody.meters) else melody.length
        length = num * 4 / den / (2 if num % 2 == 0 else 1)
        start = offset
        while start < stop - 1e-6:
            end = min(stop, start + length)
            row = window_harmony(arrangement.notes, start, end)
            # A coarse label must also survive independent subdivision. If a
            # shorter window establishes a different chord, report the change.
            middle = (start + end) / 2
            children = [
                window_harmony(arrangement.notes, a, b)
                for a, b in ((start, middle), (middle, end))
            ]
            row["subwindow_labels"] = [child["label"] for child in children]
            if row["label"] and any(
                (child["label"] and child["label"] != row["label"])
                or (
                    not child["label"]
                    and sum(
                        w > 0 and w >= 0.08 * sum(child["pitch_class_durations"])
                        for w in child["pitch_class_durations"]
                    )
                    >= 3
                )
                for child in children
            ):
                row["label"] = None
                row["status"] = "subwindow_disagreement"
            rows.append(row)
            start = end
    return rows


def main():
    import argparse
    import json
    from collections import Counter
    from pathlib import Path

    from .chorale_lab import load_entry, read_arrangement
    from .corpus import digest
    from .model import write_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory.")
    args.output.mkdir(parents=True, exist_ok=True)
    model = json.loads((args.review / "model.json").read_text())
    entries = json.loads(args.corpus.read_text())["entries"]
    rows = []
    for e in entries:
        if e["source_id"] not in model["training_ids"] and e["split"] not in (
            "validation",
            "test",
        ):
            continue
        _, melody, reference = load_entry(e)
        row = {
            "source_id": e["source_id"],
            "group": e["group"],
            "tune": e["tune"],
            "split": e["split"],
            "source_sha256": e["source_sha256"],
            "reference": analyze(melody, reference),
        }
        generated = args.review / e["tune"] / "after.arrangement.json"
        if generated.exists():
            row["generated"] = analyze(melody, read_arrangement(generated))
        rows.append(row)
    training = [
        r
        for row in rows
        if row["source_id"] in model["training_ids"]
        for r in row["reference"]
    ]
    summary = {
        "training_windows": len(training),
        "training_status": dict(Counter(r["status"] for r in training)),
        "recognized_without_onset_chord": sum(
            r["label"] is not None and r["onset_label"] is None for r in training
        ),
        "onset_window_disagreement": sum(
            r["label"] is not None
            and r["onset_label"] is not None
            and tuple(r["onset_label"]) != tuple(r["label"])
            for r in training
        ),
        "reviewed": False,
        "generator_changed": False,
    }
    write_json(args.output / "results.json", rows)
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "protocol.json",
        {
            "corpus_sha256": digest(args.corpus),
            "model_sha256": digest(args.review / "model.json"),
            "code_sha256": digest(Path(__file__)),
            "training_ids": model["training_ids"],
            "minimum_tone_support": 0.08,
            "maximum_outside_fraction": 0.12,
            "ambiguity_margin": 0.04,
            "status": "provisional_score_analysis_not_human_gold_standard",
        },
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
