"""Piano MIDI export with separate score/performance timing and full validation."""

import hashlib
import math
import shutil
import subprocess
from collections import Counter
from dataclasses import replace
from pathlib import Path

import mido

from .model import piano_hand
from .timing import local_tempo, tempo_map

PPQ = 960


def expression_map(arrangement, profile):
    # Include fractional phrase ends so a ritardando never spills into the next phrase.
    points = sorted(
        {
            0.0,
            *(t for t, _ in tempo_map(arrangement)),
            *range(math.ceil(arrangement.length)),
            *(p for p in arrangement.phrases if p < arrangement.length),
            *(p for p in arrangement.fermatas if p < arrangement.length),
        }
    )
    values, previous = [], None
    for beat in points:
        end = next((p for p in arrangement.phrases if p > beat), arrangement.length)
        # Phrase endings breathe only at an annotated fermata. The coda has
        # its own gradual ritardando instead of the same slowdown every phrase.
        factor = 1.0
        if end in arrangement.fermatas:
            factor -= 0.12 * max(0, 1 - (end - beat) / 3)
        if any(
            s["name"] == "Naspel" and s["start"] <= beat < s["end"]
            for s in arrangement.sections
        ):
            factor -= 0.4 * max(0, 1 - (arrangement.length - beat) / 8)
        if any(beat < f <= beat + 1 for f in arrangement.fermatas):
            factor *= 0.72
        bpm = local_tempo(arrangement, beat) * factor
        encoded = mido.bpm2tempo(bpm)
        if encoded != previous:
            values.append((beat, bpm))
            previous = encoded
    return values


def key_signature(tonic, mode):
    from music21 import key

    from .notation import notation_key

    k = notation_key(tonic, mode)
    if mode in ("major", "minor"):
        return k.tonic.name.replace("-", "b") + ("m" if mode == "minor" else "")
    # MIDI has only major/minor key names. The relative major preserves the
    # signature of a modal piece. MusicXML retains its actual tonic and mode.
    return key.KeySignature(k.sharps).asKey("major").tonic.name.replace("-", "b")


def rendered_notes(arrangement, profile, expressive=False):
    result = []
    expression = profile.get("expression", {})
    velocity = expression.get("velocity", 70)
    spread = min(14, max(4, expression.get("velocity_spread", 10)))
    delay = expression.get("onset_spread_seconds", 0.01)
    for n in arrangement.notes:
        start, end, vel = n.start, n.end, n.velocity
        if expressive:
            phrase_end = next(
                (p for p in arrangement.phrases if p > n.start), arrangement.length
            )
            phrase_start = max([0] + [p for p in arrangement.phrases if p <= n.start])
            phase = (n.start - phrase_start) / max(1, phrase_end - phrase_start)
            accent = 3 if abs(n.start - round(n.start)) < 0.01 else 0
            role_offset = {
                "melody": 7,
                "motif": 4,
                "bass": -5,
                "inner": -12,
                "tenor": -10,
                "alto": -8,
            }[n.role]
            learned = expression.get("phrase_velocity_envelope")
            envelope = (
                learned[min(3, int(phase * 4))]
                if learned
                else spread * 0.4 * math.sin(math.pi * phase)
            )
            vel = round(velocity + role_offset + envelope + accent)
            section = next(
                (s for s in arrangement.sections if s["start"] <= n.start < s["end"]),
                None,
            )
            if section and section["name"] != "Harmonisatie":
                progress = (n.start - section["start"]) / max(
                    1, section["end"] - section["start"]
                )
                vel += (
                    round(-5 + 7 * math.sin(math.pi * progress))
                    if section["name"] == "Voorspel"
                    else round(2 - 16 * progress)
                )
            if n.role in ("bass", "inner", "tenor", "alto"):
                start += (
                    delay
                    * local_tempo(arrangement, n.start)
                    / 60
                    * (0.3 if n.role == "bass" else 0.7)
                )
                start = min(start, end - min(0.01, n.duration / 4))
                end -= min(0.08, n.duration * 0.05)
        on = round(start * PPQ)
        off = max(on + 1, round(end * PPQ))
        result.append(
            (
                n.pitch,
                on,
                off,
                max(1, min(127, vel)),
                piano_hand(n, arrangement),
            )
        )
    return result


