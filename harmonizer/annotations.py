"""Shared validation for reviewed corpus segments."""

import hashlib
import math
from pathlib import Path


def segment_split(segment, source, sources):
    if not source["compilation"] and segment["tune"] != source["tune"]:
        raise ValueError(
            "Een losse opname mag niet via een andere melodienaam van split veranderen."
        )
    splits = {
        s["split"]
        for s in sources.values()
        if s["tune"] == segment["tune"] and s["split"] != "excluded"
    }
    if len(splits) > 1:
        raise ValueError("Dezelfde melodie staat in meerdere splits.")
    if splits:
        return splits.pop()
    if not source["compilation"]:
        raise ValueError("Nieuwe melodienaam: werk eerst de manifestgroepen bij.")
    if not segment.get("reviewed"):
        return "excluded"
    number = (
        int(
            hashlib.sha256(("koele-v1:" + segment["tune"]).encode()).hexdigest()[:8], 16
        )
        % 100
    )
    return "train" if number < 70 else "validation" if number < 85 else "test"


def validate_splits(sources):
    identities = {}
    for source in sources.values():
        if source["split"] == "excluded":
            continue
        for field in ("group", "midi_sha256", "audio_sha256"):
            if source.get(field):
                identity = field, source[field]
                previous = identities.setdefault(identity, source["split"])
                if previous != source["split"]:
                    raise ValueError(
                        "Dezelfde melodiegroep of broninhoud staat in meerdere splits."
                    )


def segment_group(segment, source, sources):
    return next(
        (
            s["group"]
            for s in sources.values()
            if s["tune"] == segment["tune"] and s["split"] != "excluded"
        ),
        segment["tune"],
    )


def validate_reviewed(segment, source):
    if not segment.get("reviewed"):
        return
    required = ("key", "meter", "sections", "phrases", "melody_midi")
    if not all(segment.get(k) for k in required):
        raise ValueError(
            "Een gecontroleerd segment vereist key, meter, sections, phrases en melody_midi."
        )
    if not Path(segment["melody_midi"]).is_file():
        raise ValueError("Het gecontroleerde melodiebestand ontbreekt.")
    start, end = segment["start"], segment["end"]
    if (
        not all(math.isfinite(t) for t in (start, end))
        or not 0 <= start < end <= source["duration"] + 0.1
    ):
        raise ValueError("Segment valt buiten de bronopname.")
    if (
        any(not start < t <= end for t in segment["phrases"])
        or sorted(set(segment["phrases"])) != segment["phrases"]
    ):
        raise ValueError("Frase-einden moeten oplopen in absolute bronseconden.")
    cursor = start
    for section in segment["sections"]:
        if abs(section["start"] - cursor) > 0.05 or not cursor < section["end"] <= end:
            raise ValueError("Vormdelen moeten het segment aansluitend bedekken.")
        if section["name"] not in ("Voorspel", "Koraal", "Tussenspel", "Naspel"):
            raise ValueError("Onbekend vormdeel.")
        cursor = section["end"]
    if abs(cursor - end) > 0.05:
        raise ValueError("Vormdelen bedekken niet het volledige segment.")
    if source["compilation"] and not segment.get("duplicate_checked"):
        raise ValueError("Controleer duplicaten vóór opname van een compilatiesegment.")
