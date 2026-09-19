"""Onafhankelijke acceptatiecontrole van de gepubliceerde hypercorrecties."""
import json
import unittest
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
