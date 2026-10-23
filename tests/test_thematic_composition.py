"""Musical contracts for source-derived composition, instruments, and score export."""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import mido
from music21 import converter, instrument

from harmonizer.arrange import frame_arrangement
from harmonizer.counterpoint import CompositionError, add_countervoice, hand_assignment, line_issues, strong_beat
from harmonizer.engine import Arrangement, Harmony, build_arrangement
from harmonizer.midi import expression_map, save_midi, validate_export
from harmonizer.model import Event, Melody
from harmonizer.motifs import extract_motifs, scale_pitch, scale_position, transform
from harmonizer.notation import save_musicxml
from harmonizer.prelude import free_section


def tune():
    return Melody([Event(p, i * 2, 2) for i, p in enumerate((67, 69, 71, 72, 74, 71, 69, 67))],
                  16, [(0, 4, 4)], [8, 16], 7, "major", 90)


def score(notes, harmonies=None, length=4):
    return Arrangement(notes, harmonies or [Harmony(0, length, 0, "major", 48, (55, 64))],
                       [{"name": "Harmonisatie", "start": 0, "end": length}],
                       [(0, 4, 4)], [length], [], 90, 0, 0, 0, length, {})


class MotifTests(unittest.TestCase):
    def test_inversion_keeps_octave_direction(self):
        melody = Melody([Event(p, i, 1) for i, p in enumerate((60, 62, 64))], 3,
                        [(0, 3, 4)], [3], 0, "major")
        inverted = transform(extract_motifs(melody)[0], invert=True)
        self.assertEqual([scale_pitch(t.degree, 0, "major", t.alteration) for t in inverted.tones],
                         [60, 59, 57])

    def test_retrograde_reverses_events_with_rests_and_durations(self):
        melody = Melody([Event(60, 0, 1), Event(62, 2, 0.5), Event(64, 2.5, 1.5)],
                        4, [(0, 4, 4)], [4], 0, "major")
        original = extract_motifs(melody)[0]
        reverse = transform(original, retrograde=True, time_scale=0.5)
        self.assertEqual([(t.offset, t.duration) for t in reverse.tones],
                         [(0, 0.75), (0.75, 0.25), (1.5, 0.5)])
        restored = transform(transform(original, retrograde=True), retrograde=True)
        self.assertEqual(restored.tones, original.tones)

    def test_no_cell_crosses_phrase_and_last_duration_is_preserved(self):
        melody = tune()
        for m in extract_motifs(melody):
            start = 0 if m.phrase == 0 else melody.phrases[m.phrase - 1]
            self.assertGreaterEqual(m.source_start, start)
            self.assertLessEqual(m.source_end, melody.phrases[m.phrase])
            self.assertEqual(m.tones[-1].offset + m.tones[-1].duration, m.span)

    def test_chromatic_and_octave_roundtrip(self):
        for mode in ("major", "dorian", "mixolydian"):
            for p in range(36, 85):
                degree, alteration = scale_position(p, 4, mode)
                self.assertEqual(scale_pitch(degree, 4, mode, alteration), p)

    def test_short_input_and_invalid_time_scale(self):
        m = Melody([Event(60, 1, 2)], 3, [(0, 3, 4)], [3], 0, "major")
        cell = extract_motifs(m)[0]
        self.assertEqual(cell.source_start, 1)
        for scale in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                transform(cell, time_scale=scale)


