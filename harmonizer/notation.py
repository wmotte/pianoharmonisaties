"""Structural piano notation, independent of expressive MIDI performance timing."""

import math
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from music21 import (
    bar,
    chord,
    clef,
    converter,
    duration,
    expressions,
    instrument,
    key,
    layout,
    metadata,
    meter,
    note,
    pitch,
    stream,
    tempo,
    tie,
)

from .model import piano_hand
from .timing import tempo_map

_EPS = 1e-6


def notation_key(tonic, mode):
    mode = {"aeolian": "minor", "ionian": "major"}.get(mode, mode)
    candidates = []
    for name in (
        "C",
        "C#",
        "D-",
        "D",
        "D#",
        "E-",
        "E",
        "F",
        "F#",
        "G-",
        "G",
        "G#",
        "A-",
        "A",
        "A#",
        "B-",
        "B",
        "C-",
    ):
        if pitch.Pitch(name).pitchClass == tonic:
            candidate = key.Key(name, mode)
            candidates.append(candidate)
    return min(candidates, key=lambda k: abs(k.sharps))


def _spelling(midi, signature):
    candidates = [pitch.Pitch(midi)]
    candidates.extend(candidates[0].getAllCommonEnharmonics())
    scale = {p.pitchClass: p.name for p in signature.pitches}
    return min(
        candidates,
        key=lambda p: (
            p.name != scale.get(midi % 12),
            abs(p.accidental.alter) if p.accidental else 0,
            (p.accidental.alter if p.accidental else 0)
            * (-1 if signature.sharps >= 0 else 1),
        ),
    )


def _lanes(events):
    """Keep equal spans as chords and independent overlapping spans in voices."""
    groups = defaultdict(list)
    for n in events:
        groups[(n.start, n.end)].append(n.pitch)
    lanes = []
    for (start, end), pitches in sorted(groups.items()):
        target = next((lane for lane in lanes if lane[-1][1] <= start + _EPS), None)
        if target is None:
            target = []
            lanes.append(target)
        target.append((start, end, pitches))
    return lanes


def revoice_source_score(source):
    """Return a source copy with nonoverlapping notation voices per measure.

    Preserve notes, ties, staff assignment and local metadata. This repairs
    overlapping events stored in one MusicXML voice, not transcription errors
    or inferred melody identity. Consumers must still verify their exporter.
    """
    before = Counter(_sounding(source))
    score = deepcopy(source)
    for part in score.parts:
        for measure in part.getElementsByClass(stream.Measure):
            items = sorted(
                (
                    (float(n.getOffsetInHierarchy(measure)), deepcopy(n))
                    for n in measure.recurse().notes
                ),
                key=lambda row: (row[0], -float(row[1].quarterLength)),
            )
            lanes = []
            length = float(measure.barDuration.quarterLength)
            for onset, element in items:
                if onset < 0 or onset + float(element.quarterLength) > length + _EPS:
                    raise ValueError("Source note extends outside its notated measure.")
                lane = next(
                    (
                        lane
                        for lane in lanes
                        if lane[-1][0] + float(lane[-1][1].quarterLength)
                        <= onset + _EPS
                    ),
                    None,
                )
                if lane is None:
                    lane = []
                    lanes.append(lane)
                lane.append((onset, element))
            # Metadata inside old voices must survive at its measure offset.
            metadata_items = [
                (float(e.getOffsetInHierarchy(measure)), deepcopy(e))
                for voice in measure.getElementsByClass(stream.Voice)
                for e in voice
                if not isinstance(e, (note.GeneralNote, stream.Stream))
            ]
            for element in list(measure):
                if isinstance(element, (stream.Voice, note.GeneralNote)):
                    measure.remove(element)
            for onset, element in metadata_items:
                measure.insert(onset, element)
            for index, lane in enumerate(lanes or [[]], 1):
                voice = stream.Voice(id=index)
                cursor = 0.0
                for onset, element in lane:
                    if onset > cursor + _EPS:
                        voice.insert(cursor, note.Rest(quarterLength=onset - cursor))
                    voice.insert(onset, element)
                    cursor = onset + float(element.quarterLength)
                if cursor < length - _EPS:
                    voice.insert(cursor, note.Rest(quarterLength=length - cursor))
                measure.insert(0, voice)
    if Counter(_sounding(score)) != before:
        raise ValueError("Reassigning source voices changed sounding events.")
    return score


