"""Private corpus inventory, duplicate candidates and reviewable source segments."""

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pretty_midi

from .model import write_json


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tune_name(stem):
    s = unicodedata.normalize("NFKD", stem).lower()
    psalm = re.search(r"psalm\s+(\d+)", s)
    if psalm:
        return "psalm_" + psalm[1]
    s = re.sub(r"^\d{4}-\d\d-\d\d\s*-\s*", "", s)
    s = re.sub(r"\[[^\]]+\]", "", s).split("｜")[0].split("|")[0]
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def is_compilation(stem, duration):
    return duration > 900 or bool(
        re.search(
            r"\d+ Psalmen|mooiste|Bekende christelijke|Beautiful Christmas|Pianomuziek voor",
            stem,
            re.IGNORECASE,
        )
    )


def fingerprints(path):
    """Four-second acoustic fingerprints, independent of MP3 metadata/encoding.

    These only propose overlaps. They do not certify duplicate performances.
    """
    from scipy.signal import stft

    pcm = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "4000",
            "-f",
            "f32le",
            "-",
        ]
    )
    x = np.frombuffer(pcm, dtype="<f4")
    f, t, z = stft(x, fs=4000, nperseg=2048, noverlap=1024, boundary=None)
    power = abs(z) ** 2
    chroma = np.zeros((12, len(t)))
    valid = f > 40
    pitches = np.rint(69 + 12 * np.log2(f[valid] / 440)).astype(int)
    for pc in range(12):
        chroma[pc] = power[valid][pitches % 12 == pc].sum(axis=0)
    rows = []
    for start in np.arange(0, max(0, len(x) / 4000 - 4), 4):
        mask = (t >= start) & (t < start + 4)
        v = np.sqrt(chroma[:, mask].mean(axis=1))
        norm = np.linalg.norm(v)
        rows.append(v / norm if norm > 1e-5 else np.zeros(12))
    return np.asarray(rows, dtype=np.float32)


def overlap_candidates(items, vectors):
    """Require ordered runs, not isolated matching chords, for candidate overlaps."""
    from scipy.spatial import cKDTree

    candidates = []
    for ai, a in enumerate(items):
        va = vectors[a["id"]]
        if len(va) < 8:
            continue
        tree = cKDTree(va)
        for b in items[ai + 1 :]:
            vb = vectors[b["id"]]
            if len(vb) < 8:
                continue
            distances, indexes = tree.query(vb, k=min(4, len(va)))
            runs = defaultdict(list)
            for j in range(len(vb)):
                for dist, i in zip(
                    np.atleast_1d(distances[j]), np.atleast_1d(indexes[j])
                ):
                    if dist < 0.12 and np.linalg.norm(vb[j]) > 0.5:
                        runs[int(i) - j].append(j)
            best = None
            for offset, js in runs.items():
                js = sorted(set(js))
                seq = []
                for j in js:
                    if seq and j - seq[-1] > 2:
                        seq = []
                    seq.append(j)
                    if len(seq) >= 8 and (best is None or len(seq) > best[0]):
                        best = (len(seq), offset, seq[0], seq[-1])
            if best:
                count, off, start, end = best
                candidates.append(
                    {
                        "a": a["id"],
                        "b": b["id"],
                        "a_seconds": [(start + off) * 4, (end + off + 1) * 4],
                        "b_seconds": [start * 4, (end + 1) * 4],
                        "matching_windows": count,
                        "status": "needs_listening",
                    }
                )
    return candidates


