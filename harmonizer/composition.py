"""Transparent composition diagnostics and diverse candidate selection."""

from collections import Counter
from itertools import pairwise


def composition_metrics(arrangement):
    sections = []
    for section in arrangement.sections:
        top = sorted(
            [
                n
                for n in arrangement.notes
                if n.role in ("motif", "melody")
                and section["start"] <= n.start < section["end"]
            ],
            key=lambda n: n.start,
        )
        cells = [(b.pitch - a.pitch, round(a.duration, 3)) for a, b in pairwise(top)]
        grams = Counter(tuple(cells[i : i + 8]) for i in range(max(0, len(cells) - 7)))
        loop_repeats = sum(max(0, n - 2) for n in grams.values())
        hs = [
            h
            for h in arrangement.harmony
            if section["start"] <= h.start < section["end"]
        ]
        changes = []
        for h in hs:
            label = (h.root, h.quality)
            if not changes or changes[-1] != label:
                changes.append(label)
        leaps = sum(abs(b.pitch - a.pitch) > 7 for a, b in pairwise(top))
        dissonances = 0
        if section["name"] != "Harmonisatie":
            from .profile import QUALITIES

            for i, n in enumerate(top):
                h = next((h for h in hs if h.start <= n.start < h.end), None)
                if h and (n.pitch - h.root) % 12 not in QUALITIES[h.quality]:
                    after = top[i + 1] if i + 1 < len(top) else None
                    nh = next(
                        (h for h in hs if after and h.start <= after.start < h.end),
                        None,
                    )
                    if (
                        not after
                        or abs(after.pitch - n.pitch) > 2
                        or not nh
                        or (after.pitch - nh.root) % 12 not in QUALITIES[nh.quality]
                    ):
                        dissonances += 1
        sections.append(
            {
                "name": section["name"],
                "excess_repeated_eight_note_cells": loop_repeats,
                "large_top_leaps": leaps,
                "unresolved_free_dissonances": dissonances,
                "harmonic_changes": len(changes),
                "rhythm_values": sorted({n.duration for n in top}),
            }
        )
    penalty = sum(
        (
            s["excess_repeated_eight_note_cells"] * 0.1
            + s["large_top_leaps"] * 0.03
            + s["unresolved_free_dissonances"] * 1.0
        )
        for s in sections
        if s["name"] != "Harmonisatie"
    )
    return {
        "sections": sections,
        "penalty": penalty,
        "listening_quality": "not_established",
    }


def descriptor(arrangement):
    features = set()
    for key in ("prelude_plan", "postlude_plan"):
        plan = arrangement.diagnostics.get(key, {})
        features.add((key, "meter", tuple(plan.get("settings", {}).get("meter", []))))
        for p in plan.get("phrases", []):
            features.add(
                (key, p["function"], round(p["end"] - p["start"], 2), p.get("density"))
            )
        for motif in plan.get("motifs", []):
            features.add((key, "motif", tuple(motif)))
    return features


def choose_diverse(rows, arrangements, count=3):
    remaining = sorted(
        rows, key=lambda c: (c.get("combined_score", c["score"]), c["seed"])
    )
    by_id = {row["id"]: a for row, a in zip(rows, arrangements)}
    chosen = []
    while remaining and len(chosen) < count:

        def objective(c):
            features = descriptor(by_id[c["id"]])
            similarity = max(
                (
                    len(features & descriptor(by_id[x["id"]]))
                    / max(1, len(features | descriptor(by_id[x["id"]])))
                    for x in chosen
                ),
                default=0,
            )
            return c.get("combined_score", c["score"]) + 2 * similarity

        winner = min(remaining, key=objective)
        chosen.append(winner)
        remaining.remove(winner)
    return chosen
