import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

from piano_notatie import logical_score_xml, place_high_bass_notes, PREFIX


XML = '''<score-partwise><part id="p"><measure number="1">
<note color="#00A000"><pitch><step>E</step><octave>3</octave></pitch><duration>4</duration><voice>3</voice><staff>2</staff></note>
<note color="#00A000" default-y="50"><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><tie type="start"/><voice>3</voice><staff>2</staff></note>
<note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><voice>3</voice><staff>2</staff></note>
<note color="#00A000"><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><staff>1</staff></note>
</measure></part></score-partwise>'''


def xml_events(root):
    events = Counter()
    for mi, measure in enumerate(root.findall('./part/measure')):
        cursor, onset = 0, 0
        for el in measure:
            if el.tag == 'backup':
                cursor -= int(el.findtext('duration'))
            elif el.tag == 'forward':
                cursor += int(el.findtext('duration'))
            elif el.tag == 'note':
                duration = int(el.findtext('duration', '0'))
                if el.find('chord') is None:
                    onset = cursor
                    cursor += duration
                events[(mi, onset, duration, el.findtext('pitch/step'), el.findtext('pitch/alter'),
                        el.findtext('pitch/octave'), el.findtext('voice'), el.findtext('staff'),
                        tuple(t.get('type') for t in el.findall('tie')))] += 1
    return events


class CrossStaffTests(unittest.TestCase):
    def test_only_high_changed_left_notes_move_and_keep_sound_data(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'score.musicxml'
            path.write_text(XML)
            self.assertEqual(place_high_bass_notes(path), 1)
            notes = ET.parse(path).findall('.//note')
            self.assertEqual([n.findtext('staff') for n in notes], ['2', '1', '2', '1'])
            self.assertNotEqual(notes[1].findtext('voice'), notes[3].findtext('voice'))
            self.assertIsNone(notes[1].find('chord'))
            self.assertEqual(ET.parse(path).findtext('.//backup/duration'), '4')
            self.assertEqual(notes[1].find('tie').get('type'), 'start')
            self.assertNotIn('default-y', notes[1].attrib)
            self.assertTrue(notes[1].get('id').startswith(PREFIX))
            normalized = ET.fromstring(logical_score_xml(path))
            self.assertEqual(xml_events(ET.fromstring(XML)), xml_events(normalized))
            before = path.read_bytes()
            self.assertEqual(place_high_bass_notes(path), 0)
            self.assertEqual(path.read_bytes(), before)

    def test_duplicate_voice_numbers_are_separated_between_staves(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'score.musicxml'
            path.write_text(XML.replace('<voice>3</voice>', '<voice>1</voice>'))
            place_high_bass_notes(path)
            notes = ET.parse(path).findall('.//note')
            left_voices = {n.findtext('voice') for n in notes[:3]}
            self.assertFalse(left_voices & {notes[3].findtext('voice')})
            restored = ET.fromstring(logical_score_xml(path)).findall('.//note')
            self.assertTrue(all(n.findtext('voice') == '1' for n in restored))

    def test_unmarked_score_does_not_get_normalized(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'score.musicxml'
            path.write_text(XML)
            self.assertIsNone(logical_score_xml(path))

    def test_invalid_cross_staff_marker_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'score.musicxml'
            path.write_text(XML.replace('<note color=', f'<note id="{PREFIX}bad" color=', 1))
            with self.assertRaisesRegex(ValueError, 'ongeldige balkverplaatsing'):
                logical_score_xml(path)


if __name__ == '__main__':
    unittest.main()
