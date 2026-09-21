"""Descriptive musical checks, deliberately without an aggregate quality score."""

from itertools import pairwise

from .chorale_resolution import steps_to_bass_octave


def musical_checks(arrangement, melody):
    notes = arrangement.notes
    accompaniment = [n for n in notes if n.role != "melody"]
    times = sorted({t for n in notes for t in (n.start, n.end)})
    rows = []
    bass_rows = []
    resolutions = steps_to_bass_octave(notes)
    resolved_indices = {r["note_index"] for r in resolutions}
    octave_resolution_time = 0.0
    rough_time = crossed_time = accompanied_time = 0.0
    for start, end in pairwise(times):
        active = sorted({n.pitch for n in notes if n.start <= start + 1e-7 < n.end})
        top = next((n for n in melody.notes if n.start <= start + 1e-7 < n.end), None)
        below = sorted(
            {n.pitch for n in accompaniment if n.start <= start + 1e-7 < n.end}
        )
        if below:
            bass_rows.append(below[0])
        if not top or not below:
            continue
        duration = end - start
        accompanied_time += duration
        rough_time += duration * any(
            (p - active[0]) % 12 in (1, 11) for p in active[1:]
        )
        rough_indices = {
            i
            for i, n in enumerate(notes)
            if n.start <= start + 1e-7 < n.end and (n.pitch - active[0]) % 12 in (1, 11)
        }
        octave_resolution_time += duration * bool(
            rough_indices and rough_indices <= resolved_indices
        )
        crossed_time += duration * (max(below) >= top.pitch)
        rows.append((start, end, top.pitch, below[0]))
    # Follow accompaniment through melody rests. Retain the existing policy
    # of comparing successive bass observations across accompaniment silence.
    bass_moves = [abs(b - a) for a, b in pairwise(bass_rows) if a != b]
    parallels = 0
    for (_, end, top, bass), (start, _, next_top, next_bass) in pairwise(rows):
        if (
            abs(end - start) < 1e-6
            and (top - bass) % 12 in (0, 7)
            and (top - bass) % 12 == (next_top - next_bass) % 12
        ):
            parallels += (next_top - top) * (next_bass - bass) > 0
    melody_times = {round(n.start, 6) for n in melody.notes}
    bass_attacks = [
        n
        for n in accompaniment
        if n.pitch == min(x.pitch for x in notes if x.start <= n.start + 1e-7 < x.end)
    ]
    reattacks = [
        n
        for n in accompaniment
        if any(
            p.pitch == n.pitch and abs(p.end - n.start) < 1e-6 for p in accompaniment
        )
    ]
    result = {
        "melody_exact": sorted(
            (n.pitch, n.start, n.end) for n in notes if n.role == "melody"
        )
        == sorted((n.pitch, n.start, n.end) for n in melody.notes),
        "crossing_time_fraction": crossed_time / max(accompanied_time, 1e-7),
        "bass_attacks_per_melody_note": len(bass_attacks) / len(melody.notes),
        "bass_attacks_off_melody_fraction": sum(
            round(n.start, 6) not in melody_times for n in bass_attacks
        )
        / max(1, len(bass_attacks)),
        "common_pitch_reattack_fraction": len(reattacks) / max(1, len(accompaniment)),
        "bass_leaps_over_octave": sum(x > 12 for x in bass_moves),
        "outer_parallel_perfects": parallels,
        "bass_semitone_seventh_time_fraction": rough_time / max(accompanied_time, 1e-7),
        "bass_semitone_seventh_step_to_octave_time_fraction": octave_resolution_time
        / max(accompanied_time, 1e-7),
        "step_to_bass_octave_evidence": resolutions,
        "accompaniment_notes": len(accompaniment),
        "explicit_fermatas": len(melody.fermatas),
        "unaccompanied_melody_time_fraction": 1
        - accompanied_time / sum(n.duration for n in melody.notes),
    }
    return result


