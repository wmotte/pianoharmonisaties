"""Maak aparte STUK-varianten met thematische omlijsting en een tegenstem.

Vanuit een liedmap: ../.venv/bin/python ../koele/componeer.py bron/psalm_62.py
    --config tmp/arrangement.json --output tmp/compositie/psalm_62
De opgegeven bron wordt nooit overschreven. Uitvoer blijft in de liedmap.
"""

import argparse
import copy
import json
import pprint
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "koele")]

from music21 import key

import maak_partituren as mp
import zetter
from harmonizer.arrange import compose_variants, export_variants
from harmonizer.counterpoint import CompositionError
from harmonizer.engine import Arrangement, Harmony
from harmonizer.model import Event, Melody, MODES, piano_hand, write_json
from harmonizer.notation import _spelling, notation_key
from harmonizer.profile import identify_chord, QUALITIES


def _events(text, ks, role):
    events, meters, cursor, current = [], [], 0.0, None
    tied = False
    for measure in mp.parse_stem(text, ks):
        if measure["maat"]:
            num, den = map(int, measure["maat"].split("/"))
            meters.append((cursor, num, den))
        for kind, p, duration, mods in measure["elems"]:
            duration = float(duration)
            if kind == "noot":
                step, alteration, octave = p
                midi = (octave + 1) * 12 + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step] + alteration
                if tied and events and events[-1].pitch == midi:
                    events[-1] = replace(events[-1], duration=events[-1].duration + duration)
                else:
                    events.append(Event(midi, cursor, duration, role=role))
                tied = "~" in mods
            else:
                tied = False
            cursor += duration
    return events, meters, cursor


def source_arrangement(stuk):
    """Extract the sung sections; preserve their text and all notated melody events."""
    sections = [s for s in stuk["secties"] if s.get("tekst")]
    if not sections:
        raise ValueError("Geen zangsectie met tekst gevonden.")
    tonic_key = key.Key(sections[0]["toonaard"])
    tonic = tonic_key.tonic.pitchClass
    signature = sections[0]["toonsoort"]
    modes = [m for m in MODES if notation_key(tonic, m).sharps == signature]
    if not modes:
        raise ValueError("Finalis en voortekening bepalen geen ondersteunde modus.")
    mode = sections[0].get("modus", modes[0])
    notes, sung, meters, phrases, lengths, chosen_harmony = [], [], [], [], [], []
    cursor = 0
    for sec in sections:
        if sec["toonsoort"] != signature or sec.get("toonaard") != sections[0].get("toonaard"):
            raise ValueError("Een zangstuk met toonsoortwisselingen vraagt een afzonderlijke compositie per toonsoort.")
        ks = key.KeySignature(signature)
        line, changes, length = _events(sec["melodie"], ks, "melody")
        num, den = map(int, sec["maat"].split("/"))
        meters.append((cursor, num, den))
        meters.extend((t + cursor, n, d) for t, n, d in changes if t > 0)
        sung.extend(replace(n, start=n.start + cursor) for n in line)
        phrases.extend(n.end + cursor for n in line if n.duration >= 4)
        for voice, role in (("2", "alto"), ("3", "tenor"), ("4", "bass")):
            ev, _, _ = _events(sec[voice], ks, role)
            notes.extend(replace(n, start=n.start + cursor) for n in ev)
        if "akkoorden" in sec:
            at, previous = cursor, None
            for measure in zetter.parse_akkoorden(sec["akkoorden"]):
                for symbol, duration in measure:
                    if symbol not in ("R", "="):
                        previous = zetter.Akkoord(symbol)
                    if symbol != "R" and previous:
                        intervals = tuple(sorted((pc - previous.root) % 12 for pc in previous.alle))
                        quality = next((q for q, intervals_q in QUALITIES.items() if tuple(sorted(intervals_q)) == intervals), None)
                        if quality is None:
                            raise ValueError(f"Akkoordtype niet ondersteund voor compositie: {symbol}")
                        chosen_harmony.append((at, at + float(duration), previous.root, quality))
                    at += float(duration)
        cursor += length
        lengths.append(length)
        phrases.append(cursor)
    phrases = sorted(set(phrases))
    bpm = next((s["tempo"] for s in stuk["secties"] if "tempo" in s), 90)
    melody = Melody(sung, cursor, meters, phrases, tonic, mode, bpm, phrases, stuk["titel"])
    melody.validate()
    hs = []
    bounds = sorted({t for n in [*notes, *sung] for t in (n.start, n.end)}
                    | {t for h in chosen_harmony for t in h[:2]})
    for a, b in zip(bounds, bounds[1:]):
        active = sorted(n.pitch for n in [*notes, *sung] if n.start <= a + 1e-7 < n.end)
        if not active:
            continue
        planned = next((h for h in chosen_harmony if h[0] <= a + 1e-7 < h[1]), None)
        chord = planned[2:] if planned else identify_chord(active) or (active[0] % 12, "major")
        bass = min((n.pitch for n in notes if n.role == "bass" and n.start <= a + 1e-7 < n.end), default=active[0])
        inner = tuple(sorted(n.pitch for n in notes if n.role in ("alto", "tenor")
                             and n.start <= a + 1e-7 < n.end))
        hs.append(Harmony(a, b, *chord, bass, inner))
    arrangement = Arrangement(sorted([*sung, *notes], key=lambda n: (n.start, n.pitch)), hs,
                              [{"name": "Harmonisatie", "start": 0, "end": cursor}],
                              meters, phrases, phrases, bpm, 0, 0, 0, cursor, {}, tonic, mode)
    return melody, arrangement, sections, lengths


