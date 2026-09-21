"""Validate full-score rest candidates without using validation or test songs."""

import itertools
import json
from copy import deepcopy
from pathlib import Path

from music21 import converter, expressions

from .chorale_corpus import crop_events, part_events, separate_melody
from .chorale_gestures import beat_class
from .chorale_lab import load_entry
from .corpus import digest
from .model import Event, Melody
from .score_style import score_timeline


def melodic_context(melody, previous, following):
    notes = [n for n in melody.notes if n.end <= previous.end + 1e-6][-4:]
    return {
        "preceding_steps": [b.pitch - a.pitch for a, b in itertools.pairwise(notes)],
        "duration_ratio": previous.duration / notes[-2].duration
        if len(notes) > 1
        else None,
        "next_duration": following.duration,
    }


def expand(
    model,
    corpus_entries,
    inventory_path,
    *,
    class_balance=False,
    context_features=False,
):
    inventory = json.loads(Path(inventory_path).read_text())
    entries = {e["source_id"]: e for e in corpus_entries}
    allowed = set(model["training_ids"])
    if any(e["source_id"] not in allowed for e in inventory["entries"]):
        raise ValueError("Rest inventory contains undisclosed training identities.")
    rows = []
    rejected = []
    seen = set()
    for item in inventory["entries"]:
        entry = entries[item["source_id"]]
        if entry["split"] != "train" or item["group"] != entry["group"]:
            raise ValueError("Rest source group or split is inconsistent.")
        _, original, _ = load_entry(entry)
        path = Path(entry["source_path"])
        if digest(path) != item["source_sha256"]:
            raise ValueError("Full-score inventory source changed.")
        score = converter.parse(path)
        timeline = score_timeline(score)
        right, left = map(part_events, score.parts)
        right_set = {(p, round(a, 6), round(b, 6)) for p, a, b in right}
        fermatas = {
            round(
                float(n.getOffsetInHierarchy(score.parts[0])) + float(n.quarterLength),
                6,
            )
            for n in score.parts[0].recurse().notes
            if any(isinstance(x, expressions.Fermata) for x in n.expressions)
        }
        for gap in item["candidate_rests"]:
            a, b = gap["start"], gap["end"]
            key = (entry["source_id"], round(a, 6), round(b, 6))
            if key in seen:
                continue
            seen.add(key)
            region = next(
                ((lo, hi) for lo, hi in item["ranges"] if lo <= a < b <= hi), None
            )
            if not region:
                rejected.append(
                    {
                        "source_id": entry["source_id"],
                        "start": a,
                        "reason": "Outside proposed chorale region.",
                    }
                )
                continue
            start = max(region[0], a - 24)
            end = min(region[1], b + 8)
            try:
                top = separate_melody(
                    crop_events(right, start, end), crop_events(left, start, end)
                )
                top = [(p, x + start, y + start) for p, x, y in top]
                pair = next(
                    (
                        (x, y)
                        for x, y in itertools.pairwise(top)
                        if abs(x[2] - a) < 1e-6 and abs(y[1] - b) < 1e-6
                    ),
                    None,
                )
                if pair is None:
                    raise ValueError(
                        "Rest is not between two unambiguous melody notes."
                    )
                if any(
                    (p, round(x, 6), round(y, 6)) not in right_set for p, x, y in pair
                ):
                    raise ValueError(
                        "A boundary note would be clipped by the extraction window."
                    )
                notes = [Event(p, x, y - x) for p, x, y in top]
                previous = next(n for n in notes if abs(n.end - a) < 1e-6)
                following = next(n for n in notes if abs(n.start - b) < 1e-6)
                melody = Melody(
                    notes, end, timeline["meters"], [end], original.tonic, original.mode
                )
                bass = min(p for p, x, y in right + left if x <= a - 1e-6 < y)
                events = sorted(
                    (p - bass, max(0, x - a), min(b, y) - a, x < a - 1e-6)
                    for p, x, y in left
                    if x < b - 1e-6 and y > a + 1e-6
                )
                if bool(events) != gap["left_support"]:
                    raise ValueError("Rest support differs from the stored inventory.")
                rows.append(
                    {
                        "source_id": entry["source_id"],
                        "group": entry["group"],
                        "source_path": str(path),
                        "source_sha256": entry["source_sha256"],
                        "mode": original.mode,
                        "duration": b - a,
                        "previous_duration": previous.duration,
                        "melodic_step": following.pitch - previous.pitch,
                        "events": events,
                        "start": a,
                        "rest_beat": beat_class(melody, a),
                        "phrase_end": round(a, 6) in fermatas,
                        "context": melodic_context(melody, previous, following),
                        "context_notes": [(n.pitch, n.start, n.end) for n in notes],
                        "meters": timeline["meters"],
                        "tonic": original.tonic,
                        "status": "validated_upper_voice_provisional_section_and_key",
                    }
                )
            except (ValueError, StopIteration) as error:
                rejected.append(
                    {"source_id": entry["source_id"], "start": a, "reason": str(error)}
                )
    result = deepcopy(model)
    result["rest_contexts"] = rows
    result["continuity_scope"].update(
        class_balance=class_balance,
        context_features=context_features,
        maximum_previous_duration=max(
            (r["previous_duration"] for r in rows), default=0
        ),
    )
    result["rest_corpus_provenance"] = {
        "inventory_sha256": digest(Path(inventory_path)),
        "rejected": rejected,
        "validated": len(rows),
    }
    return result


