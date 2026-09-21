"""Twenty sequential symbolic A/B rounds, with a frozen label-blind judge.

These are development experiments against provisional transcriptions. A fixed
statistical judge is not a human musical assessment or proof of authorship.
"""

import argparse
import json
import random
import subprocess
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from html import escape
from pathlib import Path

import mido
import numpy as np
from music21 import converter

from .audit import read_arrangement
from .chorale_model import (
    FEATURE_SCALES,
    feature_distance,
    features,
    fit,
    generate_chorale,
    model_hash,
)
from .corpus import digest
from .midi import save_midi, validate_export
from .model import Event, load_melody, write_json
from .notation import _sounding, save_musicxml
from .score_style import score_timeline


def load_entry(entry):
    directory = Path(entry["directory"])
    if digest(Path(entry["source_path"])) != entry["source_sha256"]:
        raise ValueError("Bronpartituur gewijzigd sinds voorselectie.")
    for name in (
        "melody.json",
        "reference.json",
        "reference.mid",
        "reference.musicxml",
    ):
        if digest(directory / name) != entry.get("artifact_sha256", {}).get(name):
            raise ValueError(
                "Het geëxtraheerde referentiebestand is gewijzigd of heeft geen controlehash."
            )
    return (
        entry,
        load_melody(directory / "melody.json", {}),
        read_arrangement(directory / "reference.json"),
    )


def fit_judge(references):
    vectors = [features(a, m) for _, m, a in references]
    names = sorted(vectors[0])
    center = {k: float(np.median([v[k] for v in vectors])) for k in names}
    scale = {
        k: max(FEATURE_SCALES.get(k, 0.15), float(np.std([v[k] for v in vectors])))
        for k in names
    }
    return {
        "version": 1,
        "kind": "frozen_robust_feature_distance",
        "center": center,
        "scale": scale,
        "training_groups": [e["group"] for e, _, _ in references],
        "limitations": [
            "Drie referenties geven een smalle stijlbasis.",
            "Scores zijn afstanden, geen kans op auteurschap.",
        ],
    }


def blind_predict(judge, packet):
    """Pure function: receives only A/B features, no IDs, paths or answer key."""
    if set(packet) != {"A", "B"}:
        raise ValueError("Een blinde vergelijking vereist A en B.")
    if any(set(vector) != set(judge["center"]) for vector in packet.values()):
        raise ValueError(
            "De beoordelaar accepteert uitsluitend de vastgelegde muziekkenmerken."
        )
    distances = {
        label: float(
            np.mean(
                [
                    min(5, abs(vector[k] - judge["center"][k]) / judge["scale"][k])
                    for k in judge["center"]
                ]
            )
        )
        for label, vector in packet.items()
    }
    margin = abs(distances["A"] - distances["B"])
    return {
        "choice": min(distances, key=distances.get) if margin >= 0.01 else None,
        "distances": distances,
        "margin": margin,
        "confidence_is_probability": False,
        "method": "Frozen symbolic similarity; no origin metadata supplied.",
    }


def score_from_midi(path, melody, template):
    midi = mido.MidiFile(path)
    expected = Counter(
        (n.pitch, round(n.start, 7), round(n.end, 7)) for n in melody.notes
    )
    remaining = expected.copy()
    notes = []
    for track in midi.tracks:
        time = 0
        active = {}
        for msg in track:
            time += msg.time
            if msg.type == "note_on" and msg.velocity:
                if msg.note in active:
                    raise ValueError("Overlappende MIDI-noot.")
                active[msg.note] = (time, msg.velocity)
            elif msg.type == "note_off" or msg.type == "note_on" and not msg.velocity:
                start, velocity = active.pop(msg.note)
                a, b = start / midi.ticks_per_beat, time / midi.ticks_per_beat
                signature = (msg.note, round(a, 7), round(b, 7))
                role = (
                    "melody"
                    if remaining[signature] > 0
                    else "bass"
                    if track.name == "Piano LH"
                    else "inner"
                )
                if role == "melody":
                    remaining[signature] -= 1
                notes.append(Event(msg.note, a, b - a, velocity, role))
        if active:
            raise ValueError("Onbeëindigde MIDI-noten.")
    if any(remaining.values()):
        raise ValueError("Melodie ontbreekt in de daadwerkelijke MIDI.")
    return replace(template, notes=sorted(notes, key=lambda n: (n.start, n.pitch)))


