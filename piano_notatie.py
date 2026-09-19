"""MusicXML-weergave van hoge begeleidingsnoten op de bovenste pianobalk.

De muzikale stemverdeling, toonhoogte en duur blijven behouden. De balk verandert,
en stemnummers worden ondubbelzinnig gemaakt. Metadata bewaart de oorspronkelijke indeling.
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

PREFIX = 'hc-cross-left-'
VOICE_META = 'hc-left-voices'
GREEN = '#00A000'
STEPS = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def _tree(path):
    return ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


def logical_score_xml(path):
    """Herstel de logische balk en stemnummers voor analyse, zonder toonhoogtes aan te passen."""
    path = Path(path)
    if path.suffix.lower() not in ('.xml', '.musicxml'):
        return None
    if PREFIX not in path.read_text():
        return None
    tree = _tree(path)
    changed = False
    for n in tree.findall('./part/measure/note'):
        if n.get('id', '').startswith(PREFIX):
            staff = n.find('staff')
            if staff is None or staff.text != '1':
                raise ValueError('ongeldige balkverplaatsing: gemarkeerde noot staat niet op balk 1')
            staff.text = '2'
            changed = True
    if changed:
        field = tree.find(f'./identification/miscellaneous/miscellaneous-field[@name="{VOICE_META}"]')
        if field is not None:
            mappings = json.loads(field.text)
            for pi, part in enumerate(tree.findall('./part')):
                for mi, measure in enumerate(part.findall('measure')):
                    mapping = mappings.get(f'{pi}:{mi}', {})
                    for element in measure:
                        voice = element.find('voice')
                        if element.findtext('staff') == '2' and voice is not None:
                            voice.text = mapping.get(voice.text, voice.text)
            tree.find('./identification/miscellaneous').remove(field)
    return ET.tostring(tree.getroot(), encoding='unicode') if changed else None


def _split_mixed_chords(tree):
    """Geef hoge en lage noten aparte akkoorden op hetzelfde tijdstip.

    MuseScore verplaatst een akkoord als geheel. Een gemengd akkoord blijft
    daarom niet één akkoord met nootkoppen op twee balken.
    """
    for measure in tree.findall('./part/measure'):
        elements = list(measure)
        groups, group = [], []
        for element in elements:
            if element.tag == 'note' and element.find('chord') is not None and group:
                group.append(element)
            else:
                if group:
                    groups.append(group)
                group = [element] if element.tag == 'note' else []
        if group:
            groups.append(group)
        for group in groups:
            high = [n for n in group if n.get('id', '').startswith(PREFIX)]
            low = [n for n in group if n not in high]
            if not high or not low:
                continue
            durations = {n.findtext('duration') for n in group}
            if len(durations) != 1:
                raise ValueError('balkwissel vereist gelijke nootduren binnen een akkoord')
            index = list(measure).index(group[0])
            dynamics = group[0].get('dynamics')
            for n in group:
                measure.remove(n)
                chord = n.find('chord')
                if chord is not None:
                    n.remove(chord)
            replacement = []
            for gi, notes in enumerate((low, high)):
                if gi:
                    backup = ET.Element('backup')
                    ET.SubElement(backup, 'duration').text = next(iter(durations))
                    replacement.append(backup)
                if dynamics is not None and notes[0].get('dynamics') is None:
                    notes[0].set('dynamics', dynamics)
                for ni, n in enumerate(notes):
                    if ni:
                        position = next((i for i, child in enumerate(n) if child.tag in ('pitch', 'unpitched')), 0)
                        n.insert(position, ET.Element('chord'))
                    replacement.append(n)
            for i, element in enumerate(replacement):
                measure.insert(index + i, element)


def place_high_bass_notes(path, threshold=60):
    """Zet gewijzigde linkerhandnoten vanaf C4 op balk 1, in hun bestaande stem.

    MusicXML pitch bevat de klinkende toonhoogte. Een balkwissel vraagt dus geen
    octaaftranspositie, ook niet wanneer op de doelbalk een octaaflijn staat.
    """
    tree = _tree(path)
    moved = 0
    # Reserveer aparte numerieke stemnummers voor links. Gelijke nummers op
    # verschillende balken zijn zonder balkwissel geldig, maar daarna dubbelzinnig.
    if any(n.get('id', '').startswith(PREFIX) for n in tree.findall('./part/measure/note')):
        return 0
    right = [int(n.findtext('voice', '1')) for n in tree.findall('./part/measure/note')
             if n.findtext('staff') == '1']
    first_left = max(right, default=0) + 1
    mappings = {}
    for pi, part in enumerate(tree.findall('./part')):
        for mi, measure in enumerate(part.findall('measure')):
            original = sorted({n.findtext('voice', '1') for n in measure.findall('note')
                               if n.findtext('staff') == '2'}, key=int)
            forward = {v: str(first_left + i) for i, v in enumerate(original)}
            mappings[f'{pi}:{mi}'] = {new: old for old, new in forward.items()}
            for element in measure:
                voice = element.find('voice')
                if element.findtext('staff') == '2' and voice is not None:
                    voice.text = forward[voice.text]
    upper_offset = max((len(m) for m in mappings.values()), default=1)
    note_measures = {id(n): f'{pi}:{mi}' for pi, part in enumerate(tree.findall('./part'))
                     for mi, measure in enumerate(part.findall('measure')) for n in measure.findall('note')}
    for index, n in enumerate(tree.findall('./part/measure/note')):
        staff, p = n.find('staff'), n.find('pitch')
        if staff is None or staff.text != '2' or p is None:
            continue
        if n.get('color', '').upper() != GREEN:
            continue
        midi = 12 * (int(p.findtext('octave')) + 1) + STEPS[p.findtext('step')] + float(p.findtext('alter', '0'))
        if midi < threshold:
            continue
        # Het akkoordverband en de muzikale stem blijven behouden.
        staff.text = '1'
        voice = n.find('voice')
        if voice is None:
            raise ValueError('balkwissel vereist een expliciet stemnummer')
        old_voice = voice.text
        voice.text = str(int(old_voice) + upper_offset)
        mapping = mappings[note_measures[id(n)]]
        mapping[voice.text] = mapping[old_voice]
        n.set('id', f'{PREFIX}{index}')
        n.attrib.pop('default-y', None)
        moved += 1
    if moved:
        _split_mixed_chords(tree)
        root = tree.getroot()
        identification = root.find('identification')
        if identification is None:
            identification = ET.Element('identification')
            index = next((i for i, el in enumerate(root) if el.tag in ('defaults', 'part-list', 'part')), 0)
            root.insert(index, identification)
        miscellaneous = identification.find('miscellaneous')
        if miscellaneous is None:
            miscellaneous = ET.SubElement(identification, 'miscellaneous')
        ET.SubElement(miscellaneous, 'miscellaneous-field', name=VOICE_META).text = json.dumps(mappings, separators=(',', ':'))
        tree.write(path, encoding='utf-8', xml_declaration=True)
    return moved
