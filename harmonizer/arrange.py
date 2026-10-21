"""Shared framing for both chorale generators and the STUK adapter."""

import json
import random
from dataclasses import asdict, replace
from pathlib import Path

from .composition import composition_metrics
from .counterpoint import CompositionError, add_countervoice, hand_assignment
from .model import write_json
from .prelude import free_accompaniment, free_section
from .timing import section_settings


def validate_config(config):
    allowed = {"sections", "intro_beats", "outro_beats", "countervoice", "seed", "candidates",
               "allow_draft", "style_analysis", "soundfont"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"Onbekende arrangementinstellingen: {sorted(unknown)}")
    if config.get("countervoice", "none") not in ("none", "flute", "piano"):
        raise ValueError("countervoice moet none, flute of piano zijn.")
    if not 3 <= int(config.get("candidates", 3)) <= 32:
        raise ValueError("candidates moet tussen 3 en 32 liggen.")
    if set(config.get("sections", {})) - {"intro", "outro"}:
        raise ValueError("Onbekend vormdeel in sections.")


def load_style(config):
    from .corpus import digest

    profile = {"status": "draft", "sources": [], "expression": {}}
    if config.get("style_analysis"):
        path = Path(config["style_analysis"])
        style = json.loads(path.read_text())
        for section in style["section_library"]:
            if digest(Path(section["source_path"])) != section["source_sha256"]:
                raise ValueError("Stijlanalyse is verouderd: bronpartituur gewijzigd.")
        profile.update(section_library=style["section_library"], style_analysis_sha256=digest(path))
    return profile


def frame_arrangement(melody, chorale, config, profile=None, seed=0):
    """Preserve an already generated chorale and compose both surrounding sections."""
    from .engine import Arrangement

    profile = profile or {}
    if config.get("countervoice", "none") != "none" and chorale.diagnostics.get("countervoice", {}).get("profile") != config["countervoice"]:
        chorale = add_countervoice(chorale, melody, config["countervoice"], seed)
    intro_settings = section_settings(melody, profile, config, "Voorspel", random.Random(seed))
    outro_settings = section_settings(melody, profile, config, "Naspel", random.Random(seed + 2018))
    first = min(chorale.harmony, key=lambda h: h.start)
    intro_settings.update(arrival_root=first.root, arrival_quality=first.quality)
    intro_settings["piano_descant_entry"] = config.get("countervoice") == "piano"
    def boundary(time):
        active = [n for n in chorale.notes if n.start <= time + 1e-7 < n.end]
        active = [n for n in active if n.part == "piano"]
        sung = [n for n in active if n.role in ("melody", "descant")]
        if not sung:
            return {}
        top = max(sung, key=lambda n: n.pitch)
        accompaniment = sorted(n.pitch for n in active if n is not top)
        result = {"motif": top.pitch}
        if accompaniment:
            result["bass"] = accompaniment[0]
        if len(accompaniment) >= 2:
            result["alto"] = accompaniment[-1]
        if len(accompaniment) >= 3:
            result["tenor"] = accompaniment[1]
        if config.get("countervoice") == "piano" and any(n.role == "descant" for n in active):
            melodic = next((n for n in active if n.role == "melody"), None)
            inner = next((n for n in active if n.role == "inner"), None)
            result.pop("alto", None)
            result.pop("tenor", None)
            if melodic:
                result["tenor"] = melodic.pitch
            if inner:
                result["alto"] = inner.pitch
        return result
    intro_settings["arrival_voices"] = boundary(melody.notes[0].start)
    outro_settings["departure_voices"] = boundary(max(n.start for n in chorale.notes))
    last = max(chorale.harmony, key=lambda h: h.start)
    if last.root == melody.tonic and last.quality in ("major", "minor"):
        outro_settings.setdefault("terminal_quality", last.quality)
    intro, ih, isc, ip = free_section(melody, intro_settings["length"], "Voorspel", seed, profile, intro_settings)
    outro, oh, osc, op = free_section(melody, outro_settings["length"], "Naspel", seed + 2018, profile, outro_settings, ip["motifs"])
    sections, notes, harmonies, meters, phrases, fermatas, tempos = [], [], [], [], [], [], []
    cursor = 0.0
    for name, source, hs, material, plan in (
        ("Voorspel", intro, ih, intro.notes + free_accompaniment(ih, intro, ip, profile), ip),
        ("Harmonisatie", melody, chorale.harmony, chorale.notes, None),
        ("Naspel", outro, oh, outro.notes + free_accompaniment(oh, outro, op, profile), op),
    ):
        sections.append({"name": name, "start": cursor, "end": cursor + source.length,
                         "quarter_bpm": source.bpm, "texture": "chorale" if plan is None else "variable"})
        notes.extend(replace(n, start=n.start + cursor) for n in material)
        harmonies.extend(replace(h, start=h.start + cursor, end=h.end + cursor) for h in hs)
        meters.extend((a + cursor, n, d) for a, n, d in source.meters)
        phrases.extend(p + cursor for p in source.phrases)
        fermatas.extend(p + cursor for p in source.fermatas)
        if not tempos or tempos[-1][1] != source.bpm:
            tempos.append((cursor, source.bpm))
        cursor += source.length
    fermatas.append(intro.length)
    last_intro = max(n.start for n in intro.notes)
    diagnostics = {**chorale.diagnostics, "prelude_plan": ip, "postlude_plan": op,
                   "melody_exact": True, "human_accepted": False, "musical_quality": "not_evaluated",
                   "chorale_diagnostics": chorale.diagnostics,
                   "entry_pause": {"start": last_intro, "end": intro.length,
                                   "time_stretch": 1.5, "caesura": True}}
    result = Arrangement(sorted(notes, key=lambda n: (n.start, n.pitch)), harmonies, sections,
                         meters, sorted(set(phrases)), sorted(set(fermatas)), melody.bpm,
                         (isc + osc + chorale.score) / 3, seed, intro.length, cursor,
                         diagnostics, melody.tonic, melody.mode, tempos)
    expected = [(n.pitch, round(n.start + intro.length, 7), round(n.duration, 7)) for n in melody.notes]
    actual = [(n.pitch, round(n.start, 7), round(n.duration, 7)) for n in result.notes if n.role == "melody"]
    if actual != expected:
        raise AssertionError("De vaste zangmelodie is gewijzigd.")
    if "countervoice" in diagnostics:
        countervoice = {**diagnostics["countervoice"]}
        countervoice["harmonic_changes"] = [{**c, "start": c["start"] + intro.length, "end": c["end"] + intro.length}
                                             for c in countervoice["harmonic_changes"]]
        countervoice["embellishments"] = [{**e, "beat": e["beat"] + intro.length}
                                           for e in countervoice.get("embellishments", [])]
        diagnostics["countervoice"] = countervoice
    hands = hand_assignment(result.notes)
    if hands is None:
        raise CompositionError("Geen handverdeling binnen een octaaf voor het volledige arrangement.")
    result.diagnostics["hand_assignment"] = hands
    result.diagnostics["composition"] = composition_metrics(result)
    return result