def _accidentals(measure, signature):
    """Share accidental state across voices, independently for each staff/bar.

    Tied continuations need no new sign and do not establish an accidental
    for a subsequent untied attack in the new bar.
    """
    defaults = {p.step: p.accidental.alter for p in signature.alteredPitches}
    state = {}
    attacks = defaultdict(list)
    for element in measure.recurse().notes:
        members = list(element) if isinstance(element, chord.Chord) else [element]
        attacks[element.getOffsetInHierarchy(measure)].extend(members)
    for _, members in sorted(attacks.items()):
        changes = defaultdict(set)
        for member in members:
            if member.tie and member.tie.type in ("stop", "continue"):
                continue
            p = member.pitch
            changes[(p.step, p.octave)].add(p.accidental.alter if p.accidental else 0)
        for member in members:
            p = member.pitch
            position = (p.step, p.octave)
            alteration = p.accidental.alter if p.accidental else 0
            previous = state.get(position, defaults.get(p.step, 0))
            tied = member.tie and member.tie.type in ("stop", "continue")
            if p.accidental is None:
                p.accidental = pitch.Accidental(0)
            p.accidental.displayStatus = bool(
                not tied and (alteration != previous or len(changes[position]) > 1)
            )
        for position, alterations in changes.items():
            # An altered unison requires clarification at the next attack.
            state[position] = next(iter(alterations)) if len(alterations) == 1 else None


def _bars(arrangement):
    meters = sorted(arrangement.meters) or [(0, 4, 4)]
    if meters[0][0] != 0:
        raise ValueError("De eerste maatsoort moet op tel nul beginnen.")
    boundaries = sorted(
        {
            0.0,
            arrangement.length,
            *(s["start"] for s in arrangement.sections),
            *(s["end"] for s in arrangement.sections),
            *(m[0] for m in meters),
            *(t for t, _ in tempo_map(arrangement)),
        }
    )
    result = []
    for start, end in pairwise(boundaries):
        current = next(m for m in reversed(meters) if m[0] <= start + _EPS)
        length = current[1] * 4 / current[2]
        while start < end - _EPS:
            stop = min(end, start + length)
            result.append((start, stop, current[1], current[2]))
            start = stop
    return result


def _sounding(score, melody_only=False):
    result = []

    def sounding_copy(element):
        copied = deepcopy(element)
        # music21 compares an explicit natural differently from no accidental
        # when matching tied single notes. MuseScore legitimately omits alter=0
        # after the barline. Normalize only this enharmonically identical case.
        for p in copied.pitches:
            if p.accidental and p.accidental.alter == 0:
                p.accidental = None
        return copied

    # music21's score-wide stripTies can conflate unisons in different voices.
    # Rebuild each voice across measures before resolving its ties.
    for part in list(score.parts)[:1] if melody_only else score.parts:
        voices = defaultdict(stream.Stream)
        for measure in part.getElementsByClass(stream.Measure):
            for voice in list(measure.voices)[:1] if melody_only else measure.voices:
                for element in voice.notes:
                    voices[str(voice.id)].insert(
                        element.getOffsetInHierarchy(part), sounding_copy(element)
                    )
            if not measure.voices:
                for element in measure.notes:
                    voices["1"].insert(
                        element.getOffsetInHierarchy(part), sounding_copy(element)
                    )
        for voice in voices.values():
            untied = voice.stripTies(inPlace=False, matchByPitch=True)
            for element in untied.notes:
                start = float(element.offset)
                end = start + float(element.quarterLength)
                for p in element.pitches:
                    result.append((int(p.midi), start, end))
    return sorted(result)


def _rests(voice, offset, length, measure_length):
    # A non-measure whole rest in 3/2 is expanded by music21 on import.
    # Write half rests instead, retaining the actual duration and metre.
    if abs(offset) < _EPS and abs(length - measure_length) < _EPS:
        rest = note.Rest(quarterLength=length)
        rest.fullMeasure = True
        voice.insert(offset, rest)
        return
    while length > _EPS:
        duration = min(2, length)
        rest = note.Rest(quarterLength=duration)
        rest.fullMeasure = False
        voice.insert(offset, rest)
        offset += duration
        length -= duration


