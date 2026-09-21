import argparse
import json
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .audit import musical_audit
from .composition import choose_diverse
from .corpus import digest
from .engine import generate
from .midi import render, save_midi, validate_export
from .model import load_melody, write_json
from .notation import save_musicxml


def main():
    parser = argparse.ArgumentParser(
        description="Maak een pianoarrangement met vaste melodie, voorspel en naspel."
    )
    parser.add_argument("melody", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--profile", type=Path, default=Path("private_data/harmonizer/profile.json")
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    allowed = {
        "melody_track",
        "melody_part",
        "key",
        "tempo",
        "phrases",
        "meters",
        "length",
        "intro_beats",
        "outro_beats",
        "seed",
        "candidates",
        "allow_draft",
        "soundfont",
        "aria",
        "sections",
        "style_analysis",
    }
    unknown = set(config) - allowed
    if unknown:
        parser.error("Onbekende instellingen: " + ", ".join(sorted(unknown)))
    if args.output.exists() and any(args.output.iterdir()):
        parser.error(
            "Uitvoermap is niet leeg. Kies een nieuwe map om eerdere resultaten te bewaren."
        )
    melody = load_melody(args.melody, config)
    profile = json.loads(args.profile.read_text())
    if config.get("style_analysis"):
        style = json.loads(Path(config["style_analysis"]).read_text())
        for section in style["section_library"]:
            if digest(Path(section["source_path"])) != section["source_sha256"]:
                parser.error("Stijlanalyse is verouderd: bronpartituur gewijzigd.")
        profile["section_library"] = style["section_library"]
        profile["style_analysis_sha256"] = digest(Path(config["style_analysis"]))
    args.output.mkdir(parents=True, exist_ok=True)
    melody.save(args.output / "input.melody.json")
    write_json(args.output / "profile.json", profile)
    candidates = generate(melody, profile, config)
    report = {
        "version": __version__,
        "status": "technical_preview"
        if profile["status"] != "reviewed"
        else "awaiting_listening",
        "input_sha256": digest(args.melody),
        "profile_sha256": digest(args.profile),
        "config": config,
        "profile_sources": len(profile["sources"]),
        "candidate_count": len(candidates),
        "candidates": [],
        "musical_acceptance": "pending human listening",
        "limitations": profile.get("limitations", []),
    }
    import importlib.metadata

    report["dependencies"] = {
        name: importlib.metadata.version(name)
        for name in ("music21", "pretty_midi", "mido", "numpy", "scipy")
    }
    report["implementation_sha256"] = {
        path.name: digest(path) for path in sorted(Path(__file__).parent.glob("*.py"))
    }
    private_candidates = args.output / "candidates"
    private_candidates.mkdir()
    for index, arrangement in enumerate(candidates):
        stem = f"candidate_{index + 1:02}"
        structural, performance = (
            private_candidates / (stem + ".score.mid"),
            private_candidates / (stem + ".performance.mid"),
        )
        save_midi(arrangement, structural, profile)
        save_midi(arrangement, performance, profile, expressive=True)
        checks = validate_export(structural, arrangement)
        checks["performance"] = validate_export(
            performance, arrangement, expressive=True, profile=profile
        )
        write_json(private_candidates / (stem + ".json"), asdict(arrangement))
        report["candidates"].append(
            {
                "id": stem,
                "score": arrangement.score,
                "seed": arrangement.seed,
                "structural_midi": str(structural.relative_to(args.output)),
                "performance_midi": str(performance.relative_to(args.output)),
                "checks": checks,
                "musical_audit": musical_audit(arrangement, profile, performance),
                "composition": arrangement.diagnostics.get("composition", {}),
            }
        )
    if config.get("aria"):
        from .aria import rank_candidates

        report["aria"] = rank_candidates(
            args.output, report["candidates"], config["aria"]
        )
    chosen = choose_diverse(report["candidates"], candidates)
    import shutil

    for i, c in enumerate(chosen, 1):
        arrangement = candidates[int(c["id"].split("_")[-1]) - 1]
        c["notation_checks"] = save_musicxml(
            arrangement,
            args.output / f"arrangement_{i}.score.musicxml",
            tonic=melody.tonic,
            mode=melody.mode,
            title=melody.title,
        )
        for field, suffix in (
            ("structural_midi", "score.mid"),
            ("performance_midi", "performance.mid"),
        ):
            shutil.copyfile(
                args.output / c[field], args.output / f"arrangement_{i}.{suffix}"
            )
        if config.get("soundfont"):
            report["render"] = render(
                args.output / f"arrangement_{i}.performance.mid",
                args.output / f"arrangement_{i}.wav",
                config["soundfont"],
            )
    report["selected"] = [c["id"] for c in chosen]
    write_json(args.output / "report.json", report)
    print(f"{len(chosen)} arrangementen: {args.output.resolve()}")
    print(
        "Status:",
        report["status"],
        "| melodie na export gecontroleerd | luisterbeoordeling nog nodig",
    )


if __name__ == "__main__":
    main()