def compose_variants(melody, chorale, config, profile=None, validator=None):
    validate_config(config)
    profile = profile or load_style(config)
    requested = int(config.get("candidates", 3))
    candidates, rejected, fingerprints = [], [], set()
    budget = max(12, requested * 16)
    seed = int(config.get("seed", 0))
    bodies = {}
    for i in range(budget):
        trial_seed = seed + i * 7919
        try:
            body = chorale
            if config.get("countervoice", "none") != "none":
                family = i % min(6, requested * 2)
                if family not in bodies:
                    try:
                        bodies[family] = add_countervoice(chorale, melody, config["countervoice"], seed + family * 7919)
                    except CompositionError as exc:
                        bodies[family] = exc
                if isinstance(bodies[family], CompositionError):
                    raise bodies[family]
                body = bodies[family]
            a = frame_arrangement(melody, body, config, profile, trial_seed)
            if validator:
                a.diagnostics["stuk_checks"] = validator(a)
        except CompositionError as exc:
            rejected.append({"seed": trial_seed, "reason": str(exc)})
            continue
        fp = tuple((n.pitch, n.start, n.duration, n.part, n.role) for n in a.notes)
        if fp in fingerprints:
            continue
        fingerprints.add(fp)
        candidates.append(a)
        if len(candidates) >= requested:
            break
    if len(candidates) < requested:
        exc = CompositionError(f"Slechts {len(candidates)} van {requested} geldige arrangementen binnen {budget} pogingen.")
        exc.report = {"status": "search_exhausted", "valid_candidates": len(candidates), "rejected": rejected}
        raise exc
    for a in candidates:
        a.diagnostics["candidate_search"] = {"budget": budget, "rejected": rejected}
    return candidates


def export_variants(variants, melody, output, *, soundfont=None, musescore=None):
    from .midi import render, save_midi, validate_export
    from .notation import save_musicxml
    from .chorale_review import verify_score

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, a in enumerate(variants, 1):
        stem = output / f"arrangement_{i}"
        write_json(stem.with_suffix(".json"), asdict(a))
        structural = stem.with_suffix(".mid")
        performance = output / f"arrangement_{i}.performance.mid"
        save_midi(a, structural, {})
        save_midi(a, performance, {}, expressive=True)
        checks = {"structural": validate_export(structural, a),
                  "performance": validate_export(performance, a, expressive=True),
                  "notation": save_musicxml(a, stem.with_suffix(".musicxml"), melody.tonic, melody.mode, melody.title)}
        if musescore:
            checks["musescore"] = verify_score(stem.with_suffix(".musicxml"), musescore)
        if soundfont:
            render(performance, stem.with_suffix(".wav"), soundfont)
        rows.append({"id": stem.name, "seed": a.seed, "checks": checks,
                     "composition": a.diagnostics["composition"],
                     "countervoice": a.diagnostics.get("countervoice"),
                     "listening_acceptance": "pending"})
    write_json(output / "arrangements.report.json", {"status": "awaiting_listening", "variants": rows,
               "human_votes": 0, "search": variants[0].diagnostics.get("candidate_search", {})})
    return rows
