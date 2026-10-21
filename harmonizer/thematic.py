"""Piano voicings and the public entry point for phrase composition."""

from functools import lru_cache
from .profile import QUALITIES


@lru_cache(maxsize=4096)
def _voicings(root, quality, top, density, final, leading=()):
    pcs = {(root + x) % 12 for x in QUALITIES[quality]}
    result = []
    for bass in range(24 if top < 60 else 33, min(56, top - 4)):
        if bass % 12 not in ({root} if final else pcs):
            continue
        inner = [p for p in range(max(21, top - 12), top) if p % 12 in pcs and p > bass]
        shapes = [(None, None)] if density == 2 else [(None, a) for a in inner]
        if density == 4:
            tenors = [p for p in range(max(33 if top < 60 else 45, bass + 1), top - 1)
                      if p % 12 in pcs and (top - p <= 12 or p - bass <= 12)]
            shapes = [(t, a) for t in tenors for a in inner if t < a <= t + 12]
        for tenor, alto in shapes:
            present = {p % 12 for p in (bass, tenor, alto, top) if p is not None}
            pitches = [p for p in (bass, tenor, alto, top) if p is not None]
            if any(sum(p % 12 == pc for p in pitches) > 1 for pc in leading):
                continue
            if quality == "major" and sum(p % 12 == (root + 4) % 12 for p in pitches) > 1:
                continue
            if len(QUALITIES[quality]) >= 4 and any(sum(p % 12 == (root + i) % 12 for p in pitches) > 1
                                                   for i in QUALITIES[quality] if i in (10, 11)):
                continue
            if final and not pcs <= present:
                continue
            # Prefer three upper notes in RH, permitting a close bass/tenor in LH.
            score = 0.04 * abs(bass - 43) + 0.03 * abs((alto or top) - (top - 5))
            score += 0.15 * (tenor is not None and top - tenor > 12)
            score += len(pcs - present) * 1.5
            if bass % 12 != root:
                score += 0.3
            result.append((score, {k: p for k, p in
                           (("bass", bass), ("tenor", tenor), ("alto", alto), ("motif", top))
                           if p is not None}))
    return sorted(result, key=lambda x: x[0])[:96]


def free_section(melody, length, section, seed=0, profile=None, settings=None, material=None):
    from .counterpoint import CompositionError
    from .phrase_plan import compose

    rejected = []
    for attempt in range(6):
        plan_seed = seed + attempt
        try:
            top, harmonies, score, plan = compose(melody, length, section, plan_seed, profile, settings, material)
        except CompositionError as exc:
            rejected.append({"seed": plan_seed, "reason": str(exc)})
            last_error = exc
            continue
        plan["plan_search"] = {"requested_seed": seed, "selected_seed": plan_seed, "rejected": rejected}
        return top, harmonies, score, plan
    last_error.report = {"status": "phrase_search_exhausted", "rejected": rejected}
    raise last_error
