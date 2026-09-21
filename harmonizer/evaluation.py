"""Prepare local blinded listening tests and evaluate explicitly entered ratings."""

import argparse
import json
import math
import random
import subprocess
from pathlib import Path

from .model import write_json

DIMENSIONS = ("melody", "harmony", "piano", "form", "style")
LABELS = {
    "phrase": "Fraseverband",
    "independence": "Zelfstandigheid voorspel",
    "harmony": "Harmonische afwisseling",
    "transition": "Overgangen",
    "ending": "Slotwerking",
}


def loudness(path):
    measured = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "loudnorm=I=-18:TP=-2:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # Some ffmpeg versions append muxer statistics after the JSON object.
    report, _ = json.JSONDecoder().raw_decode(
        measured.stderr[measured.stderr.rfind("{") :]
    )
    value = {
        "integrated_lufs": float(report["input_i"]),
        "true_peak_db": float(report["input_tp"]),
    }
    if not all(math.isfinite(x) for x in value.values()):
        raise ValueError(
            "Een stille of ongeldige opname kan niet worden genormaliseerd."
        )
    return value


def common_loudness_target(levels):
    return min(-18, *(x["integrated_lufs"] - 2 - x["true_peak_db"] for x in levels))


def prepare(spec_path, output, seed=0):
    spec = json.loads(Path(spec_path).read_text())
    dimensions = spec.get("dimensions", DIMENSIONS)
    if (
        not dimensions
        or len(set(dimensions)) != len(dimensions)
        or set(dimensions) - set(DIMENSIONS) - set(LABELS)
    ):
        raise ValueError("Ongeldige beoordelingsdimensies.")
    identifiers = [piece["id"] for piece in spec["pieces"]]
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError(
            "Een luisterproef vereist verschillende melodieën met unieke namen."
        )
    if any(len(piece["systems"]) < 2 for piece in spec["pieces"]):
        raise ValueError("Geef minstens twee systemen per melodie op.")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Luistermap bestaat al. Kies een nieuwe map.")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    key, trials, cards = {}, [], []
    for index, piece in enumerate(spec["pieces"], 1):
        systems = list(piece["systems"].items())
        rng.shuffle(systems)
        key[str(index)] = {"piece": piece["id"], "systems": {}}
        levels = {system: loudness(Path(path).resolve()) for system, path in systems}
        target = common_loudness_target(levels.values())
        key[str(index)]["normalization"] = {
            "target_lufs": target,
            "method": "constant_gain",
            "inputs": levels,
        }
        for j, (system, path) in enumerate(systems):
            label = chr(65 + j)
            audio = output / f"{index:02}_{label}.wav"
            # All inputs must already use the same renderer/soundfont. Only volume
            # normalization happens here; internal dynamics remain proportional.
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(Path(path).resolve()),
                    "-af",
                    f"volume={target - levels[system]['integrated_lufs']}dB",
                    "-map_metadata",
                    "-1",
                    "-ar",
                    "44100",
                    str(audio),
                ],
                check=True,
            )
            key[str(index)]["systems"][label] = system
            trial = {
                "piece": index,
                "label": label,
                **{d: None for d in dimensions},
                "disturbing_errors": None,
                "preferred": False,
                "notes": "",
            }
            trials.append(trial)
            fields = "".join(
                f'<label>{LABELS.get(d, d)} <select data-field="{d}"><option value="">Kies</option>'
                + "".join(f"<option>{v}</option>" for v in range(1, 6))
                + "</select></label> "
                for d in dimensions
            )
            cards.append(
                f'<article data-piece="{index}" data-label="{label}"><h2>Stuk {index}, versie {label}</h2><audio controls src="{audio.name}"></audio><p>{fields}</p><label>Storende fout <select data-field="disturbing_errors"><option value="">Kies</option><option value="false">Nee</option><option value="true">Ja</option></select></label> <label><input type="checkbox" data-field="preferred"> Voorkeur bij dit stuk</label><p><textarea data-field="notes" placeholder="Toelichting"></textarea></p></article>'
            )
    write_json(
        output / "answer_key.json",
        {
            "split": spec.get("split", "development"),
            "renderer": spec.get("renderer"),
            "trials": key,
            "dimensions": dimensions,
        },
    )
    write_json(output / "ratings.json", trials)
    page = """<!doctype html><html lang="nl"><meta charset="utf-8"><title>Luisterproef harmoniser</title>
<style>body{font:17px system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#222}article{border-top:1px solid #ccc;padding:20px 0}label{display:inline-block;margin:8px}textarea{width:90%;height:60px}audio{width:90%}button{padding:12px}</style>
<h1>Luisterproef</h1><p>Beoordeel elke versie van 1 (onvoldoende) tot 5 (overtuigend). Kies maximaal één voorkeursversie per stuk. De systeemnamen staan apart in answer_key.json. Open dat bestand pas na beoordeling.</p>"""
    page += "\n".join(cards)
    page += """<button onclick="save()">Beoordeling downloaden</button><script>
function save(){const rows=[...document.querySelectorAll('article')].map(e=>{const r={piece:+e.dataset.piece,label:e.dataset.label};for(const f of e.querySelectorAll('[data-field]')){r[f.dataset.field]=f.type==='checkbox'?f.checked:f.dataset.field==='notes'?f.value:f.value===''?null:f.dataset.field==='disturbing_errors'?f.value==='true':+f.value;}return r;});const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));a.download='ratings.json';a.click();URL.revokeObjectURL(a.href);}
</script></html>"""
    (output / "listen.html").write_text(page)
    return output / "listen.html"


