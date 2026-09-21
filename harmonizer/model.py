"""Score-time representation. All positions and durations use quarter-note beats."""

import json
import math
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path

MODES = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "ionian": (0, 2, 4, 5, 7, 9, 11),
}


@dataclass(frozen=True)
class Event:
    pitch: int
    start: float
    duration: float
    velocity: int = 72
    role: str = "melody"

    @property
    def end(self):
        return self.start + self.duration


@dataclass
class Melody:
    notes: list[Event]
    length: float
    meters: list[tuple[float, int, int]]
    phrases: list[float]
    tonic: int
    mode: str
    bpm: float = 80.0
    fermatas: list[float] = field(default_factory=list)
    title: str = "Melodie"

    def validate(self):
        if not self.notes:
            raise ValueError("De melodie bevat geen noten.")
        if self.mode not in MODES or not 0 <= self.tonic <= 11:
            raise ValueError("Ongeldige toonsoort of modus.")
        if not math.isfinite(self.bpm) or not 20 <= self.bpm <= 240:
            raise ValueError(
                "Tempo moet tussen 20 en 240 kwartnoten per minuut liggen."
            )
        if not math.isfinite(self.length) or self.length <= 0:
            raise ValueError("Ongeldige melodielengte.")
        previous = 0.0
        for n in self.notes:
            if not all(math.isfinite(v) for v in (n.start, n.duration)):
                raise ValueError("Niet-eindige noottijd.")
            if (
                not isinstance(n.pitch, int)
                or not 21 <= n.pitch <= 108
                or n.duration <= 0
                or n.start < previous - 1e-6
            ):
                raise ValueError(
                    "De melodie moet eenstemmig zijn, met geldige pianonoten en tijden."
                )
            previous = n.end
        if self.length < previous - 1e-6:
            raise ValueError("Melodielengte eindigt vóór de laatste noot.")
        if not self.phrases or abs(self.phrases[-1] - self.length) > 1e-6:
            raise ValueError(
                "De laatste frasegrens moet gelijk zijn aan de melodielengte."
            )
        if any(not math.isfinite(x) or x <= 0 or x > self.length for x in self.phrases):
            raise ValueError("Ongeldige frasegrens.")
        if any(b <= a for a, b in zip(self.phrases, self.phrases[1:])):
            raise ValueError("Frasegrenzen moeten strikt oplopen.")
        if any(
            n.start < b - 1e-6 and n.end > b + 1e-6
            for b in self.phrases
            for n in self.notes
        ):
            raise ValueError("Een frasegrens doorsnijdt een melodienoot.")
        if not self.meters or self.meters[0][0] != 0:
            raise ValueError("Maatsoort op positie 0 ontbreekt.")
        for i, (t, num, den) in enumerate(self.meters):
            if (
                not math.isfinite(t)
                or t < 0
                or t >= self.length
                or num < 1
                or den not in (1, 2, 4, 8, 16, 32)
            ):
                raise ValueError("Ongeldige maatsoort.")
            if i and t <= self.meters[i - 1][0]:
                raise ValueError("Maatsoortwissels moeten strikt oplopen.")

    def save(self, path):
        write_json(path, asdict(self))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement avoids incomplete caches/checkpoints after interruption.
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    temp.replace(path)


def piano_hand(event, arrangement):
    """Put a low inner note with the bass only within an octave hand span.

    This changes staff placement, never musical role, pitch or timing.
    """
    if event.role in ("bass", "tenor"):
        return "LH"
    if event.role == "inner" and event.pitch < 60:
        basses = [
            n
            for n in arrangement.notes
            if n.role == "bass" and n.start < event.end and n.end > event.start
        ]
        if basses and all(0 <= event.pitch - bass.pitch <= 12 for bass in basses):
            return "LH"
    return "RH"


def satb_coverage(notes, start=0.0, end=None):
    """Check four independent, ordered voices throughout every soprano note."""
    end = max((n.end for n in notes), default=start) if end is None else end
    notes = [n for n in notes if n.start < end and n.end > start]
    boundaries = sorted(
        {
            start,
            end,
            *(max(start, n.start) for n in notes),
            *(min(end, n.end) for n in notes),
        }
    )
    total, complete, failures = 0.0, 0.0, []
    for left, right in pairwise(boundaries):
        time = (left + right) / 2
        active = [n for n in notes if n.start <= time < n.end]
        soprano = [n for n in active if n.role in ("melody", "motif")]
        if not soprano:
            continue
        total += right - left
        lanes = [
            [n for n in active if n.role == role] for role in ("bass", "tenor", "alto")
        ] + [soprano]
        valid = all(len(lane) == 1 for lane in lanes) and len(active) == 4
        if valid:
            pitches = [lane[0].pitch for lane in lanes]
            valid = pitches == sorted(set(pitches))
        if valid:
            complete += right - left
        else:
            failures.append(
                {
                    "start": left,
                    "end": right,
                    "voices": [n.role for n in active],
                    "pitches": [n.pitch for n in active],
                }
            )
    return {
        "soprano_beats": total,
        "four_voice_beats": complete,
        "four_voice_fraction": complete / total if total else 0,
        "valid": bool(total) and not failures,
        "violations": failures[:20],
    }