def save_midi(arrangement, path, profile, expressive=False):
    midi = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    final_tick = round(arrangement.length * PPQ)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    meta = [
        (0, mido.MetaMessage("track_name", name="Vorm en tempo")),
        (
            0,
            mido.MetaMessage(
                "key_signature",
                key=key_signature(
                    getattr(arrangement, "tonic", 0),
                    getattr(arrangement, "mode", "major"),
                ),
            ),
        ),
    ]
    previous_meter = None
    for t, num, den in arrangement.meters:
        if (num, den) != previous_meter:
            meta.append(
                (
                    round(t * PPQ),
                    mido.MetaMessage("time_signature", numerator=num, denominator=den),
                )
            )
            previous_meter = num, den
    for s in arrangement.sections:
        meta.append(
            (round(s["start"] * PPQ), mido.MetaMessage("marker", text=s["name"]))
        )
    tempos = (
        expression_map(arrangement, profile) if expressive else tempo_map(arrangement)
    )
    for t, bpm in tempos:
        meta.append(
            (round(t * PPQ), mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
        )
    fill_track(conductor, meta, final_tick)
    notes = rendered_notes(arrangement, profile, expressive)
    for hand in ("RH", "LH"):
        track = mido.MidiTrack()
        midi.tracks.append(track)
        events = [(0, mido.MetaMessage("track_name", name="Piano " + hand))]
        if hand == "RH":
            events.append((0, mido.Message("program_change", program=0, channel=0)))
        for pitch, on, off, velocity, note_hand in notes:
            if hand == note_hand:
                events.extend(
                    [
                        (
                            on,
                            mido.Message(
                                "note_on", channel=0, note=pitch, velocity=velocity
                            ),
                        ),
                        (
                            off,
                            mido.Message("note_off", channel=0, note=pitch, velocity=0),
                        ),
                    ]
                )
        if hand == "LH":
            events.append(
                (0, mido.Message("control_change", control=64, value=0, channel=0))
            )
            if expressive:
                fraction = max(
                    0.15,
                    min(0.9, profile.get("expression", {}).get("pedal_fraction", 0.75)),
                )
                pedal_spans = []
                for h in arrangement.harmony:
                    if (
                        pedal_spans
                        and (h.root, h.quality, h.bass)
                        == (
                            pedal_spans[-1].root,
                            pedal_spans[-1].quality,
                            pedal_spans[-1].bass,
                        )
                        and abs(h.start - pedal_spans[-1].end) < 1e-6
                    ):
                        pedal_spans[-1] = replace(pedal_spans[-1], end=h.end)
                    else:
                        pedal_spans.append(h)
                for h in pedal_spans:
                    start, end = h.start + 0.06, h.start + (h.end - h.start) * fraction
                    if end > start:
                        events.extend(
                            [
                                (
                                    round(start * PPQ),
                                    mido.Message(
                                        "control_change",
                                        control=64,
                                        value=90,
                                        channel=0,
                                    ),
                                ),
                                (
                                    round(end * PPQ),
                                    mido.Message(
                                        "control_change", control=64, value=0, channel=0
                                    ),
                                ),
                            ]
                        )
            events.append(
                (
                    final_tick,
                    mido.Message("control_change", control=64, value=0, channel=0),
                )
            )
        fill_track(track, events, final_tick)
    midi.save(path)


def fill_track(track, events, end):
    tick = 0
    for t, message in sorted(
        events, key=lambda pair: (pair[0], 0 if pair[1].type == "note_off" else 1)
    ):
        if not 0 <= t <= end:
            raise ValueError("MIDI-event valt buiten de duur van het arrangement.")
        track.append(message.copy(time=t - tick))
        tick = t
    track.append(mido.MetaMessage("end_of_track", time=end - tick))


def validate_export(path, arrangement, expressive=False, profile=None):
    midi = mido.MidiFile(path)
    if midi.ticks_per_beat != PPQ or midi.type != 1:
        raise ValueError("Onverwacht MIDI-formaat of tijdresolutie.")
    events = []
    final_tick = round(arrangement.length * PPQ)
    for track in midi.tracks:
        tick = 0
        for message in track:
            if message.time < 0:
                raise ValueError("Negatieve MIDI-deltatijd.")
            tick += message.time
            if tick > final_tick:
                raise ValueError("MIDI-event na het einde van het arrangement.")
            events.append((tick, message))
    active, pedal, actual = {}, {}, []
    for tick, message in sorted(
        events,
        key=lambda pair: (
            pair[0],
            0
            if pair[1].type == "note_off"
            or (pair[1].type == "note_on" and pair[1].velocity == 0)
            else 1,
        ),
    ):
        if message.type == "note_on" and message.velocity:
            k = message.channel, message.note
            if k in active:
                raise ValueError(
                    "Dubbele of overlappende MIDI-aanslag op hetzelfde kanaal."
                )
            active[k] = tick, message.velocity
        elif message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        ):
            k = message.channel, message.note
            if k not in active:
                raise ValueError("note_off zonder aanslag in export.")
            start, velocity = active.pop(k)
            if tick <= start:
                raise ValueError("Noot zonder positieve duur.")
            actual.append((message.note, start, tick, velocity, message.channel))
        elif message.type == "control_change" and message.control == 64:
            pedal[message.channel] = message.value
    if active:
        raise ValueError("Noten zonder note_off in export.")
    if not pedal or any(value >= 64 for value in pedal.values()):
        raise ValueError("Pedaal niet op ieder gebruikt kanaal afgesloten.")
    expected = Counter(
        (p, on, off, v, 0)
        for p, on, off, v, _ in rendered_notes(arrangement, profile or {}, expressive)
    )
    if Counter(actual) != expected:
        raise ValueError(
            "Geëxporteerde noten, timing, aanslag of kanalen wijken af van het arrangement."
        )
    actual_tempos = sorted((t, m.tempo) for t, m in events if m.type == "set_tempo")
    intended_tempos = (
        expression_map(arrangement, profile or {})
        if expressive
        else tempo_map(arrangement)
    )
    expected_tempos = [
        (round(t * PPQ), mido.bpm2tempo(bpm)) for t, bpm in intended_tempos
    ]
    if actual_tempos != expected_tempos:
        raise ValueError("Tempoverloop wijkt af of bevat dubbele tempo-events.")
    signatures = [m.key for t, m in events if m.type == "key_signature"]
    if signatures != [
        key_signature(
            getattr(arrangement, "tonic", 0), getattr(arrangement, "mode", "major")
        )
    ]:
        raise ValueError("Toonsoortmetadata ontbreekt of wijkt af.")
    melody_expected = Counter(
        (n.pitch, round(n.start * PPQ), round(n.end * PPQ))
        for n in arrangement.notes
        if n.role == "melody"
    )
    melody_actual = Counter((p, on, off) for p, on, off, v, channel in actual)
    if melody_expected - melody_actual:
        raise ValueError("Geëxporteerde melodie wijkt af van de invoer.")
    return {
        "melody_exact_after_export": True,
        "all_notes_exact_after_export": True,
        "no_dangling_notes": True,
        "pedal_released_per_channel": True,
        "pedal_released": True,
        "ticks_per_beat": midi.ticks_per_beat,
        "note_count": len(actual),
        "tempo_events": sum(m.type == "set_tempo" for t, m in events),
    }


def render(midi, target, soundfont):
    exe = shutil.which("fluidsynth")
    if not exe:
        raise RuntimeError(
            "fluidsynth ontbreekt. Installeer lokaal of render de MIDI in je pianoprogramma."
        )
    soundfont = Path(soundfont)
    if not soundfont.is_file():
        raise ValueError("SoundFont bestaat niet.")
    subprocess.run(
        [
            exe,
            "-ni",
            "-g",
            ".5",
            "-r",
            "44100",
            "-F",
            str(target),
            str(soundfont),
            str(midi),
        ],
        check=True,
        capture_output=True,
    )
    return {
        "renderer": "fluidsynth",
        "soundfont_sha256": hashlib.sha256(soundfont.read_bytes()).hexdigest(),
        "sample_rate": 44100,
    }
