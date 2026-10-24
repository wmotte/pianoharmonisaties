"""Zelfstandige stemmen en het verlaten van een unisono bij harmoniecontrole."""
import unittest
from types import SimpleNamespace

from music21 import key, note

from harmonie_regels import NoteRec, Vertical, assign_slots, check


def score_with_voices(events, *, named=True):
    """Events: (stem, balk, inzet, duur, toonhoogte)."""
    recs = [
        NoteRec(i, note.Note(p), None, staff, on, on + duration, 1, on + 1,
                voice=voice if named else None)
        for i, (voice, staff, on, duration, p) in enumerate(events)
    ]
    verticals = []
    for on in sorted({r.on for r in recs}):
        sounding = sorted((r for r in recs if r.on <= on < r.end), key=lambda r: r.midi)
        v = Vertical(on, sounding, 1, on + 1, key.Key("C"), (0, "maj", 0))
        assign_slots(v, named=named)
        verticals.append(v)
    return SimpleNamespace(recs=recs, verticals=verticals)


class StemidentiteitTest(unittest.TestCase):
    def test_tenor_bas_octaven_blijven_parallel_bij_vaste_stemmen(self):
        events = [(v, staff, on, 1, p) for on, pitches in enumerate([
            ["C3", "C4", "E4", "G4"], ["D3", "D4", "F#4", "A4"]
        ]) for v, staff, p in zip("BTAS", "LLRR", pitches)]
        findings = check(score_with_voices(events))
        self.assertEqual({f["note"] for f in findings if f["code"] == "P8"}, {"D3", "D4"})

    def test_pianistische_basoctaaf_heuristiek_blijft_beschikbaar(self):
        events = [(v, staff, on, 1, p) for on, pitches in enumerate([
            ["C3", "C4", "E4", "G4"], ["D3", "D4", "F#4", "A4"]
        ]) for v, staff, p in zip("BTAS", "LLRR", pitches)]
        self.assertFalse(any(f["code"] == "P8" for f in check(score_with_voices(events, named=False))))

    def test_van_unisono_uiteengaan_is_geen_kruising(self):
        events = [("T", "L", 0, 2, "A3"), ("B", "L", 0, 1, "A3"), ("B", "L", 1, 1, "A2")]
        self.assertFalse(any(f["code"] == "KR" for f in check(score_with_voices(events))))

    def test_door_een_aangehouden_stem_heen_bewegen_is_kruising(self):
        events = [("T", "L", 0, 2, "A3"), ("B", "L", 0, 1, "G3"), ("B", "L", 1, 1, "B3")]
        self.assertTrue(any(f["code"] == "KR" for f in check(score_with_voices(events))))


if __name__ == "__main__":
    unittest.main()
