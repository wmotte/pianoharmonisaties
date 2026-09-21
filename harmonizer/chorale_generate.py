"""Generate an experimental chorale from a melody and a frozen corpus model."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .chorale_lab import export
from .chorale_model import generate_chorale
from .chorale_review import musical_checks, verify_score
from .corpus import digest
from .model import load_melody, write_json


def main(*, default_model=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("melody", type=Path)
    parser.add_argument(
        "--model", required=default_model is None, default=default_model, type=Path
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--search", choices=("beam", "exact"))
    parser.add_argument(
        "--complete",
        action="store_true",
        help="Request a tonic ending for a complete chorale",
    )
    parser.add_argument(
        "--terminal-quality",
        choices=("major", "minor"),
        help="Explicit final tonic quality; requires --complete",
    )
    parser.add_argument(
        "--exclude-group", help="Reject a model trained on this tune group"
    )
    parser.add_argument("--musescore")
    parser.add_argument(
        "--octave-register",
        action="store_true",
        help="Refine bass octaves using disclosed register densities, preserving harmony and rhythm",
    )
    args = parser.parse_args()
    if args.terminal_quality and not args.complete:
        parser.error("--terminal-quality requires --complete")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory")
    melody = load_melody(args.melody, {})
    model = json.loads(args.model.read_text())
    model.setdefault("structural_search", True)
    if args.octave_register:
        model["octave_register"] = True
    if args.exclude_group:
        if "training_groups" not in model:
            parser.error("Model does not disclose training groups")
        if args.exclude_group in model["training_groups"]:
            parser.error("Requested evaluation group occurs in the training model")
    if args.complete:
        # A serialized model may have been used for a different melody.
        # Do not inherit that piece's terminal quality into this request.
        model["terminal_cadence"] = (
            {"quality": args.terminal_quality} if args.terminal_quality else {}
        )
    else:
        model.pop("terminal_cadence", None)
    if args.search:
        model["gesture_search"] = args.search
    arrangement = generate_chorale(melody, model, seed=0)
    checks = musical_checks(arrangement, melody)
    if not checks["melody_exact"]:
        raise ValueError("Generator changed the supplied melody")
    structural_failures = [
        key
        for key in (
            "crossing_time_fraction",
            "bass_leaps_over_octave",
            "outer_parallel_perfects",
            "unaccompanied_melody_time_fraction",
        )
        if checks[key] > 1e-7
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    melody.save(args.output / "melody.json")
    write_json(args.output / "model.json", model)
    write_json(args.output / "candidate.json", asdict(arrangement))
    report = {
        "status": "structural_review_failed"
        if structural_failures
        else "experimental_not_style_approved",
        "structural_failures": structural_failures,
        "export_status": "in_progress",
        "input_sha256": digest(args.melody),
        "source_model_sha256": digest(args.model),
        "effective_model_sha256": digest(args.output / "model.json"),
        "implementation_sha256": {
            p.name: digest(p) for p in Path(__file__).parent.glob("*.py")
        },
        "complete_chorale_requested": args.complete,
        "excluded_group": args.exclude_group,
        "checks": checks,
        "human_votes": 0,
    }
    write_json(args.output / "report.json", report)
    try:
        report["export"] = export(
            arrangement, melody, args.output, "candidate", "Koraal"
        )
        if args.musescore:
            report["musescore"] = verify_score(
                args.output / "candidate.musicxml", args.musescore
            )
        report["export_status"] = "verified" if args.musescore else "exported"
    except Exception as exc:
        report["export_status"] = "failed"
        report["export_error"] = f"{type(exc).__name__}: {exc}"
        write_json(args.output / "report.json", report)
        raise
    write_json(args.output / "report.json", report)
    print(
        json.dumps(
            {"status": report["status"], "checks": checks, "output": str(args.output)}
        )
    )


if __name__ == "__main__":
    main()