def export(arrangement, melody, directory, name, title, *, hands=None):
    if hands is None:
        hands = arrangement.diagnostics.get("hands")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    normalized = replace(
        arrangement,
        notes=[replace(n, velocity=72) for n in arrangement.notes],
        seed=0,
        diagnostics={},
    )
    mid = directory / f"{name}.mid"
    xml = directory / f"{name}.musicxml"
    save_midi(normalized, mid, {})
    midi_checks = validate_export(mid, normalized)
    notation_checks = save_musicxml(
        normalized, xml, melody.tonic, melody.mode, title, hands=hands
    )
    parsed = score_from_midi(mid, melody, normalized)
    return {
        "midi_sha256": digest(mid),
        "musicxml_sha256": digest(xml),
        "midi_checks": midi_checks,
        "notation_checks": notation_checks,
        "features": features(parsed, melody),
    }


def validation_loss(model, references):
    values = []
    for _, melody, reference in references:
        generated = generate_chorale(melody, model, seed=731, tempos=reference.tempos)
        values.append(
            feature_distance(features(generated, melody), features(reference, melody))
        )
    return float(np.mean(values))


def proposals(current, observed, iteration):
    p = current["parameters"]
    variants = [dict(p)]
    for strength in (0.35, 0.7, 1.0):
        variants.append(dict(p, texture_strength=strength))
    if p["texture_strength"] > 0:
        variants.extend([dict(p, movement_weight=x) for x in (0.03, 0.16)])
        variants.extend([dict(p, subdivision_scale=x) for x in (0.0, 0.75)])
        variants.append(dict(p, hold_common=not p["hold_common"]))
    seen = set()
    for parameters in variants:
        key = json.dumps(parameters, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        yield fit(observed, iteration, parameters)


def run(corpus, output, rounds=20, seed=20260920):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Gebruik een lege experimentmap.")
    index = json.loads((Path(corpus) / "index.json").read_text())
    entries = index["entries"]
    train = [e for e in entries if e["split"] == "train"]
    bootstrap = [
        e for e in train if e["tune"] in ("psalm_37", "psalm_85", "holy_holy_holy")
    ]
    if len(bootstrap) != 3:
        raise ValueError("De drie startreferenties ontbreken.")
    trials = [e for e in train if e not in bootstrap]
    if len(trials) < rounds:
        raise ValueError(
            f"Slechts {len(trials)} onafhankelijke trainingskoralen beschikbaar."
        )
    random.Random(seed).shuffle(trials)
    trials = trials[:rounds]
    validation = [load_entry(e) for e in entries if e["split"] == "validation"]
    if not validation:
        raise ValueError("Validatiekoralen ontbreken.")
    observed = [load_entry(e) for e in bootstrap]
    current = fit(observed)
    baseline = deepcopy(current)
    judge = fit_judge(observed)
    judge_digest = model_hash(judge)
    output.mkdir(parents=True)
    write_json(output / "judge.json", judge)
    write_json(output / "models/v00.json", current)
    write_json(
        output / "protocol.json",
        {
            "seed": seed,
            "rounds": rounds,
            "bootstrap": [e["source_id"] for e in bootstrap],
            "trial_order": [e["source_id"] for e in trials],
            "validation": [e["source_id"] for e, _, _ in validation],
            "test": [e["source_id"] for e in entries if e["split"] == "test"],
            "reference_status": "provisional_transcriptions",
            "no_wav": True,
            "judge_frozen_sha256": judge_digest,
            "implementation_sha256": {
                p.name: digest(p) for p in Path(__file__).parent.glob("*.py")
            },
            "adaptation": "Re-estimate empirical voicing counts after reveal; accept parameters only on separate validation songs.",
        },
    )
    old_loss = validation_loss(current, validation)
    initial_validation = old_loss
    reports = []
    answers = {}
    for iteration, entry in enumerate(trials, 1):
        row, melody, reference = load_entry(entry)
        if (
            row["group"] in current["training_groups"]
            or row["group"] in judge["training_groups"]
        ):
            raise ValueError(
                "Huidig testkoraal is al in model of beoordelaar opgenomen."
            )
        if model_hash(judge) != judge_digest:
            raise ValueError("De blinde beoordelaar is veranderd.")
        generated = generate_chorale(melody, current, seed=731, tempos=reference.tempos)
        directory = output / f"round_{iteration:02}"
        labels = ["A", "B"]
        random.Random(seed + iteration * 1009).shuffle(labels)
        # The answer mapping remains with the coordinator and is not passed to
        # the pure judge. Commit its prediction before serializing the key.
        artifacts = {
            labels[0]: export(
                reference, melody, directory, labels[0], f"Koraal {iteration:02}"
            ),
            labels[1]: export(
                generated, melody, directory, labels[1], f"Koraal {iteration:02}"
            ),
        }
        packet = {label: artifact["features"] for label, artifact in artifacts.items()}
        write_json(directory / "judge_packet.json", packet)
        prediction = blind_predict(judge, packet)
        write_json(directory / "blind_prediction.json", prediction)
        prediction_hash = digest(directory / "blind_prediction.json")
        answers[str(iteration)] = {
            "reference": labels[0],
            "generated": labels[1],
            "source_id": row["source_id"],
            "prediction_committed_sha256": prediction_hash,
        }
        real = packet[labels[0]]
        fake = packet[labels[1]]
        deltas = sorted(
            [
                {
                    "feature": k,
                    "reference": real[k],
                    "generated": fake[k],
                    "scaled_error": abs(real[k] - fake[k])
                    / FEATURE_SCALES.get(k, 0.15),
                }
                for k in real
            ],
            key=lambda x: -x["scaled_error"],
        )
        report = {
            "round": iteration,
            "source_id": row["source_id"],
            "tune": row["tune"],
            "model_before_sha256": model_hash(current),
            "training_before": list(current["training_ids"]),
            "judge_sha256": judge_digest,
            "prediction_sha256": prediction_hash,
            "correct_identification": prediction["choice"] == labels[0]
            if prediction["choice"]
            else None,
            "prediction": prediction,
            "paired_feature_error": feature_distance(real, fake),
            "largest_differences": deltas[:8],
            "artifacts": artifacts,
        }
        # Only now can this reference influence the generator.
        observed.append((row, melody, reference))
        attempts = []
        best = current
        best_loss = old_loss
        for candidate in proposals(current, observed, iteration):
            loss = validation_loss(candidate, validation)
            attempts.append(
                {
                    "parameters": candidate["parameters"],
                    "validation_loss": loss,
                    "model_sha256": model_hash(candidate),
                }
            )
            if loss < best_loss - 1e-5:
                best, best_loss = candidate, loss
        report.update(
            validation_before=old_loss,
            validation_after=best_loss,
            accepted=model_hash(best) != model_hash(current),
            attempts=attempts,
        )
        current = best
        old_loss = best_loss
        report["model_after_sha256"] = model_hash(current)
        write_json(output / f"models/v{iteration:02}.json", current)
        write_json(directory / "after_reveal.json", report)
        reports.append(report)
        write_json(output / "answers/answer_key.json", answers)
        print(
            f"Round {iteration:02}: {row['tune']} | identified={report['correct_identification']} | validation {report['validation_before']:.3f} -> {best_loss:.3f} | accepted={report['accepted']}",
            flush=True,
        )
    # Final test material is first loaded after all adaptation decisions.
    tests = []
    frozen_final = model_hash(current)
    for entry in entries:
        if entry["split"] != "test":
            continue
        row, melody, reference = load_entry(entry)
        assert row["group"] not in current["training_groups"]
        gold = features(reference, melody)
        original = generate_chorale(melody, baseline, 731, reference.tempos)
        final = generate_chorale(melody, current, 731, reference.tempos)
        tests.append(
            {
                "source_id": row["source_id"],
                "tune": row["tune"],
                "baseline_error": feature_distance(features(original, melody), gold),
                "final_error": feature_distance(features(final, melody), gold),
            }
        )
    assert model_hash(current) == frozen_final
    write_json(output / "final_model.json", current)
    summary = {
        "rounds": rounds,
        "accepted_updates": sum(r["accepted"] for r in reports),
        "automatic_correct": sum(r["correct_identification"] is True for r in reports),
        "automatic_abstentions": sum(
            r["correct_identification"] is None for r in reports
        ),
        "initial_validation_error": initial_validation,
        "final_validation_error": old_loss,
        "test_results": tests,
        "test_baseline_error": float(np.mean([t["baseline_error"] for t in tests])),
        "test_final_error": float(np.mean([t["final_error"] for t in tests])),
        "final_model_sha256": frozen_final,
        "musical_acceptance": "not_established",
        "human_ratings": "pending",
        "limitations": [
            "De referenties zijn transcripties, geen geverifieerde gold standard.",
            "De bevroren beoordelaar ziet alleen symbolische kenmerken en is op drie koralen gebaseerd.",
            "Validatie is voor modelselectie hergebruikt. Alleen de laatste test is buiten de twintig aanpassingen gehouden.",
            "Minder herkenbaar voor de automatische beoordelaar bewijst geen betere muziek.",
        ],
    }
    write_json(output / "summary.json", summary)
    write_pages(output, reports)
    return summary


def write_pages(output, reports):
    style = "<style>body{font:17px system-ui;max-width:1100px;margin:35px auto;padding:20px;line-height:1.5}article{border-top:1px solid #bbb;padding:20px 0}.pair{display:flex;gap:30px}.pair>div{flex:1}select,button{padding:8px}textarea{width:90%;height:55px}a{color:#176353}</style>"
    page = f'<!doctype html><html lang="nl"><meta charset="utf-8"><title>Twintig blinde koraalvergelijkingen</title>{style}<h1>Welke versie komt uit Koeles transcriptie?</h1><p>Alleen harmonisaties: dezelfde melodie, maat en tempo, zonder voor- of naspel. Open A en B in MuseScore, of gebruik de PDF. Er zijn geen WAV-bestanden. Bronlabels en automatische uitslagen staan apart. Beoordeel eerst, bekijk daarna pas de bronnen.</p>'
    ratings = []
    for r in reports:
        number = r["round"]
        folder = f"round_{number:02}"
        page += f'<article data-round="{number}"><h2>Koraal {number:02}</h2><div class="pair">'
        for label in ("A", "B"):
            page += f'<div><h3>{label}</h3><a href="{folder}/{label}.musicxml">MuseScore-partituur</a> · <a href="{folder}/{label}.mid">MIDI</a>'
            if (output / folder / f"{label}.pdf").exists():
                page += f' · <a href="{folder}/{label}.pdf">PDF</a>'
            page += "</div>"
        page += (
            '</div><p>Welke is Koele? <select data-field="choice"><option value="">Nog niet beoordeeld</option><option>A</option><option>B</option><option>Onbeslist</option></select> Zekerheid <select data-field="confidence"><option value="">Kies</option>'
            + "".join(f"<option>{x}</option>" for x in range(1, 6))
            + '</select></p><p>Welke harmonisatie vind je beter? <select data-field="preference"><option value="">Kies</option><option>A</option><option>B</option><option>Gelijkwaardig</option></select></p><textarea data-field="notes" placeholder="Welke harmonische wendingen, basbewegingen of stemvoeringen maken het verschil?"></textarea></article>'
        )
        ratings.append(
            {
                "round": number,
                "choice": None,
                "confidence": None,
                "preference": None,
                "notes": "",
            }
        )
    page += """<button onclick="save()">Beoordeling downloaden</button><script>function save(){const rows=[...document.querySelectorAll('article')].map(e=>{const r={round:+e.dataset.round};for(const f of e.querySelectorAll('[data-field]'))r[f.dataset.field]=f.value||null;return r;});const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));a.download='human_ratings.json';a.click();URL.revokeObjectURL(a.href);}</script><p><a href="review.html">Automatisch rapport en bronnen: pas na beoordeling openen</a></p></html>"""
    (output / "blind.html").write_text(page)
    if not (output / "human_ratings.json").exists():
        write_json(output / "human_ratings.json", ratings)
    summary = json.loads((output / "summary.json").read_text())
    review = f'<!doctype html><html lang="nl"><meta charset="utf-8"><title>Koraalexperiment: resultaten</title>{style}<h1>Twintig automatische koraalrondes</h1><p><a href="blind.html">Blinde partituren</a></p><p>{summary["accepted_updates"]} aanpassingen overgenomen. De beoordelaar wees {summary["automatic_correct"]} van de {summary["rounds"]} keer de transcriptie aan, met {summary["automatic_abstentions"]} onbesliste rondes.</p>'
    review += f"<p>Gemiddelde validatiefout: {summary['initial_validation_error']:.3f} → {summary['final_validation_error']:.3f}. Eenmalige toets op {len(summary['test_results'])} apart gehouden koralen: {summary['test_baseline_error']:.3f} → {summary['test_final_error']:.3f}. Dit zijn afstanden tussen symbolische kenmerken; lager is beter volgens deze maat, niet automatisch muzikaal beter.</p>"
    review += (
        "<ul>"
        + "".join(f"<li>{escape(x)}</li>" for x in summary["limitations"])
        + '</ul><p><a href="summary.json">Meetresultaten</a> · <a href="protocol.json">Protocol</a> · <a href="final_model.json">Model na twintig rondes</a> · <a href="answers/answer_key.json">Antwoordsleutel</a></p><table><tr><th>Ronde</th><th>Bron</th><th>Herkenning</th><th>Validatie</th><th>Aangepast</th></tr>'
    )
    for r in reports:
        review += f'<tr><td><a href="round_{r["round"]:02}/after_reveal.json">{r["round"]}</a></td><td>{escape(r["tune"])}</td><td>{r["correct_identification"]}</td><td>{r["validation_before"]:.3f} → {r["validation_after"]:.3f}</td><td>{r["accepted"]}</td></tr>'
    review += "</table><h2>De zes apart gehouden testkoralen</h2><table><tr><th>Koraal</th><th>Beginmodel</th><th>Eindmodel</th><th>Verschil</th></tr>"
    for row in summary["test_results"]:
        verdict = "Lager" if row["final_error"] < row["baseline_error"] else "Hoger"
        review += f"<tr><td>{escape(row['tune'])}</td><td>{row['baseline_error']:.3f}</td><td>{row['final_error']:.3f}</td><td>{verdict}</td></tr>"
    review += "</table>"
    verification = output / "musescore_verification.json"
    if verification.exists():
        checked = json.loads(verification.read_text())
        review += f'<p>{len(checked)} partituren werkelijk door MuseScore gehaald; {sum(x["notes"] for x in checked)} noten behouden. <a href="musescore_verification.json">Uitvoercontrole</a>.</p>'
    if (output / "visual_review.md").exists():
        review += '<p><a href="visual_review.md">Niet-blinde visuele beoordeling en resterende tekortkomingen</a></p>'
    (output / "review.html").write_text(review + "</html>")


def _musescore_export(app, source, target, log_path):
    """Retry startup failures, then audit the artifact rather than the exit code."""
    target.unlink(missing_ok=True)
    for attempt in range(3):
        with log_path.open("a") as log:
            log.write(f"\nExport attempt {attempt + 1}\n")
            try:
                result = subprocess.run(
                    [str(app), "-o", str(target), str(source)],
                    stdout=log,
                    stderr=log,
                    check=False,
                    timeout=45,
                )
            except subprocess.TimeoutExpired:
                continue
        if target.exists():
            return result.returncode
    raise ValueError(f"MuseScore leverde geen bestand na drie pogingen: {source}")


def verify_musescore(output, app):
    output = Path(output)
    results = []
    for directory in sorted(output.glob("round_*")):
        for label in ("A", "B"):
            source = directory / f"{label}.musicxml"
            target = directory / f"{label}.roundtrip.musicxml"
            cached = (
                target.exists() and target.stat().st_mtime >= source.stat().st_mtime
            )
            exit_code = (
                None
                if cached
                else _musescore_export(
                    app, source, target, directory / f"{label}.musescore.log"
                )
            )
            parsed_source, parsed_target = (
                converter.parse(source),
                converter.parse(target),
            )
            before = _sounding(parsed_source)
            after = _sounding(parsed_target)
            if len(before) != len(after) or any(
                p != q or abs(a - c) > 1e-6 or abs(b - d) > 1e-6
                for (p, a, b), (q, c, d) in zip(before, after)
            ):
                raise ValueError(f"MuseScore veranderde noten: {source}")
            original_timeline, imported_timeline = (
                score_timeline(parsed_source),
                score_timeline(parsed_target),
            )
            if original_timeline["meters"] != imported_timeline["meters"]:
                raise ValueError(f"MuseScore veranderde maatsoorten: {source}")
            before_tempos = [
                (t["start"], t["quarter_bpm"]) for t in original_timeline["tempos"]
            ]
            after_tempos = [
                (t["start"], t["quarter_bpm"]) for t in imported_timeline["tempos"]
            ]
            if before_tempos != after_tempos:
                raise ValueError(f"MuseScore veranderde tempi: {source}")
            pdf = directory / f"{label}.pdf"
            if not pdf.exists() or pdf.stat().st_mtime < source.stat().st_mtime:
                _musescore_export(app, source, pdf, directory / f"{label}.pdf.log")
            if not pdf.read_bytes().startswith(
                b"%PDF"
            ) or not pdf.read_bytes().rstrip().endswith(b"%%EOF"):
                raise ValueError("PDF ontbreekt of is onvolledig.")
            results.append(
                {
                    "round": directory.name,
                    "label": label,
                    "notes": len(before),
                    "exact": True,
                    "exit": exit_code,
                    "verified_existing_export": cached,
                    "source_sha256": digest(source),
                    "meters_and_tempos_exact": True,
                }
            )
            write_json(output / "musescore_verification.json", results)
        print(directory.name, "MIDI/MusicXML/PDF verified", flush=True)
    write_pages(
        output,
        [
            json.loads(p.read_text())
            for p in sorted(output.glob("round_*/after_reveal.json"))
        ],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--corpus", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--rounds", type=int, default=20)
    v = sub.add_parser("verify")
    v.add_argument("--output", type=Path, required=True)
    v.add_argument(
        "--musescore",
        type=Path,
        default=Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
    )
    g = sub.add_parser("generate")
    g.add_argument("melody", type=Path)
    g.add_argument("--model", type=Path, required=True)
    g.add_argument("--config", type=Path)
    g.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.command == "run":
        print(json.dumps(run(a.corpus, a.output, a.rounds), indent=2))
    elif a.command == "verify":
        verify_musescore(a.output, a.musescore)
    else:
        if a.output.exists() and any(a.output.iterdir()):
            p.error("Kies een lege uitvoermap.")
        config = json.loads(a.config.read_text()) if a.config else {}
        melody = load_melody(a.melody, config)
        model = json.loads(a.model.read_text())
        arrangement = generate_chorale(melody, model)
        checks = export(arrangement, melody, a.output, "harmonisatie", "Harmonisatie")
        write_json(a.output / "arrangement.json", asdict(arrangement))
        write_json(a.output / "report.json", checks)
        print(a.output)


if __name__ == "__main__":
    main()
