#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Module voor audio- en stiltedetectie, snijpuntcalculaties en het splitsen van mp3-bestanden en ruwe MIDI.
Wordt gebruikt om voorspel, koraal en naspel los te knippen, of verzamel-mp3's in losse tracks op te delen.
"""
import argparse
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import librosa
import numpy as np
import pretty_midi


def detect_silence_gaps(
    audio_path: Path,
    min_silence: float = 1.0,
    top_db: float = 30.0,
    sr: int = 22050,
) -> Tuple[List[Tuple[float, float, float]], float]:
    """
    Detecteert stiltes in een audiobestand.
    Geeft een lijst terug van (gap_start, gap_end, gap_dur) in seconden, plus de totale tijdsduur.
    """
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    total_dur = float(len(y) / sr)
    if total_dur == 0:
        return [], 0.0

    intervals = librosa.effects.split(y, top_db=top_db, frame_length=2048, hop_length=512)
    gaps: List[Tuple[float, float, float]] = []

    # Stilte vóór het eerste actieve blok (als > min_silence)
    if len(intervals) > 0:
        first_onset = intervals[0][0] / sr
        if first_onset >= min_silence:
            gaps.append((0.0, float(first_onset), float(first_onset)))

    for i in range(len(intervals) - 1):
        gap_start = float(intervals[i][1] / sr)
        gap_end = float(intervals[i + 1][0] / sr)
        dur = gap_end - gap_start
        if dur >= min_silence:
            gaps.append((gap_start, gap_end, float(dur)))

    # Stilte na het laatste actieve blok
    if len(intervals) > 0:
        last_offset = float(intervals[-1][1] / sr)
        if total_dur - last_offset >= min_silence:
            gaps.append((last_offset, total_dur, total_dur - last_offset))

    return gaps, total_dur


def compute_cut_points(
    gaps: List[Tuple[float, float, float]],
    total_dur: float,
    min_section_dur: float = 10.0,
) -> List[Tuple[float, float]]:
    """
    Berekent sectiegrenzen (start_t, end_t) op basis van de stiltes.
    Snijdt precies in het midden van elke stilte.
    Negeert sneden die fragmenten korter dan min_section_dur zouden opleveren.
    """
    # Filter gaps die te dicht bij het absolute begin of einde liggen
    internal_gaps = [g for g in gaps if g[0] > 1.0 and g[1] < total_dur - 1.0]

    raw_cuts = [(g[0] + g[1]) / 2.0 for g in internal_gaps]

    # Filter cuts die te dicht op elkaar liggen
    cuts: List[float] = []
    last_t = 0.0
    for c in raw_cuts:
        if c - last_t >= min_section_dur and (total_dur - c) >= min_section_dur:
            cuts.append(round(c, 3))
            last_t = c

    edges = [0.0] + cuts + [round(total_dur, 3)]
    sections = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    return sections


def standard_section_labels(n_sections: int) -> List[str]:
    """Standaardnamen voor secties in klassieke pianokoralen."""
    if n_sections == 1:
        return ["Volledig"]
    if n_sections == 2:
        return ["Voorspel", "Koraal"]
    if n_sections == 3:
        return ["Voorspel", "Koraal", "Naspel"]
    if n_sections == 4:
        return ["Voorspel", "Koraal 1", "Tussenspel", "Koraal 2"]
    return [f"Deel {i+1}" for i in range(n_sections)]


def split_audio_file(
    input_mp3: Path,
    sections: List[Tuple[float, float]],
    output_dir: Path,
    labels: Optional[List[str]] = None,
) -> List[Path]:
    """
    Knipt een MP3-bestand in losse mp3-bestanden via ffmpeg.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if labels is None or len(labels) != len(sections):
        labels = standard_section_labels(len(sections))

    out_paths: List[Path] = []
    for idx, ((start_t, end_t), label) in enumerate(zip(sections, labels)):
        safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
        out_name = f"{idx+1:02d}_{safe_label}.mp3"
        out_path = output_dir / out_name

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_t:.3f}",
            "-to", f"{end_t:.3f}",
            "-i", str(input_mp3),
            "-q:a", "0",
            "-vn",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out_paths.append(out_path)

    return out_paths


