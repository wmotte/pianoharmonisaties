"""Local audio pages for transcription and overlap review; no inferred truth labels."""

import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pretty_midi
from scipy.optimize import linear_sum_assignment

from .midi import render
from .model import write_json


def agreement(old, new):
    a = [
        n
        for i in pretty_midi.PrettyMIDI(str(old)).instruments
        for n in i.notes
        if 0.5 < n.start < 29.5
    ]
    b = [
        n
        for i in pretty_midi.PrettyMIDI(str(new)).instruments
        for n in i.notes
        if 0.5 < n.start < 29.5
    ]
    matches = 0
    for pitch in range(21, 109):
        aa, bb = (
            [n.start for n in a if n.pitch == pitch],
            [n.start for n in b if n.pitch == pitch],
        )
        if aa and bb:
            distances = abs(np.array(aa)[:, None] - np.array(bb)[None, :])
            # Penalize ineligible matches before minimizing total distance.
            costs = np.where(distances <= 0.05, distances, 1000)
            rows, cols = linear_sum_assignment(costs)
            matches += int((distances[rows, cols] <= 0.05).sum())
    return {
        "old_notes": len(a),
        "new_notes": len(b),
        "matched_onsets_50ms": matches,
        "agreement_f1": 2 * matches / max(1, len(a) + len(b)),
        "interpretation": "agreement, not transcription accuracy",
    }


def page(title, body):
    return f'<!doctype html><html lang="nl"><meta charset="utf-8"><title>{html.escape(title)}</title><style>body{{font:17px system-ui;max-width:1000px;margin:40px auto;padding:20px}}article{{border-top:1px solid #ccc;padding:15px 0}}audio{{width:90%}}code{{word-break:break-all}}</style><h1>{html.escape(title)}</h1>{body}</html>'


def transcription_review(directory, soundfont):
    directory = Path(directory)
    path = directory / "transcription_review.json"
    rows = json.loads(path.read_text())
    body = "<p>Vergelijk de bronopname met beide transcripties. Gelijke transcripties zijn niet automatisch correct. Vul gevonden melodie- en basfouten in transcription_review.json in. De MIDI-links kun je openen in MuseScore.</p>"
    for row in rows:
        new = directory / "new" / (row["id"] + ".transkun.mid")
        if not new.exists():
            raise ValueError(f"Nieuwe transcriptie ontbreekt: {new}")
        row["new_midi"] = str(new.resolve())
        row["agreement"] = agreement(row["old_midi"], new)
        body += f"<article><h2>{html.escape(row['id'])}</h2>"
        for name, source in (
            ("Bron", Path(row["audio"])),
            ("Oud", Path(row["old_midi"])),
            ("Nieuw", new),
        ):
            if name != "Bron":
                wav = directory / (
                    row["id"] + (".old.wav" if name == "Oud" else ".new.wav")
                )
                render(source, wav, soundfont)
            else:
                wav = source
            url = quote(os.path.relpath(wav, directory))
            body += f'<p>{name}</p><audio controls src="{url}"></audio>'
            if name != "Bron":
                body += f'<p><a href="{quote(os.path.relpath(source, directory))}">MIDI {name.lower()}</a></p>'
        body += f"<p>Overeenkomst in aanslagen: {row['agreement']['agreement_f1']:.1%}. Dit is geen nauwkeurigheidsmeting.</p></article>"
    write_json(path, rows)
    (directory / "transcripties.html").write_text(page("Transcriptiecontrole", body))
    return rows


def overlap_review(manifest_path, output):
    manifest = json.loads(Path(manifest_path).read_text())
    sources = {s["id"]: s for s in manifest["sources"]}
    output = Path(output)
    body = "<p>Luister of beide fragmenten dezelfde uitvoering bevatten. De tijdvakken zijn voorstellen op basis van chroma. Bevestig of verwerp ze in manifest.json. Unieke speelduur wordt pas na segmentannotatie vastgesteld.</p>"
    for pair in manifest["overlap_candidates"]:
        body += "<article>"
        for side in ("a", "b"):
            src = sources[pair[side]]
            start, end = pair[side + "_seconds"]
            url = (
                quote(os.path.relpath(src["audio"], output.parent))
                + f"#t={start},{end}"
            )
            body += f'<p>{html.escape(Path(src["audio"]).name)}: {start}–{end} s</p><audio controls preload="none" src="{url}"></audio>'
        body += "</article>"
    output.write_text(page("Mogelijke opname-overlap", body))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--directory", type=Path, default=Path("private_data/harmonizer/review")
    )
    p.add_argument("--soundfont", type=Path, required=True)
    p.add_argument(
        "--manifest",
        type=Path,
        default=Path("private_data/harmonizer/corpus/manifest.json"),
    )
    a = p.parse_args()
    transcription_review(a.directory, a.soundfont)
    overlap_review(a.manifest, a.directory / "overlap.html")
    print(a.directory / "transcripties.html")


if __name__ == "__main__":
    main()