class CounterpointTests(unittest.TestCase):
    def test_short_breath_does_not_hide_consecutive_unisons(self):
        report = line_issues([Event(67, 0, 0.5), Event(69, 1, 1)],
                             [Event(67, 0, 1), Event(69, 1, 1)],
                             [Harmony(0, 1, 0, "major", 48, ()), Harmony(1, 2, 2, "minor", 50, ())],
                             [(0, 4, 4)])
        self.assertFalse(report["valid"])

    def test_parallel_against_sung_melody_is_checked(self):
        report = line_issues([Event(72, 0, 1), Event(74, 1, 1)],
                             [Event(60, 0, 1), Event(62, 1, 1)],
                             [Harmony(0, 1, 0, "major", 48, ()), Harmony(1, 2, 2, "minor", 50, ())],
                             [(0, 4, 4)])
        self.assertIn("countervoice_parallel", [r["code"] for r in report["issues"]])

    def test_held_note_is_checked_at_changed_harmony(self):
        report = line_issues([Event(64, 0, 4)], [],
                             [Harmony(0, 2, 0, "major", 48, ()), Harmony(2, 4, 2, "minor", 50, ())],
                             [(0, 4, 4)])
        self.assertFalse(report["valid"])
        self.assertEqual(report["issues"][0]["beat"], 2)

    def test_prepared_suspension_and_weak_passing_note(self):
        hs = [Harmony(0, 1, 0, "major", 48, ()), Harmony(1, 3, 7, "major", 43, ())]
        report = line_issues([Event(72, 0, 1), Event(72, 1, 1), Event(71, 2, 1)], [], hs, [(0, 4, 4)])
        self.assertTrue(report["valid"], report)
        self.assertIn("suspension", [r["kind"] for r in report["classified_dissonances"]])
        report = line_issues([Event(60, 0, 0.5), Event(62, 0.5, 0.5), Event(64, 1, 1)], [],
                             [Harmony(0, 2, 0, "major", 48, ())], [(0, 4, 4)])
        self.assertTrue(report["valid"], report)

    def test_compound_meter_and_half_note_beats(self):
        self.assertTrue(strong_beat([(0, 6, 8)], 1.5))
        self.assertFalse(strong_beat([(0, 6, 8)], 0.5))
        self.assertTrue(strong_beat([(0, 2, 2)], 2))
        self.assertFalse(strong_beat([(0, 4, 4)], 1))

    def test_moderate_flute_can_pass_under_song(self):
        report = line_issues([Event(64, 0, 2, part="flute")], [Event(72, 0, 2)],
                             [Harmony(0, 2, 0, "major", 48, ())], [(0, 4, 4)])
        self.assertTrue(report["valid"])

    def test_impossible_search_is_explicit(self):
        m = Melody([Event(84, 0, 4)], 4, [(0, 4, 4)], [4], 0, "major")
        with self.assertRaises(CompositionError):
            add_countervoice(score(m.notes), m, "piano")


