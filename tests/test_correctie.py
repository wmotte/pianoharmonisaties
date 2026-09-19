import unittest
from types import SimpleNamespace

from music21 import key, note

from corrigeer_harmonie import apply, line_cost, revoice
from harmonie_regels import NoteRec, Vertical, assign_slots


class CorrectionTests(unittest.TestCase):
    def test_leap_recovery(self):
        older = [(0, 60, 'R')]
        previous = [(1, 67, 'R')]
        down = [(2, 65, 'R')]
        up = [(2, 69, 'R')]
        orig = {0: 60, 1: 67, 2: 65}
        self.assertLess(line_cost(older, previous, down, orig, {2}),
                        line_cost(older, previous, up, orig, {2}))

    def test_preserve_moving_line(self):
        orig = {0: 60, 1: 62}
        self.assertLess(line_cost([], [(0, 60, 'R')], [(1, 62, 'R')], orig, {1}),
                        line_cost([], [(0, 60, 'R')], [(1, 60, 'R')], orig, {1}))

    def test_sustained_outer_voice_and_determinism(self):
        records = [NoteRec(i, note.Note(m), None, st, on, end, 1, on + 1)
                   for i, (m, st, on, end) in enumerate([
                       (48, 'L', 0, 2), (60, 'R', 0, 2), (67, 'R', 0, 1),
                       (55, 'R', 1, 2)])]
        verticals = [Vertical(t, sorted([r for r in records if r.on <= t < r.end],
                                       key=lambda r: r.midi), 1, t + 1,
                              key.Key('C'), (0, 'maj', 3)) for t in (0, 1)]
        for v in verticals:
            assign_slots(v)
        score = SimpleNamespace(recs=records, verticals=verticals)
        changes = revoice(score)
        self.assertEqual(changes, revoice(score))
        self.assertNotIn(1, changes)  # C4 wordt pas bij de tweede inzet sopraan.
        timing = [(r.on, r.end, r.staff) for r in records]
        apply(score, changes)
        self.assertEqual(timing, [(r.on, r.end, r.staff) for r in records])

    def test_invalid_beam(self):
        with self.assertRaises(ValueError):
            revoice(SimpleNamespace(recs=[], verticals=[]), beam=0)

    def test_empty_score(self):
        self.assertEqual(revoice(SimpleNamespace(recs=[], verticals=[])), {})


if __name__ == '__main__':
    unittest.main()
