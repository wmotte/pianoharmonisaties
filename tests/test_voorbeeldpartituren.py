"""Controleer de opgeslagen MusicXML-voorbeelden en hun correctierapport."""
import json
import unittest
from collections import Counter
from pathlib import Path

from harmonie_regels import Score, check, summary

ROOT = Path(__file__).resolve().parents[1]


class ExampleExportTests(unittest.TestCase):
    def test_export_preserves_structure_and_matches_report(self):
        results = json.loads((ROOT / 'harmonie_correctie.json').read_text())
        sources = sorted((ROOT / 'voorbeelden/ongecorrigeerd').glob('*.musicxml'))
        self.assertEqual(len(sources), 4)
        for source in sources:
            with self.subTest(piece=source.stem):
                original = Score(source)
                exported = Score(ROOT / 'voorbeelden/gecorrigeerd' / source.name)
                signature = lambda sc: Counter((r.staff, r.on, r.end, r.measure)
                                                for r in sc.recs)
                self.assertEqual(signature(original), signature(exported))
                self.assertEqual([v.on for v in original.verticals],
                                 [v.on for v in exported.verticals])
                for before, after in zip(original.verticals, exported.verticals):
                    self.assertEqual(min(r.midi for r in before.notes),
                                     min(r.midi for r in after.notes))
                    self.assertEqual(max(r.midi for r in before.notes),
                                     max(r.midi for r in after.notes))
                self.assertEqual(summary(check(exported), len(exported.verticals)),
                                 results[source.stem]['na'])


if __name__ == '__main__':
    unittest.main()