class IntegrationTests(unittest.TestCase):
    def test_source_rests_remain_supported_in_a_complete_piano_phrase(self):
        from harmonizer.model import load_melody

        m = load_melody(Path(__file__).resolve().parents[1] /
                        "harmonisatie/voorbeelden/psalm_49.melodie.json", {})
        top, _, _, plan = free_section(m, 96, "Voorspel", 0)
        self.assertEqual(top.length, 96)
        self.assertTrue(any(b.start > a.end for a, b in zip(top.notes, top.notes[1:])))
        self.assertTrue(plan["accompaniment"])

    def test_three_beat_cadence_resolves_on_the_actual_last_beat(self):
        top, hs, _, _ = free_section(tune(), 36, "Voorspel", 0,
                                    settings={"meter": [3, 4], "quarter_bpm": 90, "source": {}})
        self.assertEqual(top.notes[-1].end, 36)
        self.assertEqual([(h.start, h.end) for h in hs[-2:]], [(33, 35), (35, 36)])
        self.assertEqual([h.quality for h in hs[-2:]], ["sus4", "major"])

    def test_free_piano_has_a_recognizable_opening_and_stable_harmonic_pulse(self):
        m = Melody([Event(p, i * 2, 2) for i, p in enumerate((64, 71, 67, 69, 69, 67, 66, 64))],
                   16, [(0, 4, 4)], [8, 16], 4, "dorian", 90)
        top, harmonies, _, plan = free_section(m, 96, "Voorspel", 0)
        self.assertEqual([n.pitch for n in top.notes[:4]], [64, 71, 67, 69])
        self.assertTrue(all(h.start % 2 == 0 for h in harmonies))
        self.assertTrue(all(n["start"] % 2 == 0 for n in plan["accompaniment"]))
        for phase in plan["phrases"]:
            end = phase["end"]
            if phase["cadence"] == "dominant":
                last = [h for h in harmonies if end - 4 <= h.start < end]
                self.assertEqual([h.quality for h in last], ["sus4", "major"])
                self.assertEqual(last[0].root, last[1].root)
        self.assertLessEqual(max(abs(b.pitch - a.pitch) for a, b in zip(top.notes, top.notes[1:])), 7)

    def test_hand_engraving_keeps_inner_voice_identity_across_measures(self):
        from koele.componeer import mp

        stuk = {"titel": "Engraving", "secties": [{"toonaard": "C", "toonsoort": 0, "maat": "4/4",
                "melodie": "C5/2 R/2 | D5/1 |]", "1": "C5/2 R/2 | D5/1 |]",
                "2": "G4/1~ | G4/1 |]", "3": "E4/1~ | E4/1 |]", "4": "C3/1 | D3/1 |]"}],
                "handverdeling": [[72, 0, 2, "RH"], [74, 4, 8, "RH"], [67, 0, 8, "RH"],
                                   [64, 0, 8, "RH"], [48, 0, 4, "LH"], [50, 4, 8, "LH"]]}
        right = mp.bouw(stuk).parts[-2]
        for measure in right.getElementsByClass("Measure"):
            self.assertTrue(any(int(n.pitch.midi) == 67 for n in measure.voices[1].notes))
            self.assertTrue(any(int(n.pitch.midi) == 64 for n in measure.voices[2].notes))

    def test_chord_labels_inside_a_voice_are_not_counted_as_played_notes(self):
        from music21 import harmony, note, stream
        from harmonizer.notation import _sounding

        s, part, measure, voice = stream.Score(), stream.Part(), stream.Measure(), stream.Voice()
        voice.insert(0, note.Note("C4", quarterLength=4))
        measure.insert(0, voice)
        part.append(measure)
        s.append(part)
        before = _sounding(s)
        voice.insert(0, harmony.ChordSymbol("C"))
        self.assertEqual(_sounding(s), before)

    def test_low_modal_entrance_preserves_the_melody_and_reaches_its_cadence(self):
        pitches = (60, 60, 62, 63, 65, 67, 65, 63, 62, 60, 62, 60)
        m = Melody([Event(p, i, 1) for i, p in enumerate(pitches)],
                   12, [(0, 4, 4)], [6, 12], 0, "dorian", 80)
        a = build_arrangement(m, {"status": "draft"},
                              {"intro_beats": 16, "outro_beats": 16}, 1)
        self.assertEqual(a.diagnostics["framing_search"]["requested_seed"], 1)
        self.assertEqual([n.pitch for n in a.notes if n.role == "melody"], list(pitches))
        self.assertEqual(a.harmony[-1].quality, "minor")

    def test_named_voices_do_not_reassign_a_resting_tenor_to_the_melody(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "koele"))
        import maak_partituren as mp
        from harmonie_regels import Score, check

        stuk = {"titel": "Voice identity", "secties": [{
            "toonsoort": 0, "toonaard": "C", "maat": "4/4",
            "melodie": "D5/1 | G5/1 |]", "1": "D5/1 | G5/1 |]",
            "2": "B4/1 | A4/1 |]", "3": "G4/1 | R/1 |]", "4": "G3/1 | A2/1 |]"}]}
        with TemporaryDirectory() as d:
            path = Path(d) / "named.musicxml"
            mp.bouw(stuk, met_zang=False).write("musicxml", fp=path)
            inferred = check(Score(path))
            named = check(Score(path, voice_identity=True))
            self.assertIn("AP8", {x["code"] for x in inferred})
            self.assertNotIn("AP8", {x["code"] for x in named})

    def test_named_voices_still_reject_real_parallel_octaves(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "koele"))
        import maak_partituren as mp
        from harmonie_regels import Score, check

        stuk = {"titel": "Actual octaves", "secties": [{
            "toonsoort": 0, "toonaard": "C", "maat": "4/4",
            "melodie": "C5/1 | D5/1 |]", "1": "C5/1 | D5/1 |]",
            "2": "G4/1 | A4/1 |]", "3": "C4/1 | D4/1 |]", "4": "G2/1 | A2/1 |]"}]}
        with TemporaryDirectory() as d:
            path = Path(d) / "octaves.musicxml"
            mp.bouw(stuk, met_zang=False).write("musicxml", fp=path)
            self.assertIn("P8", {x["code"] for x in check(Score(path, voice_identity=True))})

    def test_thematic_generation_is_repeatable_and_reports_actual_notes(self):
        m = tune()
        first = free_section(m, 32, "Voorspel", 3)
        self.assertEqual(first, free_section(m, 32, "Voorspel", 3))
        plan = first[3]
        self.assertGreaterEqual(plan["exact_pitch_retention"], 0.5)
        self.assertTrue(plan["realized_motifs"])
        self.assertTrue(all(cell["source_start"] < m.length for cell in plan["motifs"]))

    def test_three_profiles_roundtrip_and_fermata_stretch(self):
        m = tune()
        with TemporaryDirectory() as tmp:
            for profile in ("none", "flute", "piano"):
                a = build_arrangement(m, {"status": "draft"},
                                      {"intro_beats": 16, "outro_beats": 16, "countervoice": profile}, 0)
                self.assertIn(a.melody_offset, a.fermatas)
                pause = a.diagnostics["entry_pause"]
                self.assertAlmostEqual(dict(expression_map(a, {}))[pause["start"]], 60)
                self.assertEqual([(n.pitch, n.start - a.melody_offset, n.duration) for n in a.notes if n.role == "melody"],
                                 [(n.pitch, n.start, n.duration) for n in m.notes])
                mid = Path(tmp) / (profile + ".mid")
                save_midi(a, mid, {}, expressive=True)
                self.assertTrue(validate_export(mid, a, expressive=True)["all_notes_exact_after_export"])
                xml = Path(tmp) / (profile + ".musicxml")
                self.assertTrue(save_musicxml(a, xml, 7)["melody_voice_exact_after_export"])
                parsed = converter.parse(xml)
                if profile == "flute":
                    fluit = sorted((n for n in a.notes if n.part == "flute"), key=lambda n: n.start)
                    self.assertTrue(fluit)
                    self.assertTrue(all(60 <= n.pitch <= 74 for n in fluit))  # C4-D5
                    self.assertTrue(all(abs(y.pitch - x.pitch) <= 4 for x, y in zip(fluit, fluit[1:])
                                        if abs(x.start + x.duration - y.start) < 1e-6))  # sprong hoogstens een terts
                    self.assertIsInstance(parsed.parts[-1].getInstrument(), instrument.Flute)
                    messages = list(mido.MidiFile(mid))
                    self.assertTrue(any(x.type == "program_change" and x.channel == 1 and x.program == 73 for x in messages))
                    self.assertFalse(any(x.type == "control_change" and x.channel == 1 and x.control == 64 and x.value >= 64 for x in messages))

    def test_retained_melody_can_be_written_in_left_hand(self):
        notes = [Event(60, 0, 4), Event(48, 0, 4, role="bass"), Event(79, 0, 4, role="descant")]
        a = score(notes)
        a.diagnostics["hand_assignment"] = hand_assignment(notes)
        self.assertIsNotNone(a.diagnostics["hand_assignment"])
        with TemporaryDirectory() as d:
            self.assertTrue(save_musicxml(a, Path(d) / "piano.musicxml")["melody_voice_exact_after_export"])

    def test_midi_instrument_tampering_is_detected(self):
        notes = [Event(60, 0, 4), Event(72, 0, 4, role="descant", part="flute")]
        a = score(notes)
        with TemporaryDirectory() as d:
            path = Path(d) / "bad.mid"
            save_midi(a, path, {})
            midi = mido.MidiFile(path)
            for track in midi.tracks:
                for event in track:
                    if event.type == "program_change" and event.channel == 1:
                        event.program = 0
            midi.save(path)
            with self.assertRaises(ValueError):
                validate_export(path, a)

    def test_source_chord_symbols_override_ambiguous_chord_inference(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "koele"))
        from componeer import source_arrangement

        stuk = {"titel": "Modal test", "secties": [{
            "toonsoort": 2, "toonaard": "e", "maat": "4/4", "tempo": 90,
            "tekst": ["Test"], "melodie": "E4/1 | E4/1 |]",
            "2": "B3/1 | B3/1 |]", "3": "A3/1 | G#3/1 |]", "4": "E3/1 | E3/1 |]",
            "akkoorden": "Esus4/1 | E/1 |]"}]}
        m, a, _, _ = source_arrangement(stuk)
        self.assertEqual(m.mode, "dorian")
        self.assertEqual(a.harmony[0].quality, "sus4")
        self.assertEqual(a.harmony[-1].quality, "major")
        framed = frame_arrangement(m, a, {"intro_beats": 16, "outro_beats": 16})
        self.assertEqual(framed.harmony[-1].quality, "major")

    def test_stuk_ties_decompose_non_single_note_values(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "koele"))
        from componeer import _events, stem_text
        from music21 import key

        events = [Event(61, 0.5, 5)]
        text = stem_text(events, [(0, 4, 4, 4), (4, 8, 4, 4)], key.Key("D"))
        self.assertNotIn("t", text)
        restored, _, length = _events(text, key.KeySignature(2), "melody")
        self.assertEqual([(n.pitch, n.start, n.duration) for n in restored], [(61, 0.5, 5)])
        self.assertEqual(length, 8)

    def test_binary_note_lengths_never_introduce_tuplets(self):
        from fractions import Fraction
        from music21 import key
        from koele.componeer import _duration_parts, _events

        for length in (Fraction(5, 2), Fraction(9, 4), Fraction(11, 4), Fraction(13, 8)):
            tokens = _duration_parts(length)
            self.assertFalse(any("t" in token for token in tokens))
            parsed, _, _ = _events(
                " ".join("C4" + token + ("~" if i < len(tokens) - 1 else "")
                         for i, token in enumerate(tokens)) + " |]", key.KeySignature(0), "melody")
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0].duration, float(length))


if __name__ == "__main__":
    unittest.main()
