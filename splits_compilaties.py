#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Script voor het automatisch detecteren en losknippen van verzamel-mp3's (compilaties)
zoals '8 Psalmen op Piano', 'De mooiste kerstliederen', etc.

Zoekt lange stiltes (standaard >= 3.0s) tussen afzonderlijke liederen en knipt
deze op in zelfstandige mp3's in de mp3/-map (of een doelmap naar keuze).
"""
import argparse
import re
from pathlib import Path

from audio_segmentatie import compute_cut_points, detect_silence_gaps, split_audio_file


def parse_video_id(filename: str) -> str:
    """Haalt [videoId] op uit de bestandsnaam indien aanwezig."""
    m = re.search(r"\[([a-zA-Z0-9_-]{11})\]", filename)
    return m.group(1) if m else ""


def parse_date_prefix(filename: str) -> str:
    """Haalt YYYY-MM-DD op uit de bestandsnaam indien aanwezig."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*-\s*", filename)
    return m.group(1) if m else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mp3", type=Path, help="Het te splitsen compilatie-mp3 bestand")
    parser.add_argument("--min-silence", type=float, default=3.0, help="Minimale stilte tussen liederen in sec (standaard: 3.0)")
    parser.add_argument("--top-db", type=float, default=32.0, help="Stilte-drempel in dB onder piek (standaard: 32)")
    parser.add_argument("--min-dur", type=float, default=30.0, help="Minimale duur per lied in sec (standaard: 30)")
    parser.add_argument("--out-dir", type=Path, default=None, help="Doelmap voor losse mp3's (standaard: mp3/)")
    parser.add_argument("--prefix", type=str, default=None, help="Titel-prefix voor de losse bestanden")
    parser.add_argument("--split", action="store_true", help="Voer de splitsing daadwerkelijk uit (zonder vlag alleen inspectie)")
    args = parser.parse_args()

    mp3_path = args.mp3.resolve()
    if not mp3_path.exists():
        parser.error(f"Bestand niet gevonden: {mp3_path}")

    out_dir = (args.out_dir or mp3_path.parent).resolve()

    gaps, dur = detect_silence_gaps(mp3_path, min_silence=args.min_silence, top_db=args.top_db)
    sections = compute_cut_points(gaps, dur, min_section_dur=args.min_dur)

    date_prefix = parse_date_prefix(mp3_path.name)
    video_id = parse_video_id(mp3_path.name)
    base_title = args.prefix
    if not base_title:
        t = mp3_path.stem
        if date_prefix:
            t = t[len(date_prefix):].lstrip(" -")
        if video_id:
            t = t.replace(f"[{video_id}]", "").strip()
        t = t.split("｜")[0].split("|")[0].strip()
        base_title = t

    labels = [f"{base_title} - Deel {i+1:02d}" for i in range(len(sections))]

    print(f"=== Compilatie-analyse: {mp3_path.name} ===")
    print(f"Totale tijdsduur: {dur/60:.1f} minuten ({dur:.1f}s)")
    print(f"Aantal lange stiltes (>= {args.min_silence}s): {len(gaps)}")
    print(f"Aantal gedetecteerde liederen/tracks: {len(sections)}\n")

    for i, ((st, et), lbl) in enumerate(zip(sections, labels)):
        s_min, s_sec = divmod(st, 60)
        e_min, e_sec = divmod(et, 60)
        d_min, d_sec = divmod(et - st, 60)
        print(f"Track {i+1:02d}: {lbl}")
        print(f"   Tijd: {int(s_min):02d}:{int(s_sec):02d} - {int(e_min):02d}:{int(e_sec):02d} (lengte: {int(d_min):02d}:{int(d_sec):02d})")

    if not args.split:
        print("\n[Tip] Draai met --split om deze tracks daadwerkelijk los te knippen:")
        print(f"   .venv/bin/python splits_compilaties.py \"{mp3_path}\" --split")
        return

    print(f"\nBezig met splitsen naar {out_dir}...")
    filenames = []
    for i, ((st, et), lbl) in enumerate(zip(sections, labels)):
        date_part = f"{date_prefix} - " if date_prefix else ""
        id_part = f" [{video_id}_{i+1:02d}]" if video_id else ""
        clean_name = f"{date_part}{lbl}{id_part}.mp3"
        filenames.append(clean_name)

    # Voer splitsing uit via audio_segmentatie
    out_dir.mkdir(parents=True, exist_ok=True)
    for (st, et), fname in zip(sections, filenames):
        dest = out_dir / fname
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{st:.3f}",
            "-to", f"{et:.3f}",
            "-i", str(mp3_path),
            "-q:a", "0",
            "-vn",
            str(dest)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"   -> Aangemaakt: {dest.name}")

    print(f"\nKlaar! {len(sections)} tracks geëxporteerd.")


if __name__ == "__main__":
    main()