def verify_score(source, app):
    """Validate sounding notes and tempo/meter after an actual MuseScore import."""
    from music21 import converter

    from .chorale_lab import _musescore_export
    from .notation import _sounding
    from .score_style import score_timeline

    target = source.with_suffix(".roundtrip.musicxml")
    _musescore_export(app, source, target, source.with_suffix(".musescore.log"))
    original, imported = converter.parse(source), converter.parse(target)
    before, after = _sounding(original), _sounding(imported)
    exact = len(before) == len(after) and all(
        p == q and abs(a - c) < 1e-6 and abs(b - d) < 1e-6
        for (p, a, b), (q, c, d) in zip(before, after)
    )
    timelines = [score_timeline(s) for s in (original, imported)]
    meters = timelines[0]["meters"] == timelines[1]["meters"]
    tempi = [[(t["start"], t["quarter_bpm"]) for t in x["tempos"]] for x in timelines]
    if not exact or not meters or tempi[0] != tempi[1]:
        raise ValueError(f"MuseScore changed notes, meter or tempo: {source}")
    pdf = source.with_suffix(".pdf")
    _musescore_export(app, source, pdf, source.with_suffix(".pdf.log"))
    if not pdf.read_bytes().startswith(
        b"%PDF"
    ) or not pdf.read_bytes().rstrip().endswith(b"%%EOF"):
        raise ValueError(f"Incomplete PDF: {pdf}")
    return {
        "notes": len(before),
        "exact": True,
        "meters_and_tempos_exact": True,
        # A complete PDF container does not prove that systems fit on its pages.
        "pdf_layout_status": "requires_visual_review",
    }