def slice_raw_midi(
    raw_midi_path: Path,
    sections: List[Tuple[float, float]],
    output_dir: Path,
    labels: Optional[List[str]] = None,
) -> List[Path]:
    """
    Knipt een bestaand PrettyMIDI-bestand in partities voor elke sectie.
    Verschuift alle tijden met -start_t zodat elke partitie op t=0 begint.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pm = pretty_midi.PrettyMIDI(str(raw_midi_path))
    if labels is None or len(labels) != len(sections):
        labels = standard_section_labels(len(sections))

    out_paths: List[Path] = []
    for idx, ((start_t, end_t), label) in enumerate(zip(sections, labels)):
        safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
        out_path = output_dir / f"{idx+1:02d}_{safe_label}.mid"

        sub_pm = pretty_midi.PrettyMIDI(resolution=pm.resolution)

        # Kopieer instrumenten en noten binnen [start_t, end_t)
        for inst in pm.instruments:
            sub_inst = pretty_midi.Instrument(program=inst.program, is_drum=inst.is_drum, name=inst.name)
            for n in inst.notes:
                if start_t <= n.start < end_t:
                    shifted_start = max(0.0, n.start - start_t)
                    shifted_end = max(shifted_start + 0.01, min(end_t, n.end) - start_t)
                    sub_inst.notes.append(
                        pretty_midi.Note(
                            velocity=n.velocity,
                            pitch=n.pitch,
                            start=shifted_start,
                            end=shifted_end,
                        )
                    )
            # Pedaal / CC control changes
            for cc in inst.control_changes:
                if start_t <= cc.time < end_t:
                    sub_inst.control_changes.append(
                        pretty_midi.ControlChange(
                            number=cc.number,
                            value=cc.value,
                            time=cc.time - start_t,
                        )
                    )
            # Pitch bends
            for pb in inst.pitch_bends:
                if start_t <= pb.time < end_t:
                    sub_inst.pitch_bends.append(
                        pretty_midi.PitchBend(
                            pitch=pb.pitch,
                            time=pb.time - start_t,
                        )
                    )
            sub_pm.instruments.append(sub_inst)

        sub_pm.write(str(out_path))
        out_paths.append(out_path)

    return out_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mp3", type=Path, help="Te analyseren mp3-bestand")
    parser.add_argument("--min-silence", type=float, default=1.0, help="Minimale stilte-lengte in sec (standaard: 1.0)")
    parser.add_argument("--top-db", type=float, default=30.0, help="Stilte-drempel in dB onder piek (standaard: 30)")
    parser.add_argument("--min-dur", type=float, default=10.0, help="Minimale sectieduur in sec (standaard: 10)")
    parser.add_argument("--split", action="store_true", help="Fysiek opsplitsen naar mp3_delen/<stem>/")
    args = parser.parse_args()

    gaps, dur = detect_silence_gaps(args.mp3, min_silence=args.min_silence, top_db=args.top_db)
    sections = compute_cut_points(gaps, dur, min_section_dur=args.min_dur)
    labels = standard_section_labels(len(sections))

    print(f"Bestand: {args.mp3.name}")
    print(f"Totale duur: {dur:.2f}s ({int(dur // 60)}m {int(dur % 60):02d}s)")
    print(f"Aantal stiltes >= {args.min_silence}s: {len(gaps)}")
    for s, e, d in gaps:
        print(f"   Stilte: {s:6.2f}s - {e:6.2f}s (duur: {d:4.2f}s)")

    print(f"\nGedetecteerde secties ({len(sections)}):")
    for (st, et), lbl in zip(sections, labels):
        print(f"   [{lbl:12s}] {st:6.2f}s - {et:6.2f}s (duur: {et-st:6.2f}s)")

    if args.split:
        out_dir = args.mp3.parent.parent / "mp3_delen" / args.mp3.stem
        out_paths = split_audio_file(args.mp3, sections, out_dir, labels)
        print(f"\nOpgesplitst naar {out_dir}:")
        for p in out_paths:
            print(f"   -> {p.name}")


if __name__ == "__main__":
    main()