def _duration(value):
    value = Fraction(value).limit_denominator(96)
    for denominator in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        for dots in range(3):
            for triplet in (False, True):
                if mp.ql(str(denominator), "." * dots, "t" if triplet else "") == value:
                    return f"/{denominator}" + "." * dots + ("t" if triplet else "")
    raise ValueError(f"Niet noteerbare duur in STUK: {value}")


def _duration_parts(value):
    remaining, parts = Fraction(value).limit_denominator(96), []
    # Binary durations must stay binary: 5/2 is a half tied to an eighth.
    # Greedily choosing 7/3 + 1/6 invents incompatible tuplet groups on import.
    binary = (remaining.denominator & (remaining.denominator - 1)) == 0
    values = sorted({mp.ql(str(d), "." * dots, "t" if triplet else "")
                     for d in (1, 2, 4, 8, 16, 32, 64, 128, 256)
                     for dots in range(3) for triplet in ((False,) if binary else (False, True))}, reverse=True)
    while remaining:
        try:
            parts.append(_duration(remaining))
            break
        except ValueError:
            piece = next((v for v in values if v <= remaining), None)
            if piece is None:
                raise ValueError(f"Niet noteerbare restduur: {remaining}")
            parts.append(_duration(piece))
            remaining -= piece
    return parts


def stem_text(events, bars, signature, fermatas=()):
    tokens = []
    previous_meter = None
    for index, (start, end, num, den) in enumerate(bars):
        current = f"{num}/{den}"
        if previous_meter is not None and previous_meter != current:
            tokens.append("M" + current)
        previous_meter = current
        cursor = start
        for n in sorted(events, key=lambda n: n.start):
            a, b = max(start, n.start), min(end, n.end)
            if b <= a + 1e-7:
                continue
            if a < cursor - 1e-7:
                raise ValueError("Twee gelijktijdige noten in één STUK-stem.")
            if a > cursor + 1e-7:
                tokens.extend("R" + d for d in _duration_parts(a - cursor))
            p = _spelling(n.pitch, signature)
            accidental = "n" if not p.accidental else {0: "n", 1: "#", -1: "b", 2: "##", -2: "bb"}[int(p.accidental.alter)]
            parts = _duration_parts(b - a)
            for j, d in enumerate(parts):
                text = p.step + accidental + str(p.octave) + d
                if j < len(parts) - 1 or n.end > end + 1e-7:
                    text += "~"
                if j == len(parts) - 1 and any(abs(b - f) < 1e-7 for f in fermatas):
                    text += "^"
                tokens.append(text)
            cursor = b
        if cursor < end - 1e-7:
            tokens.extend("R" + d for d in _duration_parts(end - cursor))
        tokens.append("|]" if index == len(bars) - 1 else "|")
    return " ".join(tokens)


