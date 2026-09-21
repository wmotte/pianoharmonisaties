"""Adversarial diagnostics. Structural measurements are not listening ratings."""

import argparse
import json
from itertools import pairwise
from pathlib import Path

import mido

from .engine import Arrangement, Harmony
from .model import MODES, Event, satb_coverage, write_json
from .timing import tempo_map as structural_tempo_map


def read_arrangement(path, tonic=0, mode="major"):
    raw = json.loads(Path(path).read_text())
    raw["notes"] = [Event(**n) for n in raw["notes"]]
    raw["harmony"] = [Harmony(**h) for h in raw["harmony"]]
    raw.setdefault("tonic", tonic)
    raw.setdefault("mode", mode)
    return Arrangement(**raw)


def midi_metrics(path):
    midi = mido.MidiFile(path)
    tempos, names, keys, changes = [], [], [], []
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type == "set_tempo":
                tempos.append((tick / midi.ticks_per_beat, message.tempo))
            elif message.type == "track_name":
                names.append(message.name)
            elif message.type == "key_signature":
                keys.append(message.key)
            elif message.type == "time_signature":
                changes.append(
                    (tick / midi.ticks_per_beat, message.numerator, message.denominator)
                )
    tempos.sort()
    return {
        "duration_seconds": midi.length,
        "track_names": names,
        "key_signatures": keys,
        "tempo_events": len(tempos),
        "redundant_tempo_events": sum(a[1] == b[1] for a, b in pairwise(tempos)),
        "meters": changes,
        "tempo_map": tempos,
    }


def seconds_at(beat, tempos):
    cursor, seconds, tempo = 0.0, 0.0, 500000
    for time, value in tempos:
        if time >= beat:
            break
        seconds += (time - cursor) * tempo / 1e6
        cursor, tempo = time, value
    return seconds + (beat - cursor) * tempo / 1e6


def musical_audit(arrangement, profile, performance_path=None):
    a = arrangement
    metrics = midi_metrics(performance_path) if performance_path else None
    tempo_map = (
        metrics["tempo_map"]
        if metrics
        else [(t, mido.bpm2tempo(bpm)) for t, bpm in structural_tempo_map(a)]
    )
    sections = []
    issues = []
    for section in a.sections:
        hs = [h for h in a.harmony if section["start"] <= h.start < section["end"]]
        notes = [n for n in a.notes if section["start"] <= n.start < section["end"]]
        terminal = max(
            (n.start for n in notes if n.role in ("melody", "motif")),
            default=section["start"],
        )
        sounding = [
            n.pitch
            for n in notes
            if n.start <= terminal + 1e-6 and n.end > terminal + 1e-6
        ]
        row = dict(
            section,
            beats=section["end"] - section["start"],
            seconds=seconds_at(section["end"], tempo_map)
            - seconds_at(section["start"], tempo_map),
            phrase_ends=[
                p - section["start"]
                for p in a.phrases
                if section["start"] < p <= section["end"]
            ],
            harmony_blocks=len(hs),
            bass_only_blocks=sum(not h.inner for h in hs),
            terminal_sounding_pitches=sorted(sounding),
        )
        sections.append(row)
        row["satb"] = satb_coverage(a.notes, section["start"], section["end"])
        if section["name"] == "Harmonisatie" and not row["satb"]["valid"]:
            issues.append(
                {
                    "code": "not_four_part",
                    "section": "Harmonisatie",
                    "detail": "Bas, tenor, alt en sopraan zijn niet gedurende iedere melodienoot afzonderlijk aanwezig.",
                }
            )
        if section["name"] == "Naspel" and sounding:
            tonic_triad = {(a.tonic + MODES[a.mode][i]) % 12 for i in (0, 2, 4)}
            if min(sounding) % 12 != a.tonic:
                issues.append(
                    {
                        "code": "postlude_inversion",
                        "section": "Naspel",
                        "detail": "Het naspel eindigt niet met de tonica in de bas.",
                    }
                )
            if not tonic_triad <= {p % 12 for p in sounding}:
                issues.append(
                    {
                        "code": "incomplete_postlude_triad",
                        "section": "Naspel",
                        "detail": "De klinkende slotzetting bevat niet de volledige tonische drieklank.",
                    }
                )
        if row["bass_only_blocks"] > max(1, len(hs) * 0.15):
            issues.append(
                {
                    "code": "thin_voicing",
                    "section": section["name"],
                    "detail": f"{row['bass_only_blocks']}/{len(hs)} harmonieblokken hebben geen binnenstem.",
                }
            )
        if section["name"] == "Harmonisatie":
            triad = {(a.tonic + MODES[a.mode][i]) % 12 for i in (0, 2, 4)}
            ending = [n for n in notes if n.role == "melody"]
            if ending and max(ending, key=lambda n: n.start).pitch % 12 not in triad:
                issues.append(
                    {
                        "code": "melody_terminal_nontriad",
                        "section": "Harmonisatie",
                        "detail": "De vaste melodie eindigt buiten de tonische drieklank. Controleer de melodie-extractie en de gewenste slotwerking. Niet automatisch gewijzigd.",
                    }
                )
    intro = next((s for s in sections if s["name"] == "Voorspel"), None)
    if intro and intro["seconds"] < 25:
        issues.append(
            {
                "code": "short_introduction",
                "section": "Voorspel",
                "detail": "Voorspel korter dan 25 seconden. Signaal voor de gewenste uitgebreide pianobewerking, geen universele muzieknorm.",
            }
        )
    if metrics and metrics["redundant_tempo_events"]:
        issues.append(
            {
                "code": "repeated_tempo",
                "detail": f"{metrics['redundant_tempo_events']} opeenvolgende identieke tempo-events.",
            }
        )
    if metrics and not metrics["key_signatures"]:
        issues.append(
            {
                "code": "missing_key_signature",
                "detail": "MIDI bevat geen toonsoortmetadata.",
            }
        )
    reviewed = sum(bool(s.get("reviewed")) for s in profile.get("sources", []))
    if not reviewed:
        issues.append(
            {
                "code": "unreviewed_style_corpus",
                "detail": "Geen gecontroleerde stijlvoorbeelden. Stilistische overtuigingskracht is niet aangetoond.",
            }
        )
    return {
        "status": "requires_musical_review",
        "method": "symbolic and file inspection; no claimed listening score",
        "sections": sections,
        "midi": metrics,
        "reviewed_sources": reviewed,
        "issues": issues,
        "listening_acceptance": "not_established",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = json.loads((a.run / "report.json").read_text())
    profile_path = a.run / "profile.json"
    profile = (
        json.loads(profile_path.read_text())
        if profile_path.exists()
        else json.loads(Path("private_data/harmonizer/profile.json").read_text())
    )
    melody = json.loads((a.run / "input.melody.json").read_text())
    candidates = {}
    for c in report["candidates"]:
        arr = read_arrangement(
            a.run / "candidates" / (c["id"] + ".json"), melody["tonic"], melody["mode"]
        )
        candidates[c["id"]] = musical_audit(arr, profile, a.run / c["performance_midi"])
    write_json(a.output, {"selected": report["selected"], "candidates": candidates})
    print(a.output)


if __name__ == "__main__":
    main()
