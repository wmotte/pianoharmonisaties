"""Onafhankelijke acceptatiecontrole van de gepubliceerde hypercorrecties."""
import json
import unittest
import xml.etree.ElementTree as ET
from tempfile import TemporaryDirectory
from collections import Counter
from pathlib import Path

from harmonie_regels import Score, check, summary
from hypercorrectie import preservation, run_file

ROOT = Path(__file__).resolve().parents[1]


class HyperExampleTests(unittest.TestCase):
    def test_complete_checkpoint_resumes_without_new_search(self):
        source = next((ROOT / 'voorbeelden/ongecorrigeerd').glob('*Psalm 85*'))
        report = json.loads((ROOT / 'voorbeelden/hypercorrectie/hypercorrectie.json').read_text())
        previous = report[source.stem]
        with TemporaryDirectory() as tmp:
            result = run_file(source, Path(tmp) / source.name, checkpoint=previous, seconds=1)
        self.assertEqual(result['status'], 'volledig')
        self.assertEqual(result['zoektocht']['evaluaties'], 0)
        self.assertEqual(result['na'], previous['na'])
        self.assertEqual(result['gewijzigd'], previous['gewijzigd'])

    def test_psalm_85_measure_46_has_a_moving_accompaniment(self):
        path = next((ROOT / 'voorbeelden/hypercorrectie').glob('*Psalm 85*.musicxml'))
        score = Score(path)
        left = [r for r in score.recs if r.staff == 'L' and r.measure == 46]
        self.assertTrue(any(r.spitch.nameWithOctave == 'G2' and r.end - r.on == 3 for r in left))
        line = sorted((r.beat, r.spitch.nameWithOctave) for r in left if r.end - r.on < 3)
        self.assertEqual(line, [(1, 'D3'), (2, 'D4'), (2.5, 'E4'), (3, 'D4')])
        self.assertFalse(check(score))

    def test_all_four_exports_are_complete_and_keep_the_melody(self):
        path = ROOT / 'voorbeelden/hypercorrectie'
        report = json.loads((path / 'hypercorrectie.json').read_text())
        sources = sorted((ROOT / 'voorbeelden/ongecorrigeerd').glob('*.musicxml'))
        self.assertEqual(len(sources), 4)
        for source in sources:
            with self.subTest(piece=source.stem):
                original, result = Score(source), Score(path / source.name)
                findings = check(result)
                self.assertEqual(findings, [])
                row = report[source.stem]
                self.assertEqual(row['status'], 'volledig')
                self.assertEqual(row['na'], summary(findings, len(result.verticals)))
                self.assertEqual(row['extra_aanslagen'], len(result.recs) - len(original.recs))
                self.assertTrue(preservation(original, result)['geslaagd'])
                notes = ET.parse(path / source.name).findall('./part/measure/note')
                displayed_above = [n for n in notes if n.get('id', '').startswith('hc-cross-left-')]
                self.assertGreater(len(displayed_above), 0)
                self.assertEqual(len(displayed_above), row['bovenbalk_noten'])
                self.assertTrue(all(n.findtext('staff') == '1' for n in displayed_above))
                for n in notes:
                    if n.get('color', '').upper() == '#00A000' and n.findtext('staff') == '2':
                        octave = int(n.findtext('pitch/octave'))
                        step = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[n.findtext('pitch/step')]
                        midi = 12 * (octave + 1) + step + float(n.findtext('pitch/alter', '0'))
                        self.assertLess(midi, 60)
                # Verifieer de vaste noten los van de acceptatiefunctie.
                protected = {}
                for v in original.verticals:
                    right = [r for r in v.notes if r.staff == 'R']
                    for r in right:
                        if r.midi == max(n.midi for n in right):
                            protected[r.id] = r
                event = lambda r: (r.staff, r.on, r.end, r.spitch.nameWithOctave)
                exported = Counter(event(r) for r in result.recs)
                self.assertFalse(Counter(event(r) for r in protected.values()) - exported)


if __name__ == '__main__':
    unittest.main()