def assign_splits(items, overlaps):
    # Compilations are excluded until someone identifies the individual tunes.
    eligible = [i for i in items if not i["compilation"]]
    parents = {i["tune"]: i["tune"] for i in eligible}

    def root(x):
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    by_id = {i["id"]: i for i in eligible}
    exact = {}
    for item in eligible:
        for field in ("audio_sha256", "midi_sha256"):
            if item.get(field):
                key = (field, item[field])
                if key in exact:
                    parents[root(item["tune"])] = root(exact[key])
                else:
                    exact[key] = item["tune"]
    for pair in overlaps:
        if pair["a"] in by_id and pair["b"] in by_id:
            a, b = (by_id[pair[x]]["tune"] for x in ("a", "b"))
            parents[root(b)] = root(a)
    groups = defaultdict(list)
    for item in eligible:
        groups[root(item["tune"])].append(item)
    ordered = sorted(
        groups, key=lambda g: hashlib.sha256(("koele-v1:" + g).encode()).hexdigest()
    )
    # Existing public examples are development sources, never final tests.
    development = {"psalm_85", "psalm_37", "de_lofzang_van_maria", "u_zij_de_glorie"}
    psalms = [
        g
        for g in ordered
        if any(i["tune"].startswith("psalm_") for i in groups[g])
        and not any(i["tune"] in development for i in groups[g])
    ]
    test = set(psalms[:3])
    for g in ordered:
        if len(test) >= max(3, round(len(groups) * 0.15)):
            break
        if not any(i["tune"] in development for i in groups[g]):
            test.add(g)
    validation = set()
    for g in ordered:
        if g not in test and not any(i["tune"] in development for i in groups[g]):
            validation.add(g)
        if len(validation) >= max(1, round(len(groups) * 0.15)):
            break
    for g, rows in groups.items():
        for i in rows:
            i["group"] = g
            i["split"] = (
                "test" if g in test else "validation" if g in validation else "train"
            )
    for i in items:
        if i["compilation"]:
            i["split"] = "excluded"
            i["group"] = "unresolved_compilation"


def inventory(root, output, acoustic=True):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for audio in sorted((root / "mp3").glob("*.mp3")):
        duration = float(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(audio),
                ]
            )
        )
        # glob interprets video-id brackets. Match filenames literally instead.
        raw = [
            p
            for p in (root / "midi_raw").glob("*.mid")
            if p.name.startswith(audio.stem + ".")
        ]
        midi = next(
            (p for p in raw if p.name.endswith(".transkun.mid")),
            raw[0] if raw else None,
        )
        pm = pretty_midi.PrettyMIDI(str(midi)) if midi else None
        notes = [n for i in pm.instruments for n in i.notes] if pm else []
        rows.append(
            {
                "id": digest(audio)[:16],
                "audio": str(audio),
                "audio_sha256": digest(audio),
                "midi": str(midi) if midi else None,
                "midi_sha256": digest(midi) if midi else None,
                "duration": duration,
                "note_count": len(notes),
                "tune": tune_name(audio.stem),
                "compilation": is_compilation(audio.stem, duration),
                "review": "pending",
                "cc64_count": sum(
                    c.number == 64 for i in pm.instruments for c in i.control_changes
                )
                if pm
                else 0,
            }
        )
    vectors = {}
    if acoustic:
        cache = output / "fingerprints"
        cache.mkdir(exist_ok=True)

        def get(row):
            p = cache / (row["id"] + ".npy")
            if p.exists():
                return row["id"], np.load(p, allow_pickle=False)
            v = fingerprints(row["audio"])
            np.save(p, v, allow_pickle=False)
            return row["id"], v

        with ThreadPoolExecutor(max_workers=2) as pool:
            vectors = dict(pool.map(get, rows))
    overlaps = overlap_candidates(rows, vectors) if acoustic else []
    assign_splits(rows, overlaps)
    # Exact duplicates may exist even when the acoustic pass was disabled.
    hashes = defaultdict(list)
    for row in rows:
        hashes[row["audio_sha256"]].append(row["id"])
    duplicate_hashes = [v for v in hashes.values() if len(v) > 1]
    manifest = {
        "schema_version": 1,
        "status": "unreviewed",
        "sources": rows,
        "overlap_candidates": overlaps,
        "exact_duplicates": duplicate_hashes,
        "summary": {
            "files": len(rows),
            "hours": sum(i["duration"] for i in rows) / 3600,
            "notes": sum(i["note_count"] for i in rows),
            "unique_hours": None,
            "split_counts": dict(Counter(i["split"] for i in rows)),
            "unique_hours_status": "requires segment and duplicate review",
        },
    }
    write_json(output / "manifest.json", manifest)
    # Never overwrite human annotations on rerun.
    annotation_path = output / "annotations.json"
    if not annotation_path.exists():
        write_json(
            annotation_path,
            {
                "schema_version": 1,
                "instructions": "Vul segmenten in met start/end in seconden, tune, key, meter, sections, phrases en reviewed=true. Identificeer eerst compilaties. Geen hoogste-nootheuristiek als gecertificeerde melodie.",
                "segments": [
                    {
                        "source_id": i["id"],
                        "start": 0,
                        "end": i["duration"],
                        "tune": i["tune"],
                        "reviewed": False,
                        "exclude": i["compilation"],
                        "key": None,
                        "meter": None,
                        "sections": [],
                        "phrases": [],
                        "melody_midi": None,
                    }
                    for i in rows
                ],
            },
        )
    lines = [
        "# Corpusinventaris",
        "",
        f"{len(rows)} opnamen, {manifest['summary']['hours']:.2f} uur, {manifest['summary']['notes']} ruwe noten.",
        "",
        "Unieke speelduur: nog niet vastgesteld. Akoestische overeenkomsten zijn luisterkandidaten.",
        f"{len(overlaps)} overlapkandidaten. Compilaties blijven uitgesloten van training totdat hun melodieën zijn geïdentificeerd.",
        "",
        "| Groep | Bestanden |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {v} |" for k, v in manifest["summary"]["split_counts"].items()]
    (output / "inventory.md").write_text("\n".join(lines) + "\n")
    return manifest