def akkoord_text(harmonies, bars, signature):
    suffix = {"major": "", "minor": "m", "sus2": "sus2", "sus4": "sus4",
              "dom7": "7", "min7": "m7", "maj7": "maj7", "add9": "add9", "dim": "dim"}
    result = []
    for i, (start, end, num, den) in enumerate(bars):
        cuts = sorted({start, end, *(h.start for h in harmonies if start < h.start < end),
                       *(h.end for h in harmonies if start < h.end < end)})
        cells = []
        for a, b in zip(cuts, cuts[1:]):
            h = next((h for h in harmonies if h.start <= a + 1e-7 < h.end), None)
            if h is None:
                symbol = "R"
            else:
                symbol = _spelling(60 + h.root, signature).name.replace("-", "b") + suffix[h.quality]
            if cells and cells[-1][0] == symbol:
                cells[-1][1] += b - a
            else:
                cells.append([symbol, b - a])
        result.extend(sym + part for sym, dur in cells for part in _duration_parts(dur))
        result.append("|]" if i == len(bars) - 1 else "|")
    return " ".join(result)


def to_stuk(original, arrangement, singing, lengths):
    from harmonizer.notation import _bars

    result = copy.deepcopy(original)
    for k in ("regels", "paginas", "begeleiding", "linkerhand"):
        result.pop(k, None)
    result["bestandsnaam"] = original.get("bestandsnaam", original["titel"]) + " (thematische variant)"
    result["secties"] = []
    signature = notation_key(arrangement.tonic, arrangement.mode)
    profile = arrangement.diagnostics.get("countervoice", {}).get("profile")
    bars = _bars(arrangement)
    for section in arrangement.sections:
        intervals = []
        if section["name"] == "Harmonisatie":
            cursor = section["start"]
            for sec, length in zip(singing, lengths):
                intervals.append((cursor, cursor + length, sec))
                cursor += length
        else:
            intervals = [(section["start"], section["end"], None)]
        for start, end, source in intervals:
            local = [b for b in bars if start <= b[0] < end]
            # Preserve source bar shapes, including short measures and pickups.
            if source:
                _, ts, ls = mp.sectie_maten(original, source, key.KeySignature(source["toonsoort"]))
                local, at = [], start
                for meter, length in zip(ts, ls):
                    num, den = map(int, meter.split("/"))
                    local.append((at, at + float(length), num, den))
                    at += float(length)
            if not local:
                raise ValueError("Geen maten voor compositiesectie.")
            sec = copy.deepcopy(source) if source else {"kop": section["name"], "toonsoort": signature.sharps,
                  "toonaard": signature.tonic.name.replace("-", "b").lower() if MODES[arrangement.mode][2] == 3 else signature.tonic.name.replace("-", "b"),
                  "maat": f"{local[0][2]}/{local[0][3]}"}
            sec.pop("akkoorden", None)
            sec.pop("tegenstem", None)
            sec["tempo"] = section["quarter_bpm"]
            notes = [n for n in arrangement.notes if n.start < end and n.end > start]
            if source:
                # Keep original spelling, syllable alignment, barlines and repeat metadata.
                sec["melodie"] = source["melodie"]
            else:
                sec["melodie"] = stem_text([], local, signature)
            for voice, role in (("1", "descant" if profile == "piano" and source else "melody" if source else "motif"),
                                ("2", "inner" if profile == "piano" and source else "alto"),
                                ("3", "tenor"), ("4", "bass")):
                sec[voice] = stem_text([n for n in notes if n.role == role and n.part == "piano"], local, signature,
                                      arrangement.fermatas if voice == "1" else ())
            if profile == "piano" and source:
                sec["3"] = stem_text([n for n in notes if n.role == "melody"], local, signature)
            flute = [n for n in notes if n.part == "flute"]
            if flute:
                sec["tegenstem"] = stem_text(flute, local, signature)
            sec["akkoorden"] = akkoord_text(arrangement.harmony, local, signature)
            sec["compositie_vast"] = True
            result["secties"].append(sec)
    if profile == "flute":
        result["tegenstemnaam"] = ("Dwarsfluit", "Fl.")
    result["handverdeling"] = [[n.pitch, n.start, n.end, piano_hand(n, arrangement)]
                               for n in arrangement.notes if n.part == "piano"]
    result["compositiecontrole"] = arrangement.diagnostics.get("countervoice", {}).get("check", {})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--musescore", help="MuseScore-programma voor PDF en MSCZ van de volledige zangpartituur")
    args = p.parse_args()
    # Liedmappen are already private and ignored. Do not write source variants elsewhere.
    song_root = args.source.resolve().parent.parent
    if not song_root.name.startswith("muziekgroep_") or not args.output.resolve().is_relative_to(song_root):
        p.error("Bewaar compositievarianten binnen dezelfde privé-muziekgroepmap.")
    if args.output.exists() and any(args.output.iterdir()):
        p.error("Kies een lege uitvoermap.")
    stuk = mp.laad(args.source)
    melody, chorale, singing, lengths = source_arrangement(stuk)
    config = json.loads(args.config.read_text())
    from harmonizer.corpus import digest
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "source.snapshot.json", stuk)
    write_json(args.output / "provenance.json", {
        "source": str(args.source.resolve()), "source_sha256": digest(args.source), "config": config,
        "implementation_sha256": {str(p.relative_to(ROOT)): digest(p)
                                  for folder in (ROOT / "harmonizer", ROOT / "koele")
                                  for p in sorted(folder.glob("*.py"))},
        "human_acceptance": "pending"})
    def validate(variant):
        return validate_stuk(to_stuk(stuk, variant, singing, lengths))

    try:
        variants = compose_variants(melody, chorale, config, validator=validate)
    except CompositionError as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "failed.report.json", getattr(exc, "report", {"error": str(exc)}))
        raise
    args.output.mkdir(parents=True, exist_ok=True)
    export_variants(variants, melody, args.output, soundfont=config.get("soundfont"))
    for i, variant in enumerate(variants, 1):
        converted = to_stuk(stuk, variant, singing, lengths)
        label = "dwarsfluit" if config.get("countervoice") == "flute" else "piano-bovenstem" if config.get("countervoice") == "piano" else "piano"
        converted["bestandsnaam"] = stuk.get("bestandsnaam", stuk["titel"]) + f" (thematisch {i}, {label})"
        target = args.output / f"{args.source.stem}_thematisch_{i}.py"
        target.write_text("# Zelfstandige compositievariant; oorspronkelijke bron behouden.\nSTUK = "
                          + pprint.pformat(converted, width=110, sort_dicts=False) + "\n")
        xml = target.with_suffix(".musicxml")
        mp.bouw(converted).write("musicxml", fp=xml)
        mp.nabewerk(xml)
        if args.musescore:
            from harmonizer.chorale_lab import _musescore_export
            _musescore_export(args.musescore, xml, target.with_suffix(".mscz"), target.with_suffix(".mscz.log"), style=ROOT / "koele" / "stijl.mss")
            mp.ruim_bereik(target.with_suffix(".mscz"), converted.get("spatium", 1.5), hide_empty=True)
            _musescore_export(args.musescore, target.with_suffix(".mscz"), target.with_suffix(".pdf"), target.with_suffix(".pdf.log"), style=ROOT / "koele" / "stijl.mss")
    print(f"{len(variants)} varianten: {args.output.resolve()}")


def validate_stuk(stuk):
    from controleer import stemcontrole
    from greep import spans
    from harmonie_regels import Score, ZACHT, check

    messages, warnings = stemcontrole(stuk)
    if messages:
        raise CompositionError("STUK-stemcontrole: " + "; ".join(messages[:3]))
    unplayable = spans(mp.bouw(stuk))
    if unplayable:
        raise CompositionError("STUK-handbereik: " + "; ".join(unplayable[:3]))
    with TemporaryDirectory(prefix="koele-compositie-") as tmp:
        path = Path(tmp) / "piano.musicxml"
        mp.bouw(stuk, met_zang=False).write("musicxml", fp=path)
        findings = check(Score(path, voice_identity=True))
    hard = [r for r in findings if r["code"] not in ZACHT]
    if hard:
        raise CompositionError("STUK-harmoniecontrole: " + "; ".join(
            f"maat {r['measure']} {r['code']} {r['detail']}" for r in hard[:3]))
    return {"hard_findings": 0, "voice_findings": 0, "hand_findings": 0,
            "warnings": warnings, "soft_findings": [r for r in findings if r["code"] in ZACHT]}


if __name__ == "__main__":
    main()
