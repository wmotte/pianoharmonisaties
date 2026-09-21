"""Reproducible section measurements from current converted scores.

Explicit boundaries can be used in draft experiments. They do not certify the
transcribed notes. Unresolved boundaries and held-out songs never train a planner.
"""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from itertools import pairwise
from pathlib import Path

from music21 import converter, expressions, stream

from .annotations import validate_splits
from .model import write_json
from .profile import identify_chord


def score_timeline(score):
    part = score.parts[0]
    meters, tempos, measures = [], [], []
    current = None
    for m in part.getElementsByClass(stream.Measure):
        offset = float(m.offset)
        if m.timeSignature:
            current = m.timeSignature
            value = [current.numerator, current.denominator]
            if not meters or meters[-1][1:] != value:
                meters.append([offset, *value])
        measures.append(
            {
                "number": m.number,
                "start": offset,
                "length": float(m.duration.quarterLength),
                "meter": [current.numerator, current.denominator],
            }
        )
        for mark in m.recurse().getElementsByClass("MetronomeMark"):
            bpm = mark.getQuarterBPM()
            if bpm is None:
                continue
            time = float(mark.getOffsetInHierarchy(part))
            row = {
                "start": time,
                "quarter_bpm": float(bpm),
                "number": float(mark.number),
                "beat_quarters": float(mark.referent.quarterLength),
            }
            if tempos and tempos[-1]["start"] == time:
                if tempos[-1]["quarter_bpm"] != row["quarter_bpm"]:
                    raise ValueError(
                        "Tegenstrijdige tempoaanduidingen op dezelfde positie."
                    )
                continue
            tempos.append(row)
    return {"meters": meters, "tempos": tempos, "measures": measures}


def explicit_sections(timeline, title, splits, length):
    spec = next((v for k, v in splits.items() if k in title), None)
    if not spec:
        return []
    starts = [t["start"] for t in timeline["tempos"]]
    labels = spec.get("labels", [])
    # Current stitched scores carry one tempo mark at every documented section.
    if len(starts) != len(labels) or not starts or starts[0] != 0:
        return []
    return [
        {"name": name, "start": a, "end": b, "boundary_source": "explicit"}
        for name, a, b in zip(labels, starts, starts[1:] + [length])
    ]


