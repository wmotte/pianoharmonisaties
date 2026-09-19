import unittest
import json
from unittest.mock import patch
from fractions import Fraction
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace

from music21 import key, note, chord, stream, spanner

from harmonie_regels import NoteRec, Vertical, assign_slots, check
import hypercorrectie as hyper
from hypercorrectie import (Search, named_pitch, melody_ids, preservation, articulate_accompaniment,
                            prepared_fingerprint, run_file, apply_preferences, DIR)


def fixture(events):
    records = [NoteRec(i, note.Note(m), None, staff, start, end, 1, start + 1)
               for i, (m, staff, start, end) in enumerate(events)]
    verticals = []
    for t in sorted({r.on for r in records}):
        notes = sorted([r for r in records if r.on <= t < r.end], key=lambda r: r.midi)
        v = Vertical(t, notes, 1, t + 1, key.Key('C'), (0, 'maj', 3.5))
        assign_slots(v)
        verticals.append(v)
    return SimpleNamespace(recs=records, verticals=verticals)


class HyperCorrectionTests(unittest.TestCase):
    def test_release_only_melody_is_protected(self):
        score = fixture([(48, 'L', 0, 3), (64, 'R', 0, 3), (72, 'R', 0, 1)])
        self.assertEqual(melody_ids(score), {1, 2})
        self.assertNotIn(1, Search(score).mutable)

    def test_candidates_cannot_overtake_melody_after_release(self):
        score = fixture([(48, 'L', 0, 3), (60, 'R', 0, 3),
                         (64, 'R', 0, 3), (72, 'R', 0, 1)])
        self.assertLessEqual(max(Search(score).candidates[1]), 64)

    def test_preservation_rejects_new_voice_above_unchanged_melody(self):
        source = fixture([(48, 'L', 0, 2), (64, 'R', 0, 2), (67, 'R', 0, 2)])
        result = fixture([(48, 'L', 0, 2), (76, 'R', 0, 2), (67, 'R', 0, 2)])
        self.assertFalse(preservation(source, result)['controles']['melodie_identiek'])

    def test_density_loss_after_release_is_not_missed(self):
        source = fixture([(48, 'L', 0, 3), (64, 'L', 0, 3),
                          (64, 'R', 0, 1), (67, 'R', 0, 3)])
        result = fixture([(48, 'L', 0, 3), (60, 'L', 0, 3),
                          (64, 'R', 0, 1), (67, 'R', 0, 3)])
        self.assertFalse(preservation(source, result)['controles']['toonklasdichtheid_behouden'])

    def test_failed_export_validation_preserves_previous_file(self):
        source = next((DIR / 'voorbeelden/ongecorrigeerd').glob('*Psalm 85*'))
        report = json.loads((DIR / 'voorbeelden/hypercorrectie/hypercorrectie.json').read_text())
        real_score = hyper.Score
        def parse(path):
            if Path(path).name == 'output.musicxml':
                raise ValueError('gesimuleerde exportfout')
            return real_score(path)
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / 'output.musicxml'
            target.write_text('bestaande partituur')
            with patch.object(hyper, 'Score', side_effect=parse):
                with self.assertRaisesRegex(ValueError, 'gesimuleerde exportfout'):
                    run_file(source, target, checkpoint=report[source.stem], seconds=1)
            self.assertEqual(target.read_text(), 'bestaande partituur')

    def test_run_file_rejects_source_as_output_before_parsing(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.musicxml'
            source.write_text('bron')
            with patch.object(hyper, 'Score') as parse:
                with self.assertRaisesRegex(ValueError, 'bron.*uitvoer'):
                    run_file(source, source)
                parse.assert_not_called()
            self.assertEqual(source.read_text(), 'bron')

    def test_preference_cannot_change_melody(self):
        score = fixture([(48, 'L', 0, 1), (72, 'R', 0, 1)])
        search = Search(score)
        with self.assertRaisesRegex(ValueError, 'melodie'):
            apply_preferences(search, [{'maat': 1, 'tel': 1, 'hand': 'R', 'van': 'C5', 'naar': 'D5'}])
        self.assertEqual(search.values, search.orig)

    def test_preference_keeps_selected_accompaniment_fixed(self):
        search = Search(fixture([(48, 'L', 0, 1), (72, 'R', 0, 1)]))
        apply_preferences(search, [{'maat': 1, 'tel': 1, 'hand': 'L', 'van': 'C3', 'naar': 'E3'}])
        self.assertEqual(search.values[0], 52)
        self.assertNotIn(0, search.mutable)

    def test_fingerprint_supports_tuplet_offsets(self):
        rational = fixture([(60, 'R', Fraction(1, 3), Fraction(2, 3))])
        floating = fixture([(60, 'R', 1 / 3, 2 / 3)])
        self.assertEqual(prepared_fingerprint(rational), prepared_fingerprint(floating))

    def test_resume_rejects_changed_source_before_export(self):
        source = next((DIR / 'voorbeelden/ongecorrigeerd').glob('*Psalm 85*'))
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / 'output.musicxml'
            with self.assertRaisesRegex(ValueError, 'bron of voorbereiding'):
                run_file(source, target, checkpoint={'bron_sha256': 'verkeerde bron'})
            self.assertFalse(target.exists())

    def test_enharmonic_octave_boundary(self):
        self.assertEqual(named_pitch(60, 'B#').midi, 60)
        self.assertEqual(named_pitch(59, 'C-').midi, 59)

    def test_melody_and_held_melody_never_mutable(self):
        score = fixture([(48, 'L', 0, 2), (60, 'R', 0, 3), (72, 'R', 1, 3)])
        search = Search(score)
        self.assertEqual(search.melody, {1, 2})
        self.assertEqual(search.mutable, {0})
        changes, _ = search.solve(rounds=3, seconds=10)
        self.assertFalse(search.melody & changes.keys())

    def test_high_left_hand_note_is_not_melody(self):
        score = fixture([(62, 'L', 0, 1), (60, 'R', 0, 1)])
        self.assertEqual(melody_ids(score), {1})
        self.assertIn(0, Search(score).mutable)

    def test_preservation_accepts_rearticulation_but_rejects_a_gap(self):
        source = fixture([(48, 'L', 0, 2), (72, 'R', 0, 2)])
        articulated = fixture([(48, 'L', 0, 1), (48, 'L', 1, 2), (72, 'R', 0, 2)])
        gap = fixture([(48, 'L', 0, 0.5), (48, 'L', 1, 2), (72, 'R', 0, 2)])
        self.assertTrue(preservation(source, articulated)['controles']['tijdsdekking_identiek'])
        self.assertFalse(preservation(source, gap)['controles']['tijdsdekking_identiek'])

    def test_parallel_repaired_with_fixed_melody(self):
        score = fixture([(48, 'L', 0, 1), (64, 'R', 0, 1), (72, 'R', 0, 1),
                         (50, 'L', 1, 2), (65, 'R', 1, 2), (74, 'R', 1, 2)])
        search = Search(score)
        self.assertGreater(search.objective()[0], 0)
        changes, result = search.solve(rounds=8, seconds=20)
        self.assertEqual(result['zoekfouten'], 0)
        self.assertTrue(changes)
        self.assertFalse(search.melody & changes.keys())
        repeated = Search(score).solve(rounds=8, seconds=20)[0]
        self.assertEqual(changes, repeated)

    def test_unsatisfiable_fixed_leading_tones_report_failure(self):
        score = fixture([(59, 'R', 0, 3), (71, 'R', 1, 3)])
        search = Search(score)
        changes, result = search.solve(rounds=3, seconds=10)
        self.assertEqual(changes, {})
        self.assertGreater(result['zoekfouten'], 0)

    def test_trial_does_not_mutate_source_or_current_state(self):
        score = fixture([(48, 'L', 0, 1), (64, 'R', 0, 1), (72, 'R', 0, 1)])
        search = Search(score)
        original = dict(search.values)
        factors = list(search.current)
        search.trial({0: 50})
        self.assertEqual(search.values, original)
        self.assertEqual(search.current, factors)
        self.assertEqual({r.id: r.midi for r in score.recs}, original)

    def test_articulation_preserves_spanner_endpoint(self):
        left = stream.PartStaff()
        held = chord.Chord([48, 52], quarterLength=2)
        endpoint = note.Note(55, quarterLength=1)
        left.insert(0, held)
        left.insert(2, endpoint)
        octave = spanner.Ottava(held, endpoint)
        left.insert(0, octave)
        score = fixture([(48, 'L', 0, 2), (52, 'L', 0, 2),
                         (84, 'R', 0, 1), (83, 'R', 1, 2)])
        for r, n in zip(score.recs[:2], held.notes):
            r.obj, r.parent = n, held
        score.parts = {'L': left}
        self.assertEqual(articulate_accompaniment(score), 1)
        self.assertIs(octave.getSpannedElements()[-1], endpoint)
        self.assertEqual(len(octave.getSpannedElements()), 3)
        fragments = list(left.recurse().getElementsByClass(chord.Chord))
        self.assertEqual([float(c.quarterLength) for c in fragments], [1, 1])
        self.assertEqual([c.notes[0].tie.type for c in fragments], ['start', 'stop'])
        self.assertTrue(all(c.notes[1].tie is None for c in fragments))

    def test_anchor_proposal_is_transactional(self):
        score = fixture([(48, 'L', 0, 2), (72, 'R', 0, 2)])
        search = Search(score)
        _, updated = search.trial({0: 55})
        search.commit({0: 55}, updated)
        values, current = dict(search.values), list(search.current)
        import time
        proposal = search.anchor_trial(0, time.monotonic() + 5)
        self.assertIsNotNone(proposal)
        self.assertEqual(search.values, values)
        self.assertEqual(search.current, current)
        self.assertEqual(proposal[1][0], 48)

    def test_checker_note_ids_are_optional(self):
        events = [(59, 'R', 0, 3), (71, 'R', 1, 3)]
        plain = check(fixture(events))
        identified = check(fixture(events), include_ids=True)
        self.assertTrue(identified)
        self.assertTrue(all('note_id' in f for f in identified))
        self.assertEqual(plain, [{k: v for k, v in f.items() if k != 'note_id'} for f in identified])

    def test_harmonic_density_cannot_be_silently_removed(self):
        score = fixture([(48, 'L', 0, 1), (64, 'R', 0, 1), (67, 'R', 0, 1)])
        search = Search(score)
        _, factors = search.trial({0: 52})
        self.assertTrue(any(code == 'KLEURVERLIES' for errors, _ in factors.values()
                            for _, code in errors))


if __name__ == '__main__':
    unittest.main()