def _regularize_triplets(measure):
    """Write explicit one-beat triplet groups, splitting unusual tied values.

    Inferred 6:5 durations and open bracket groups can make MuseScore shift the
    following bars. A complete local 3:2 group preserves the same sounding time.
    """
    for voice in measure.voices:
        elements = list(voice.notesAndRests)
        affected = set()
        for element in elements:
            start = Fraction(float(element.offset)).limit_denominator(96)
            end = start + Fraction(float(element.quarterLength)).limit_denominator(96)
            for point in (start, end):
                if point.denominator % 3 == 0:
                    affected.add(math.floor(point))
        if not affected:
            continue
        rebuilt = []
        groups = defaultdict(list)
        for element in elements:
            start = Fraction(float(element.offset)).limit_denominator(96)
            end = start + Fraction(float(element.quarterLength)).limit_denominator(96)
            cuts = sorted(
                {
                    start,
                    end,
                    *(
                        Fraction(x)
                        for b in affected
                        for x in (b, b + 1)
                        if start < x < end
                    ),
                }
            )
            pieces = []
            for a, b in pairwise(cuts):
                triplet = math.floor(a) in affected
                written = duration.Duration(
                    (b - a) * Fraction(3, 2) if triplet else b - a
                )
                cursor = a
                for component in written.components:
                    d = duration.Duration(component)
                    if triplet:
                        d.appendTuplet(duration.Tuplet(3, 2, "eighth"))
                    piece = deepcopy(element)
                    piece.duration = d
                    if isinstance(piece, note.Rest):
                        piece.fullMeasure = False
                    pieces.append((cursor, piece))
                    if triplet:
                        groups[math.floor(a)].append(piece)
                    cursor += Fraction(float(d.quarterLength)).limit_denominator(96)
            original_tie = element.tie.type if element.tie else None
            for i, (a, piece) in enumerate(pieces):
                if not isinstance(piece, note.Rest):
                    before = i > 0 or original_tie in ("stop", "continue")
                    after = i < len(pieces) - 1 or original_tie in ("start", "continue")
                    piece.tie = (
                        tie.Tie(
                            "continue"
                            if before and after
                            else "stop"
                            if before
                            else "start"
                        )
                        if before or after
                        else None
                    )
                    if i < len(pieces) - 1:
                        piece.expressions = [
                            x
                            for x in piece.expressions
                            if not isinstance(x, expressions.Fermata)
                        ]
                rebuilt.append((a, piece))
        for pieces in groups.values():
            for i, piece in enumerate(pieces):
                t = piece.duration.tuplets[0]
                t.type = (
                    "startStop"
                    if len(pieces) == 1
                    else "start"
                    if i == 0
                    else "stop"
                    if i == len(pieces) - 1
                    else None
                )
        for element in elements:
            voice.remove(element)
        for a, piece in rebuilt:
            voice.insert(a, piece)