def summarize(key_path, ratings_path):
    key = json.loads(Path(key_path).read_text())
    dimensions = key.get("dimensions", DIMENSIONS)
    ratings = json.loads(Path(ratings_path).read_text())
    expected = {
        (int(piece), label)
        for piece, item in key["trials"].items()
        for label in item["systems"]
    }
    actual = [(r["piece"], r["label"]) for r in ratings]
    if set(actual) != expected or len(actual) != len(set(actual)):
        raise ValueError("Ontbrekende, dubbele of onbekende luisterbeoordelingen.")
    if any(
        any(r.get(d) not in (1, 2, 3, 4, 5) for d in dimensions)
        or type(r.get("disturbing_errors")) is not bool
        for r in ratings
    ):
        return {"status": "incomplete", "accepted": False}
    results = {}
    pieces = {}
    for row in ratings:
        system = key["trials"][str(row["piece"])]["systems"][row["label"]]
        result = results.setdefault(
            system, {"pieces": 0, "good": 0, "preferred": 0, "scores": []}
        )
        average = sum(row[d] for d in dimensions) / len(dimensions)
        result["pieces"] += 1
        result["good"] += int(average >= 4 and not row["disturbing_errors"])
        result["preferred"] += int(bool(row.get("preferred")))
        result["scores"].append(average)
        pieces.setdefault(row["piece"], []).append(row)
    if any(sum(bool(r.get("preferred")) for r in rows) > 1 for rows in pieces.values()):
        raise ValueError("Meerdere voorkeursversies bij hetzelfde stuk.")
    for result in results.values():
        result["quality_gate"] = result["good"] / result["pieces"] >= 0.8
        result["preference_fraction"] = result["preferred"] / result["pieces"]
        result["finetune_preference_gate"] = result["preference_fraction"] >= 2 / 3
    return {
        "status": "complete",
        "split": key["split"],
        "systems": results,
        "acceptance_eligible": key["split"] == "test"
        and len({trial["piece"] for trial in key["trials"].values()}) >= 3,
        "interpretation": "Persoonlijke luisterbeoordeling. Geen bewijs van objectieve stijlovereenkomst.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("spec", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--seed", type=int, default=0)
    summ = sub.add_parser("summarize")
    summ.add_argument("--key", type=Path, required=True)
    summ.add_argument("--ratings", type=Path, required=True)
    summ.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.command == "prepare":
        print(prepare(a.spec, a.output, a.seed))
    else:
        result = summarize(a.key, a.ratings)
        write_json(a.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