def measure_section(score, timeline, section):
    start, end = section["start"], section["end"]
    events, top, fermatas = [], [], []
    for pi, part in enumerate(score.parts):
        for element in part.recurse().notes:
            a = float(element.getOffsetInHierarchy(part))
            b = a + float(element.quarterLength)
            if b <= start or a >= end:
                continue
            for p in element.pitches:
                events.append((int(p.midi), max(start, a), min(end, b)))
            tied = element.tie and element.tie.type in ("stop", "continue")
            if pi == 0 and not tied:
                top.append(
                    (
                        a,
                        b - a,
                        max(p.midi for p in element.pitches),
                        element.volume.velocity or 70,
                    )
                )
                if any(isinstance(e, expressions.Fermata) for e in element.expressions):
                    fermatas.append(min(end, b))
    bounds = sorted(
        {start, end, *(a for _, a, _ in events), *(b for _, _, b in events)}
    )
    coverage, bass_runs, sequence = Counter(), [], []
    for a, b in pairwise(bounds):
        sounding = sorted({p for p, x, y in events if x <= a < y})
        coverage[str(len(sounding))] += b - a
        if sounding:
            bass = sounding[0]
            if (
                bass_runs
                and bass_runs[-1][0] == bass
                and abs(bass_runs[-1][2] - a) < 1e-6
            ):
                bass_runs[-1][2] = b
            else:
                bass_runs.append([bass, a, b])
        found = identify_chord(sounding)
        if found and (not sequence or tuple(sequence[-1][2:]) != found):
            sequence.append([a, b, *found])
        elif found:
            sequence[-1][1] = b
    local_measures = [m for m in timeline["measures"] if start <= m["start"] < end]
    meter = next(m[1:] for m in reversed(timeline["meters"]) if m[0] <= start)
    bpm = next(
        t["quarter_bpm"] for t in reversed(timeline["tempos"]) if t["start"] <= start
    )
    bar_length = meter[0] * 4 / meter[1]
    # Phrase proposals are distinguished from explicit section boundaries.
    candidates = sorted(
        set(
            [t for t in fermatas if t < end]
            + [a + d for a, d, _, _ in top if d >= bar_length / 2 and a + d < end]
        )
    )
    phrase_ends, cursor = [], start
    for t in candidates + [end]:
        if t == end or t - cursor >= 2 * bar_length:
            phrase_ends.append(t)
            cursor = t
    lengths = [(b - a) / bar_length for a, b in zip([start] + phrase_ends, phrase_ends)]
    rhythm_counts = Counter(
        str(round(d * 2) / 2) for _, d, _, _ in top if 0.5 <= d <= 4
    )
    return {
        **section,
        "meter": meter,
        "quarter_bpm": bpm,
        "bars": len(local_measures),
        "sounding_density": dict(coverage),
        "mean_sounding_notes": sum(int(k) * v for k, v in coverage.items())
        / max(1, end - start),
        "phrase_bars": lengths,
        "phrase_confidence": "inferred_from_duration_and_fermatas",
        "rhythm_counts": dict(rhythm_counts),
        "top_range": [
            min((p for _, _, p, _ in top), default=60),
            max((p for _, _, p, _ in top), default=84),
        ],
        "velocity_mean": statistics.mean(v for _, _, _, v in top) if top else 70,
        "harmonic_changes_per_bar": len(sequence) / max(1, len(local_measures)),
        "harmonies": sequence,
        "pedal_points": [r for r in bass_runs if r[2] - r[1] >= bar_length],
        "cadence": [s[2:] for s in sequence[-2:]],
        "motif_intervals": [int(b[2] - a[2]) for a, b in pairwise(top)],
        "fermatas": fermatas,
    }


def analyse_score(path, splits=None):
    score = converter.parse(path)
    timeline = score_timeline(score)
    length = float(score.duration.quarterLength)
    sections = explicit_sections(timeline, Path(path).stem, splits or {}, length)
    if not sections:
        sections = [
            {
                "name": "Unresolved",
                "start": 0,
                "end": length,
                "boundary_source": "unresolved",
            }
        ]
    return {
        "path": str(path),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "reviewed": False,
        "timeline": timeline,
        "sections": [measure_section(score, timeline, s) for s in sections],
    }


def build_library(directory, manifest, splits):
    sources = json.loads(Path(manifest).read_text())["sources"]
    validate_splits({s["id"]: s for s in sources})
    by_name = {Path(s["audio"]).stem: s for s in sources}
    rows, library, seen = [], [], set()
    for path in sorted(Path(directory).glob("*.musicxml")):
        source = by_name.get(path.stem)
        if not source:
            continue
        row = analyse_score(path, splits)
        row.update(source_id=source["id"], split=source["split"], group=source["group"])
        rows.append(row)
        if (
            source["split"] != "train"
            or source["compilation"]
            or source["group"] in seen
        ):
            continue
        eligible = [s for s in row["sections"] if s["boundary_source"] == "explicit"]
        if eligible:
            seen.add(source["group"])
        for s in eligible:
            library.append(
                {
                    **s,
                    "source_id": source["id"],
                    "source_sha256": row["sha256"],
                    "source_path": str(path),
                    "split": "train",
                    "reviewed": False,
                }
            )
        print(path.stem, "explicit" if eligible else "diagnostic", flush=True)
    return {
        "schema_version": 2,
        "status": "draft",
        "sources": rows,
        "section_library": library,
        "limitations": [
            "Transcripties niet muzikaal gecontroleerd.",
            "Alleen expliciet begrensde trainingsstukken sturen sectiekeuzes.",
            "Frasegrenzen zijn voorstellen, geen geverifieerde analyse.",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--splits", type=Path, default=Path("splits.json"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    write_json(
        args.output,
        build_library(args.scores, args.manifest, json.loads(args.splits.read_text())),
    )


if __name__ == "__main__":
    main()
