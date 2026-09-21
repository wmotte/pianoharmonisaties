"""Reproducible, opt-in chorale refinement with source and export audits."""

import argparse
import json
import math
import platform
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path

from .audit import read_arrangement
from .chorale_inner_pair import revoice_inner_pair
from .chorale_obligations import ResolutionObligation, consonant_outer_context
from .chorale_review import musical_checks, verify_score
from .chorale_source_protection import source_supported_resolutions
from .corpus import digest
from .model import Event, load_melody, write_json


def source_contexts(donors, placements):
    contexts = []
    for placement in placements:
        matches = [
            d
            for d in donors
            if d["source_id"] == placement["source_id"]
            and d["source_start"] == placement["source_start"]
        ]
        if len(matches) != 1:
            raise ValueError("Each source placement must identify exactly one donor")
        donor = matches[0]
        contexts.append(
            {
                "source_id": donor["source_id"],
                "source_sha256": donor["source_sha256"],
                "source_start": donor["source_start"],
                "target_start": placement["target_start"],
                "length": donor["length"],
                "events": [Event(p, a, b - a, role=r) for p, a, b, r in donor["notes"]]
                + [Event(p, a, b - a) for p, a, b in donor["melody"]],
            }
        )
    return contexts


def refine_chorale(arrangement, melody, targets, contexts=()):
    melody.validate()
    for note in arrangement.notes:
        if (
            not isinstance(note.pitch, int)
            or not 21 <= note.pitch <= 108
            or not all(math.isfinite(t) for t in (note.start, note.duration))
            or not 0 <= note.start < note.end <= melody.length
        ):
            raise ValueError("Arrangement contains an invalid note or duration")
        if note.role not in ("melody", "bass", "inner"):
            raise ValueError(
                "Refinement requires melody, bass and inner roles; "
                "explicit SATB roles must first be mapped deliberately"
            )
    if arrangement.melody_offset != 0 or arrangement.length != melody.length:
        raise ValueError(
            "Refinement expects an isolated chorale with matching duration"
        )
    if (
        [tuple(m) for m in arrangement.meters] != [tuple(m) for m in melody.meters]
        or arrangement.tonic != melody.tonic
        or arrangement.mode != melody.mode
    ):
        raise ValueError("Arrangement and melody must share meter, tonic and mode")
    before = musical_checks(arrangement, melody)
    if not before["melody_exact"]:
        raise ValueError("The arrangement does not contain the exact supplied melody")
    for target in targets:
        if not 0 <= target["start"] < target["end"] <= melody.length:
            raise ValueError("Harmonic target lies outside the chorale")
        if not target["pitch_classes"] or any(
            not isinstance(p, int) or not 0 <= p < 12
            for p in target["pitch_classes"] + target["required"]
        ):
            raise ValueError("Targets require integer pitch classes from 0 to 11")
        if not set(target["required"]) <= set(target["pitch_classes"]):
            raise ValueError("Required pitches must belong to the target chord")
    notes = arrangement.notes
    evidence = source_supported_resolutions(notes, contexts)
    fixed = [n for n in notes if n.role not in ("inner", "melody")]
    contracts, omitted = [], []
    for match in evidence:
        i, j = match["protected_indices"]
        if consonant_outer_context(notes[j], fixed, melody):
            contracts.append(
                ResolutionObligation(i, notes[i].pitch, notes[j].pitch, notes[j].start)
            )
        else:
            omitted.append(
                dict(
                    match,
                    reason="Resolution context not confirmed by the narrow outer-voice rule",
                )
            )
    contracts = list(dict.fromkeys(contracts))
    trace = {}
    revised = revoice_inner_pair(
        notes,
        melody,
        targets,
        source_contexts=contexts,
        plan_hands=True,
        obligations=contracts,
        diagnostics=trace,
    )
    report = {
        "status": "no_feasible_path",
        "before": before,
        "source_evidence": evidence,
        "contracts": [asdict(c) for c in contracts],
        "contracts_not_inferred": omitted,
        "search": trace,
        "human_votes": 0,
        "style_quality_verified": False,
    }
    if revised is None:
        return None, report
    assert [(n.start, n.end, n.role) for n in revised] == [
        (n.start, n.end, n.role) for n in notes
    ]
    assert [n for n in revised if n.role != "inner"] == [
        n for n in notes if n.role != "inner"
    ]
    result = replace(
        arrangement,
        notes=revised,
        harmony=[],
        score=trace["cost"],
        diagnostics={
            "method": "joint_inner_refinement",
            "harmonic_targets": targets,
            "source_protection": evidence,
            "hands": trace["hands"],
        },
    )
    after = musical_checks(result, melody)
    report["after"] = after
    report["changes"] = [
        {"index": i, "before": asdict(a), "after": asdict(b)}
        for i, (a, b) in enumerate(zip(notes, revised))
        if a != b
    ]
    if (
        not after["melody_exact"]
        or after["crossing_time_fraction"] > 1e-7
        or after["outer_parallel_perfects"]
        or after["bass_leaps_over_octave"]
        or after["unaccompanied_melody_time_fraction"] > 1e-7
    ):
        report["status"] = "rejected_structural_checks"
        return None, report
    report["status"] = "refined_not_style_approved"
    return result, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("arrangement", "melody", "goals", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--donors", type=Path)
    parser.add_argument("--placements", type=Path)
    parser.add_argument("--musescore")
    args = parser.parse_args()
    if bool(args.donors) != bool(args.placements):
        parser.error("Use --donors and --placements together")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory to preserve earlier results")
    paths = [args.arrangement, args.melody, args.goals]
    contexts = []
    if args.donors:
        paths += [args.donors, args.placements]
        contexts = source_contexts(
            json.loads(args.donors.read_text()), json.loads(args.placements.read_text())
        )
    result, report = refine_chorale(
        read_arrangement(args.arrangement),
        load_melody(args.melody, {}),
        json.loads(args.goals.read_text()),
        contexts,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    report["input_sha256"] = {str(p): digest(p) for p in paths}
    report["implementation_sha256"] = {
        p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    report["runtime"] = {
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("numpy", "music21", "mido")},
    }
    report["export_status"] = "not_started"
    write_json(args.output / "review.json", report)
    if result is None:
        raise SystemExit("No candidate exported: " + report["status"])
    from .chorale_lab import export

    melody = load_melody(args.melody, {})
    report["export_status"] = "in_progress"
    write_json(args.output / "review.json", report)
    try:
        report["export"] = export(
            result,
            melody,
            args.output,
            "candidate",
            "Koraal",
            hands=report["search"]["hands"],
        )
        write_json(args.output / "candidate.json", asdict(result))
        if args.musescore:
            report["musescore"] = verify_score(
                args.output / "candidate.musicxml", args.musescore
            )
        report["export_status"] = "verified" if args.musescore else "exported"
    except Exception as exc:
        report["export_status"] = "failed"
        report["export_error"] = f"{type(exc).__name__}: {exc}"
        write_json(args.output / "review.json", report)
        raise
    write_json(args.output / "review.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "changed_notes": len(report["changes"]),
                "source_protections": len(report["source_evidence"]),
                "contracts": len(report["contracts"]),
            }
        )
    )


if __name__ == "__main__":
    main()
