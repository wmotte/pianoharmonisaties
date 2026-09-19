#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Module voor het naadloos samenvoegen ("vastplakken") van afzonderlijk geconverteerde
muzieksecties (zoals voorspel, koraal en naspel) tot één complete MusicXML-partituur en MIDI.
"""
import copy
from pathlib import Path
from typing import Any, Dict, List

import music21 as m21
import pretty_midi


def time_signature_string(m: int, grid: int = 2) -> str:
    """Geeft de maatsoortstring terug: m=6 -> 3/2 (koraal), anders n/4."""
    return "3/2" if m == 6 else f"{m}/4"


def stitch_scores(
    sections_info: List[Dict[str, Any]],
    full_title: str,
    composer: str = "Gerrit Koele (automatische transcriptie)",
) -> m21.stream.Score:
    """
    Voegt een reeks individuele MusicXML-partituren (music21.stream.Score) samen.
    
    Elke sectie in sections_info bevat minimaal:
      - 'label': str (bijv. 'Voorspel', 'Koraal', 'Naspel')
      - 'score': music21.stream.Score (met PartStaff R en L)
      - 'bpm': float
      - 'm': int (bijv. 4 of 6 voor 3/2)
      - 'grid': int (bijv. 2)
    """
    combined = m21.stream.Score()
    combined.metadata = m21.metadata.Metadata(title=full_title, composer=composer)

    combined_r = m21.stream.PartStaff()
    combined_r.id = "R"
    combined_r.insert(0, m21.instrument.Piano())
    combined_r.insert(0, m21.clef.TrebleClef())

    combined_l = m21.stream.PartStaff()
    combined_l.id = "L"
    combined_l.insert(0, m21.instrument.Piano())
    combined_l.insert(0, m21.clef.BassClef())

    m_num = 1
    total_sections = len(sections_info)

    for seg_idx, info in enumerate(sections_info):
        label = info.get("label", f"Deel {seg_idx + 1}")
        sub_score = info["score"]
        bpm = float(info.get("bpm", 100))
        m = int(info.get("m", 4))
        grid = int(info.get("grid", 2))
        ts_str = time_signature_string(m, grid)

        # Haal de twee partijen op (R = 0, L = 1)
        r_measures = list(sub_score.parts[0].getElementsByClass(m21.stream.Measure))
        l_measures = list(sub_score.parts[1].getElementsByClass(m21.stream.Measure))
        n_meas = max(len(r_measures), len(l_measures))

        for i in range(n_meas):
            mr = copy.deepcopy(r_measures[i]) if i < len(r_measures) else m21.stream.Measure()
            ml = copy.deepcopy(l_measures[i]) if i < len(l_measures) else m21.stream.Measure()

            mr.number = m_num
            ml.number = m_num

            # Begin van de sectie
            if i == 0:
                # Repetitieteken met sectienaam (bijv. [Voorspel], [Koraal], [Naspel])
                mr.insert(0, m21.expressions.RehearsalMark(label))
                # Tempo-aanduiding
                mr.insert(0, m21.tempo.MetronomeMark(number=round(bpm)))
                # Maatsoort expliciet instellen
                ts_obj_r = m21.meter.TimeSignature(ts_str)
                ts_obj_l = m21.meter.TimeSignature(ts_str)
                mr.insert(0, ts_obj_r)
                ml.insert(0, ts_obj_l)

            # Einde van de sectie
            if i == n_meas - 1:
                if seg_idx < total_sections - 1:
                    # Dubbele maatstreep als overgang naar de volgende sectie
                    mr.rightBarline = m21.bar.Barline("double")
                    ml.rightBarline = m21.bar.Barline("double")
                else:
                    # Slotmaatstreep aan het einde van het hele stuk
                    mr.rightBarline = m21.bar.Barline("final")
                    ml.rightBarline = m21.bar.Barline("final")

            combined_r.append(mr)
            combined_l.append(ml)
            m_num += 1

    combined.insert(0, combined_r)
    combined.insert(0, combined_l)
    combined.insert(0, m21.layout.StaffGroup([combined_r, combined_l], name="Piano", abbreviation="Pno.", symbol="brace"))

    return combined


def stitch_midi(
    sections_info: List[Dict[str, Any]],
    output_path: Path,
    pause_sec: float = 1.5,
) -> None:
    """
    Voegt noten uit meerdere secties samen tot één aaneengesloten PrettyMIDI-bestand.
    Tussen opeenvolgende secties wordt een natuurlijke pauze (pause_sec) ingelast.
    Tijdshandtekeningen en tempo-wisselingen worden per sectie geplaatst.
    """
    first_bpm = float(sections_info[0].get("bpm", 100))
    out_pm = pretty_midi.PrettyMIDI(initial_tempo=first_bpm, resolution=480)
    inst = pretty_midi.Instrument(program=0, name="Piano")

    current_time_offset = 0.0

    for seg_idx, info in enumerate(sections_info):
        bpm = float(info.get("bpm", 100))
        m = int(info.get("m", 4))
        grid = int(info.get("grid", 2))
        hands = info.get("hands", {})

        # Maatsoort-event voor deze sectie
        # 6 tellen = 3/2, anders m/4
        sig_num, sig_den = (3, 2) if m == 6 else (m, 4)
        out_pm.time_signature_changes.append(
            pretty_midi.TimeSignature(sig_num, sig_den, time=current_time_offset)
        )

        spu = 60.0 / bpm / grid
        sec_max_time = 0.0

        for groups in hands.values():
            for on, dur, pitches in groups:
                n_start = current_time_offset + on * spu
                n_end = current_time_offset + (on + dur) * spu
                for p, v in pitches:
                    inst.notes.append(
                        pretty_midi.Note(
                            velocity=int(v),
                            pitch=int(p),
                            start=n_start,
                            end=n_end,
                        )
                    )
                if (on + dur) * spu > sec_max_time:
                    sec_max_time = (on + dur) * spu

        current_time_offset += sec_max_time + pause_sec

    out_pm.instruments.append(inst)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_pm.write(str(output_path))
