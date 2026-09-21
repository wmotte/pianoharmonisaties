"""Compare donor melodies in the tonal frame used by the harmonizer."""


def tonal_similarity(target, donor):
    """Preserve tonic-relative pitch classes; choose only octave placement.

    Rhythm must match exactly to count a note as equal. This is retrieval
    evidence, not a guarantee of suitable harmony or voice leading.
    """
    if target.mode != donor["mode"]:
        raise ValueError("Tonal comparison requires matching modes.")
    actual = {(n.start, n.end): n.pitch for n in target.notes}
    if not actual or not donor["melody"]:
        raise ValueError("Both melody sequences must contain notes.")
    if len(actual) != len(target.notes):
        raise ValueError("Target melody has ambiguous coincident notes.")
    difference = (target.tonic - donor["tonic"]) % 12
    candidates = []
    for shift in range(-24, 25):
        if shift % 12 != difference:
            continue
        observed = {(s, e): p + shift for p, s, e in donor["melody"]}
        if len(observed) != len(donor["melody"]):
            raise ValueError("Donor melody has ambiguous coincident notes.")
        shared = actual.keys() & observed.keys()
        exact = sum(actual[k] == observed[k] for k in shared)
        mismatches = len(shared) - exact + len(actual.keys() ^ observed.keys())
        candidates.append((mismatches, -exact, abs(shift), shift))
    best = min(candidates)
    return {"mismatches": best[0], "exact_notes": -best[1], "transpose": best[3]}
