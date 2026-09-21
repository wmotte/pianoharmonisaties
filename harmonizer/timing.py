"""Structural tempo, metre and section configuration in quarter-note units."""

import math

UNITS = {"whole": 4, "half": 2, "quarter": 1, "eighth": 0.5}


def quarter_bpm(tempo):
    if isinstance(tempo, (int, float)):
        value = float(tempo)
    else:
        if tempo.get("unit", "quarter") not in UNITS:
            raise ValueError("Onbekende telwaarde bij tempo.")
        value = float(tempo["bpm"]) * UNITS[tempo.get("unit", "quarter")]
        if tempo.get("dotted", False):
            value *= 1.5
    if not math.isfinite(value) or not 20 <= value <= 240:
        raise ValueError("Tempo moet 20–240 kwartnoten per minuut zijn.")
    return value


def tempo_map(arrangement):
    values = getattr(arrangement, "tempos", None) or [(0.0, arrangement.bpm)]
    result = []
    for t, bpm in values:
        bpm = quarter_bpm(bpm)
        if not math.isfinite(t) or t < 0 or t >= arrangement.length:
            raise ValueError("Tempowissel buiten arrangement.")
        if result and t <= result[-1][0]:
            raise ValueError("Tempowissels moeten strikt oplopen.")
        result.append((t, bpm))
    if result[0][0] != 0:
        raise ValueError("Begintempo ontbreekt.")
    return result


def local_tempo(arrangement, beat):
    return next(bpm for t, bpm in reversed(tempo_map(arrangement)) if t <= beat)


def section_settings(melody, profile, config, name, rng):
    key = "intro" if name == "Voorspel" else "outro"
    overrides = config.get("sections", {}).get(key, {})
    unknown = set(overrides) - {"meter", "tempo", "bars"}
    if unknown:
        raise ValueError(f"Onbekende sectie-instellingen: {sorted(unknown)}")
    sources = [
        s
        for s in profile.get("section_library", [])
        if s["name"] == name
        and s.get("split") == "train"
        and s.get("boundary_source") == "explicit"
        and (s.get("reviewed") or config.get("allow_draft"))
    ]
    if sources:
        requested_meter = overrides.get("meter")
        if isinstance(requested_meter, str):
            requested_meter = [int(x) for x in requested_meter.split("/")]
        same_meter = [s for s in sources if s["meter"] == requested_meter]
        sources = same_meter or sources
        # Prefer a matching mode, but never sample validation/test material.
        matching = [s for s in sources if s.get("mode") == melody.mode]
        source = rng.choice(matching or sources)
    else:
        source = {}
    meter = overrides.get("meter", source.get("meter", [4, 4]))
    if isinstance(meter, str):
        meter = [int(x) for x in meter.split("/")]
    if len(meter) != 2 or meter[0] < 1 or meter[1] not in (2, 4, 8, 16):
        raise ValueError("Ongeldige sectiemaatsoort.")
    measure = meter[0] * 4 / meter[1]
    bpm = quarter_bpm(overrides.get("tempo", source.get("quarter_bpm", melody.bpm)))
    legacy = config.get(key + "_beats")
    if legacy is not None and "bars" in overrides:
        raise ValueError("Gebruik sectielengte in maten of tellen, niet beide.")
    ratio = profile.get("section_ratios", {}).get(name)
    fallback = max(
        32 if key == "intro" else 16,
        min(
            128 if key == "intro" else 80,
            round(melody.length * (0.6 if key == "intro" else 0.35) / measure)
            * measure,
        ),
    )
    length = float(
        legacy
        if legacy is not None
        else float(overrides["bars"]) * measure
        if "bars" in overrides
        else source["bars"] * measure
        if source
        else max(measure, round(melody.length * ratio / measure) * measure)
        if ratio
        else fallback
    )
    if not math.isfinite(length) or not 2 <= length <= 512:
        raise ValueError("Sectielengte moet tussen 2 en 512 kwartnoottellen liggen.")
    return {
        "meter": list(meter),
        "quarter_bpm": bpm,
        "length": length,
        "source": source,
        "overrides": overrides,
    }