def clips(manifest_path, output):
    manifest = json.loads(Path(manifest_path).read_text())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    examples = ("psalm_85", "psalm_37", "de_lofzang_van_maria", "u_zij_de_glorie")
    selected = [
        next(
            (s for s in manifest["sources"] if s["tune"] == t and not s["compilation"]),
            None,
        )
        for t in examples
    ]
    review = []
    for row in filter(None, selected):
        for index, fraction in enumerate((0.12, 0.5, 0.83)):
            start = max(0, min(row["duration"] - 30, row["duration"] * fraction))
            name = row["tune"] + f"_{index + 1}"
            audio_out, midi_out = output / (name + ".wav"), output / (name + ".old.mid")
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(start),
                    "-i",
                    row["audio"],
                    "-t",
                    "30",
                    "-ar",
                    "22050",
                    str(audio_out),
                ],
                check=True,
            )
            crop_midi(row["midi"], midi_out, start, start + 30)
            review.append(
                {
                    "id": name,
                    "source_id": row["id"],
                    "start": start,
                    "end": start + 30,
                    "audio": str(audio_out.resolve()),
                    "old_midi": str(midi_out.resolve()),
                    "new_midi": None,
                    "melody_errors_old": None,
                    "melody_errors_new": None,
                    "bass_errors_old": None,
                    "bass_errors_new": None,
                    "notes": "",
                }
            )
    review_path = output / "transcription_review.json"
    if review_path.exists():
        previous = {row["id"]: row for row in json.loads(review_path.read_text())}
        review = [dict(row, **previous.get(row["id"], {})) for row in review]
    write_json(review_path, review)
    return review


def crop_midi(source, target, start, end):
    src = pretty_midi.PrettyMIDI(str(source))
    out = pretty_midi.PrettyMIDI()
    for instrument in src.instruments:
        part = pretty_midi.Instrument(
            instrument.program, instrument.is_drum, instrument.name
        )
        for n in instrument.notes:
            if n.end > start and n.start < end:
                part.notes.append(
                    pretty_midi.Note(
                        n.velocity,
                        n.pitch,
                        max(0, n.start - start),
                        min(end, n.end) - start,
                    )
                )
        state = {}
        for c in sorted(instrument.control_changes, key=lambda c: c.time):
            if c.time < start:
                state[c.number] = c.value
            elif c.time < end:
                part.control_changes.append(
                    pretty_midi.ControlChange(c.number, c.value, c.time - start)
                )
        part.control_changes.extend(
            pretty_midi.ControlChange(k, v, 0) for k, v in state.items()
        )
        part.control_changes.append(pretty_midi.ControlChange(64, 0, end - start))
        out.instruments.append(part)
    out.write(str(target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--root", type=Path, default=Path("private_data"))
    inv.add_argument(
        "--output", type=Path, default=Path("private_data/harmonizer/corpus")
    )
    inv.add_argument("--skip-acoustic", action="store_true")
    cl = sub.add_parser("clips")
    cl.add_argument(
        "--manifest",
        type=Path,
        default=Path("private_data/harmonizer/corpus/manifest.json"),
    )
    cl.add_argument(
        "--output", type=Path, default=Path("private_data/harmonizer/review")
    )
    args = parser.parse_args()
    if args.command == "inventory":
        print(
            json.dumps(
                inventory(args.root, args.output, not args.skip_acoustic)["summary"],
                indent=2,
            )
        )
    else:
        print(
            f"{len(clips(args.manifest, args.output))} vergelijkingsfragmenten gemaakt."
        )


if __name__ == "__main__":
    main()