def evaluate_groups(model):
    from .chorale_continuity import choose_context

    cases = []
    for row in model["rest_contexts"]:
        notes = [Event(p, a, b - a) for p, a, b in row["context_notes"]]
        end = max(n.end for n in notes)
        m = Melody(
            notes,
            end,
            row["meters"],
            [end],
            row["tonic"],
            row["mode"],
            fermatas=[row["start"]] if row["phrase_end"] else [],
        )
        before = next(n for n in notes if abs(n.end - row["start"]) < 1e-6)
        after = next(
            n for n in notes if abs(n.start - row["start"] - row["duration"]) < 1e-6
        )
        predicted = choose_context(m, before, after, model, exclude_group=row["group"])
        cases.append(
            {
                "group": row["group"],
                "start": row["start"],
                "actual": bool(row["events"]),
                "predicted": predicted is not None,
                "explicit_fermata": row["phrase_end"],
            }
        )
    pairs = {
        "true_support": (True, True),
        "true_silence": (False, False),
        "false_fill": (False, True),
        "missed_support": (True, False),
    }
    counts = {
        k: sum((r["actual"], r["predicted"]) == v for r in cases)
        for k, v in pairs.items()
    }
    return {"method": "leave_entire_source_group_out", "counts": counts, "cases": cases}


def main():
    import argparse

    from .model import write_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory.")
    args.output.mkdir(parents=True, exist_ok=True)
    original = json.loads(args.model.read_text())
    expanded = expand(
        original, json.loads(args.corpus.read_text())["entries"], args.inventory
    )
    write_json(args.output / "expanded_model.json", expanded)
    write_json(
        args.output / "protocol.json",
        {
            "model_sha256": digest(args.model),
            "corpus_sha256": digest(args.corpus),
            "inventory_sha256": digest(args.inventory),
            "implementation_sha256": digest(Path(__file__)),
            "status": "data_and_ablation_review_only_not_a_promoted_generator",
        },
    )
    for balance in (False, True):
        for context in (False, True):
            candidate = deepcopy(expanded)
            candidate["continuity_scope"].update(
                class_balance=balance, context_features=context
            )
            result = evaluate_groups(candidate)
            write_json(
                args.output
                / f"group_review_balance_{int(balance)}_context_{int(context)}.json",
                result,
            )
            print(balance, context, result["counts"], flush=True)


if __name__ == "__main__":
    main()