def main():
    import argparse
    import json
    import random
    from dataclasses import asdict
    from html import escape
    from pathlib import Path

    from .chorale_gestures import upgrade_model
    from .chorale_lab import export, load_entry, score_from_midi
    from .chorale_model import generate_chorale, model_hash
    from .corpus import digest
    from .model import write_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--musescore")
    parser.add_argument("--include-regressions", action="store_true")
    parser.add_argument("--cadence-contexts", action="store_true")
    parser.add_argument("--phrase-harmony", action="store_true")
    parser.add_argument("--continuous-accompaniment", action="store_true")
    parser.add_argument("--two-pass-bass", action="store_true")
    parser.add_argument("--phrase-rhythm", action="store_true")
    parser.add_argument(
        "--historical", type=Path, default=Path("private_data/stijlanalyse.json")
    )
    parser.add_argument("--splits", type=Path, default=Path("splits.json"))
    args = parser.parse_args()
    if args.two_pass_bass and args.phrase_rhythm:
        parser.error("Choose one experimental decoder.")
    if (args.two_pass_bass or args.phrase_rhythm) and (
        args.cadence_contexts or args.phrase_harmony or args.continuous_accompaniment
    ):
        parser.error(
            "Two-pass comparison uses the unchanged baseline corpus; do not combine fitting flags."
        )
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory to preserve previous reviews.")
    args.output.mkdir(parents=True, exist_ok=True)
    entries = json.loads(args.corpus.read_text())["entries"]
    baseline = json.loads(args.baseline.read_text())
    training = [
        load_entry(e) for e in entries if e["source_id"] in baseline["training_ids"]
    ]
    if args.two_pass_bass or args.phrase_rhythm:
        required = ("gestures", "phrase_chords", "register_profiles", "rest_contexts")
        if any(key not in baseline for key in required):
            parser.error(
                "Two-pass planning requires a fitted phrase-continuity baseline."
            )
        model = dict(baseline, decoder="two_pass_bass_v1")
        if args.phrase_rhythm:
            from .chorale_rhythm_plan import fit_rhythm

            model = fit_rhythm(baseline, training)
    else:
        model = upgrade_model(baseline, training)
    if args.cadence_contexts:
        from .chorale_cadences import collect, cross_validate

        model = collect(model, entries, args.historical, args.splits)
        write_json(args.output / "cadence_cross_validation.json", cross_validate(model))
    if args.phrase_harmony or args.continuous_accompaniment:
        from .chorale_phrases import fit_phrases

        model = fit_phrases(model, training)
    if args.continuous_accompaniment:
        from .chorale_continuity import cross_validate_continuity, fit_continuity

        model = fit_continuity(model, training)
        write_json(
            args.output / "continuity_cross_validation.json",
            cross_validate_continuity(model, training),
        )
    write_json(args.output / "model.json", model)
    write_json(
        args.output / "protocol.json",
        {
            "baseline_sha256": model_hash(baseline),
            "model_sha256": model_hash(model),
            "rubric_sha256": digest(Path("HARMONISATIE_BEOORDELING.md")),
            "phrase_rubric_sha256": digest(Path("FRASE_BEOORDELING.md"))
            if args.phrase_harmony or args.two_pass_bass or args.phrase_rhythm
            else None,
            "cadence_rubric_sha256": digest(Path("CADENS_BEOORDELING.md"))
            if args.cadence_contexts
            else None,
            "implementation_sha256": {
                p.name: digest(p)
                for p in [
                    Path(__file__),
                    Path(__file__).with_name("chorale_gestures.py"),
                    Path(__file__).with_name("chorale_model.py"),
                    Path(__file__).with_name("chorale_cadences.py"),
                    Path(__file__).with_name("chorale_phrases.py"),
                    Path(__file__).with_name("chorale_continuity.py"),
                    Path(__file__).with_name("chorale_bass_plan.py"),
                    Path(__file__).with_name("chorale_rhythm_plan.py"),
                    Path(__file__).with_name("chorale_phrase_transfer.py"),
                ]
            },
            "training_ids": model["training_ids"],
            "no_wav": True,
            "test_status": "Previously examined test pieces are regression cases, not fresh holdout.",
            "assessment": "Descriptive checks and non-blind score inspection. No aggregate quality score.",
        },
    )
    rows, answer_key, pages, blind_pages = [], {}, [], []
    for entry in entries:
        if entry["split"] != "validation" and not (
            args.include_regressions and entry["split"] == "test"
        ):
            continue
        _, melody, reference = load_entry(entry)
        directory = args.output / entry["tune"]
        directory.mkdir()
        row = {"id": entry["source_id"], "tune": entry["tune"], "split": entry["split"]}
        arrangements = {
            "before": generate_chorale(melody, baseline),
            "after": generate_chorale(melody, model),
            "reference": reference,
        }
        for label, arrangement in arrangements.items():
            result = export(arrangement, melody, directory, label, "Koraal")
            row[label] = musical_checks(
                score_from_midi(directory / f"{label}.mid", melody, arrangement), melody
            )
            if (
                args.continuous_accompaniment
                or args.two_pass_bass
                or args.phrase_rhythm
            ):
                from .chorale_continuity import compare_rest_support

                row[label + "_rest_support"] = compare_rest_support(
                    reference,
                    score_from_midi(directory / f"{label}.mid", melody, arrangement),
                    melody,
                )
            write_json(directory / f"{label}.arrangement.json", asdict(arrangement))
            if (
                args.phrase_harmony
                or args.continuous_accompaniment
                or args.two_pass_bass
                or args.phrase_rhythm
            ):
                from .chorale_phrases import phrase_checks

                row[label + "_phrase"] = phrase_checks(
                    score_from_midi(directory / f"{label}.mid", melody, arrangement),
                    melody,
                )
            row[label + "_export"] = result
            if args.musescore:
                row[label + "_musescore"] = verify_score(
                    directory / f"{label}.musicxml", args.musescore
                )
        # New/reference pair for manual inspection. The HTML does not contain
        # provenance or filled ratings. The key is in a separate local file.
        pair_id = f"pair_{len(rows) + 1:02d}"
        blind_dir = args.output / "blind" / pair_id
        blind_dir.mkdir(parents=True)
        origins = ["reference", "after"]
        random.Random(entry["source_id"]).shuffle(origins)
        answer_key[pair_id] = dict(zip(("A", "B"), origins))
        for label, origin in zip(("A", "B"), origins):
            for suffix in [".mid", ".musicxml"] + ([".pdf"] if args.musescore else []):
                (blind_dir / (label + suffix)).write_bytes(
                    (directory / (origin + suffix)).read_bytes()
                )
        blind_pages.append(
            f"<li>{pair_id}: "
            + " | ".join(
                f'<a href="blind/{pair_id}/{label}{suffix}">{label} {suffix[1:]}</a>'
                for label in ("A", "B")
                for suffix in [".mid", ".musicxml"]
                + ([".pdf"] if args.musescore else [])
            )
            + "</li>"
        )
        pages.append(
            f"<h2>{escape(entry['tune'])}</h2><p>"
            + " | ".join(
                f'<a href="{entry["tune"]}/{label}{suffix}">{label} {suffix[1:]}</a>'
                for label in arrangements
                for suffix in [".mid", ".musicxml"]
                + ([".pdf"] if args.musescore else [])
            )
            + "</p>"
        )
        rows.append(row)
        write_json(args.output / "results.json", rows)
        print(entry["tune"], "verified", flush=True)
    write_json(args.output / "answer_key.json", answer_key)
    write_json(
        args.output / "human_ratings.json",
        [
            {
                "pair": p,
                "koele": None,
                "preference": None,
                "confidence": None,
                "notes": "",
            }
            for p in answer_key
        ],
    )
    (args.output / "blind.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Blinde koralen</title><h1>Blinde koralen</h1><p>Welke versie is van Koele? Welke heeft je voorkeur? Noteer ook je zekerheid en maatnummers.</p><ul>'
        + "".join(blind_pages)
        + "</ul>"
    )
    (args.output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Koraalbeoordeling</title><h1>Koraalbeoordeling</h1><p>Niet-blinde vergelijking: before = vorig model, after = nieuwe motor, reference = transcriptie. Eerdere teststukken zijn regressiegevallen.</p><a href="blind.html">Blinde partituren</a>'
        + "".join(pages)
    )


if __name__ == "__main__":
    main()