def load_melody(path, config):
    from music21 import chord, converter, key, meter, note, tempo

    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text())
        raw["notes"] = [Event(**n) for n in raw["notes"]]
        result = Melody(**raw)
    elif path.suffix.lower() in (".mid", ".midi"):
        import mido

        midi = mido.MidiFile(path)
        if midi.type == 2:
            raise ValueError("Asynchrone MIDI type 2 wordt niet ondersteund.")
        musical = [
            i
            for i, tr in enumerate(midi.tracks)
            if any(m.type == "note_on" and m.velocity for m in tr)
        ]
        index = config.get("melody_track")
        if index is None:
            if len(musical) != 1:
                raise ValueError(
                    f"Kies melody_track uit {musical} voor meerstemmige MIDI."
                )
            index = musical[0]
        if index not in musical:
            raise ValueError("melody_track bevat geen noten.")
        notes, active, signatures, bpms = [], {}, {}, []
        for ti, track in enumerate(midi.tracks):
            tick = 0
            for m in track:
                tick += m.time
                t = tick / midi.ticks_per_beat
                if m.type == "time_signature":
                    signatures[t] = (t, m.numerator, m.denominator)
                if m.type == "set_tempo":
                    bpms.append((t, mido.tempo2bpm(m.tempo)))
                if ti != index:
                    continue
                if m.type == "note_on" and m.velocity:
                    k = (m.channel, m.note)
                    if k in active:
                        raise ValueError(
                            "Overlappende aanslagen van dezelfde MIDI-noot."
                        )
                    active[k] = (t, m.velocity)
                elif m.type == "note_off" or (m.type == "note_on" and not m.velocity):
                    k = (m.channel, m.note)
                    if k in active:
                        start, vel = active.pop(k)
                        notes.append(Event(m.note, start, t - start, vel))
        if active:
            raise ValueError("MIDI bevat noten zonder note_off.")
        if "phrases" not in config or "key" not in config:
            raise ValueError(
                "MIDI vereist expliciete key en phrases in de configuratie."
            )
        notes.sort(key=lambda n: n.start)
        length = float(config.get("length", max((n.end for n in notes), default=0)))
        result = Melody(
            notes,
            length,
            sorted(signatures.values()),
            config["phrases"],
            0,
            "major",
            min(bpms)[1] if bpms else 80,
            title=path.stem,
        )
    else:
        score = converter.parse(path)
        parts = list(score.parts) or [score]
        index = config.get("melody_part")
        if index is None and len(parts) != 1:
            raise ValueError("Kies melody_part bij een MusicXML met meerdere partijen.")
        part = parts[index or 0].expandRepeats().stripTies()
        notes, fermatas, phrase_marks = [], [], []
        flat = part.flatten()
        for n in flat.notes:
            if isinstance(n, chord.Chord):
                raise ValueError(  # noqa: TRY004 -- invalid musical input, not a Python API type error
                    "De gekozen melodiepartij bevat akkoorden. Lever een eenstemmige partij aan."
                )
            if isinstance(n, note.Note) and not n.duration.isGrace:
                start, duration = float(n.offset), float(n.quarterLength)
                notes.append(Event(n.pitch.midi, start, duration))
                if any(e.__class__.__name__ == "Fermata" for e in n.expressions):
                    fermatas.append(start + duration)
                    phrase_marks.append(start + duration)
        signatures = [
            (float(m.offset), m.numerator, m.denominator)
            for m in flat.getElementsByClass(meter.TimeSignature)
        ]
        keys = list(flat.getElementsByClass(key.Key))
        if not keys and "key" not in config:
            raise ValueError(
                "Geef key expliciet op, inclusief modus, bijvoorbeeld 'C dorian'."
            )
        k = keys[0] if keys else key.Key("C")
        tempos = list(flat.getElementsByClass(tempo.MetronomeMark))
        length = float(flat.highestTime)
        if "phrases" not in config and not phrase_marks:
            raise ValueError(
                "Frasegrenzen ontbreken. Geef phrases op in kwartnoottellen."
            )
        result = Melody(
            sorted(notes, key=lambda n: n.start),
            length,
            signatures,
            sorted(set(phrase_marks + [length])),
            k.tonic.pitchClass,
            k.mode,
            (tempos[0].getQuarterBPM() or 80) if tempos else 80,
            fermatas,
            path.stem,
        )
    if "key" in config:
        k = key.Key(*config["key"].split())
        result.tonic, result.mode = k.tonic.pitchClass, k.mode
    if "tempo" in config:
        result.bpm = float(config["tempo"])
    if "phrases" in config:
        result.phrases = [float(x) for x in config["phrases"]]
    if "meters" in config:
        result.meters = [tuple(x) for x in config["meters"]]
    result.validate()
    return result