def save_musicxml(
    arrangement, path, tonic=0, mode="major", title="Pianoarrangement", *, hands=None
):
    """Write a grand staff and check every sounding note through a MusicXML roundtrip.

    Voices preserve structural durations exactly. This does not infer fingerings,
    redistribute inner notes between hands or claim editorially finished engraving.
    """
    signature = notation_key(tonic, mode)
    score = stream.Score()
    score.metadata = metadata.Metadata(title=title, composer="")
    staffs = [stream.PartStaff(id="right"), stream.PartStaff(id="left")]
    if hands is not None:
        from .chorale_hand_plan import validate_hands

        validate_hands(arrangement.notes, hands)
    hand_by_id = {id(n): h for n, h in zip(arrangement.notes, hands or [])}

    def hand(n):
        return hand_by_id[id(n)] if hands is not None else piano_hand(n, arrangement)

    top = [n for n in arrangement.notes if n.role in ("melody", "motif")]
    inner = [
        n
        for n in arrangement.notes
        if n.role in ("inner", "alto", "bass", "tenor") and hand(n) == "RH"
    ]
    bass = [n for n in arrangement.notes if hand(n) == "LH"]
    if len(top) + len(inner) + len(bass) != len(arrangement.notes):
        raise ValueError("Onbekende nootrol voor pianonotatie.")
    if len(_lanes(top)) > 1:
        raise ValueError(
            "Melodie en motief moeten samen een eenstemmige bovenstem vormen."
        )
    explicit_satb = hands is None and any(
        n.role in ("tenor", "alto") for n in arrangement.notes
    )
    if explicit_satb:
        tenor = [n for n in arrangement.notes if n.role == "tenor"]
        bass_line = [n for n in arrangement.notes if n.role == "bass"]
        lanes = [
            (_lanes(top) or [[]]) + (_lanes(inner) or [[]]),
            (_lanes(tenor) or [[]]) + (_lanes(bass_line) or [[]]),
        ]
        if any(len(lane) != 2 for lane in lanes):
            raise ValueError("SATB vereist vier afzonderlijke monofone stemmen.")
    else:
        lanes = [(_lanes(top) or [[]]) + _lanes(inner), _lanes(bass) or [[]]]
    bars = _bars(arrangement)
    for staff_index, staff in enumerate(staffs):
        staff.partName = "Piano"
        staff.insert(0, instrument.Piano())
        previous_meter = None
        for number, (start, end, num, den) in enumerate(bars, 1):
            measure = stream.Measure(number=number)
            if previous_meter != (num, den):
                measure.insert(0, meter.TimeSignature(f"{num}/{den}"))
                previous_meter = (num, den)
            measure.paddingRight = num * 4 / den - (end - start)
            if measure.paddingRight > _EPS:
                measure.showNumber = stream.enums.ShowNumber.NEVER
            if number == 1:
                measure.insert(
                    0, clef.TrebleClef() if staff_index == 0 else clef.BassClef()
                )
                measure.insert(0, deepcopy(signature))
            if staff_index == 0:
                for position, bpm in tempo_map(arrangement):
                    if start <= position < end:
                        measure.insert(
                            position - start, tempo.MetronomeMark(number=bpm)
                        )
                for section in arrangement.sections:
                    if abs(section["start"] - start) < _EPS:
                        measure.insert(0, expressions.TextExpression(section["name"]))
            for voice_index, lane in enumerate(lanes[staff_index], 1):
                voice = stream.Voice(id=voice_index)
                cursor = start
                for onset, offset, pitches in lane:
                    a, b = max(onset, start), min(offset, end)
                    if b <= a + _EPS:
                        continue
                    if a > cursor + _EPS:
                        _rests(voice, cursor - start, a - cursor, num * 4 / den)
                    spelled = [_spelling(p, signature) for p in pitches]
                    element = (
                        note.Note(spelled[0])
                        if len(spelled) == 1
                        else chord.Chord(spelled)
                    )
                    element.quarterLength = b - a
                    before, after = onset < start - _EPS, offset > end + _EPS
                    if before or after:
                        element.tie = tie.Tie(
                            "continue"
                            if before and after
                            else "stop"
                            if before
                            else "start"
                        )
                    if (
                        staff_index == 0
                        and voice_index == 1
                        and not after
                        and any(
                            abs(offset - fermata) < _EPS
                            for fermata in arrangement.fermatas
                        )
                    ):
                        fermata_mark = expressions.Fermata()
                        fermata_mark.type = "upright"
                        element.expressions.append(fermata_mark)
                    if staff_index == 0 or explicit_satb:
                        element.stemDirection = "up" if voice_index == 1 else "down"
                    voice.insert(a - start, element)
                    cursor = b
                if cursor < end - _EPS:
                    _rests(voice, cursor - start, end - cursor, num * 4 / den)
                # Keep the same voice count in every measure: music21 offsets
                # LH voice IDs by the number of RH voices when joining staves.
                # Omitting empty voices changes tie identities in MuseScore.
                other_notes = any(
                    max(a, start) < min(b, end)
                    for other_lane in lanes[staff_index]
                    for a, b, _ in other_lane
                )
                if not voice.notes and (voice_index > 1 or other_notes):
                    for rest in voice.notesAndRests:
                        rest.style.hideObjectOnPrint = True
                measure.insert(0, voice)
            if any(abs(s["end"] - end) < _EPS for s in arrangement.sections):
                measure.rightBarline = bar.Barline(
                    "final" if end == arrangement.length else "double"
                )
            _regularize_triplets(measure)
            _accidentals(measure, signature)
            staff.insert(start, measure)
        score.insert(0, staff)
    score.insert(0, layout.StaffGroup(staffs, symbol="brace", barTogether=True))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(path))
    parsed = converter.parse(str(path))
    actual = _sounding(parsed)
    expected = sorted((n.pitch, n.start, n.end) for n in arrangement.notes)
    exact = len(actual) == len(expected) and all(
        p == q and abs(a - c) < _EPS and abs(b - d) < _EPS
        for (p, a, b), (q, c, d) in zip(actual, expected)
    )
    if not exact:
        raise ValueError(
            "MusicXML-roundtrip heeft toonhoogten of structurele noottijden veranderd."
        )
    melody_actual = _sounding(parsed, melody_only=True)
    melody_expected = sorted((n.pitch, n.start, n.end) for n in top)
    if len(melody_actual) != len(melody_expected) or any(
        p != q or abs(a - c) >= _EPS or abs(b - d) >= _EPS
        for (p, a, b), (q, c, d) in zip(melody_actual, melody_expected)
    ):
        raise ValueError(
            "De afzonderlijke melodie- en motiefstem is veranderd in MusicXML."
        )
    return {
        "all_notes_exact_after_export": True,
        "melody_voice_exact_after_export": True,
        "notes": len(expected),
        "staves": 2,
        "measures": len(bars),
        "key_signature_sharps": signature.sharps,
        "structural_timing": True,
    }
