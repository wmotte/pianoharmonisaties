"""Phrase-local motifs with octave-aware scale positions and exact transformations."""

from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from math import gcd, isfinite
from functools import reduce

from .model import MODES


def scale_pitch(degree, tonic, mode, alteration=0):
    octave, step = divmod(degree, 7)
    return 12 * octave + tonic + MODES[mode][step] + alteration


def scale_position(midi, tonic, mode):
    # Prefer the modal spelling, retaining a signed chromatic alteration.
    candidates = range((midi - tonic) // 12 * 7 - 7, (midi - tonic) // 12 * 7 + 14)
    degree = min(candidates, key=lambda d: (abs(scale_pitch(d, tonic, mode) - midi),
                                           scale_pitch(d, tonic, mode) > midi))
    return degree, midi - scale_pitch(degree, tonic, mode)


@dataclass(frozen=True)
class MotifTone:
    degree: int
    alteration: int
    offset: float
    duration: float


@dataclass(frozen=True)
class Motif:
    tones: tuple[MotifTone, ...]
    span: float
    source_start: float
    source_end: float
    phrase: int
    score: float = 0
    occurrences: tuple[float, ...] = ()

    def data(self):
        return asdict(self)

    @classmethod
    def from_data(cls, value):
        return cls(**{**value, "tones": tuple(MotifTone(**t) for t in value["tones"]),
                      "occurrences": tuple(value.get("occurrences", ()))})


def transform(motif, *, transpose=0, invert=False, retrograde=False, time_scale=1):
    """Transform complete note events, including their spacing and last duration."""
    if not isfinite(time_scale) or time_scale <= 0:
        raise ValueError("De ritmische schaalfactor moet positief en eindig zijn.")
    axis = motif.tones[0].degree
    tones = []
    for t in motif.tones:
        degree = 2 * axis - t.degree if invert else t.degree
        offset = motif.span - t.offset - t.duration if retrograde else t.offset
        tones.append(MotifTone(degree + transpose, -t.alteration if invert else t.alteration,
                               offset * time_scale, t.duration * time_scale))
    return replace(motif, tones=tuple(sorted(tones, key=lambda t: t.offset)),
                   span=motif.span * time_scale)


def signature(motif):
    tones = motif.tones
    ticks = [round(Fraction(x).limit_denominator(96) * 96)
             for t in tones for x in (t.duration, t.offset) if x > 0]
    unit = reduce(gcd, ticks, 96) / 96
    return (tuple(t.degree - tones[0].degree for t in tones),
            tuple(t.alteration for t in tones),
            tuple((round(t.offset / unit), round(t.duration / unit)) for t in tones))


def extract_motifs(melody, limit=8):
    """Rank several cells, without crossing a phrase or rewarding overlapping copies."""
    melody.validate()
    candidates = []
    left = 0
    for pi, end in enumerate(melody.phrases):
        notes = [n for n in melody.notes if left <= n.start < end]
        for size in (3, 4, 5):
            for i in range(len(notes) - size + 1):
                fragment = notes[i:i + size]
                first, last = fragment[0], fragment[-1]
                tones = tuple(MotifTone(*scale_position(n.pitch, melody.tonic, melody.mode),
                                        n.start - first.start, n.duration) for n in fragment)
                candidates.append(Motif(tones, last.end - first.start, first.start, last.end, pi))
        left = end
    # Tiny input remains meaningful source material, rather than a random replacement.
    if not candidates:
        notes = [n for n in melody.notes if n.start < melody.phrases[0]]
        first, last = notes[0], notes[-1]
        candidates = [Motif(tuple(MotifTone(*scale_position(n.pitch, melody.tonic, melody.mode),
                                           n.start - first.start, n.duration) for n in notes),
                            last.end - first.start, first.start, last.end, 0)]
    groups = {}
    for motif in candidates:
        groups.setdefault(signature(motif), []).append(motif)
    ranked = []
    for copies in groups.values():
        selected, stop = [], -1
        for m in sorted(copies, key=lambda m: m.source_start):
            if m.source_start >= stop:
                selected.append(m.source_start)
                stop = m.source_end
        for m in copies:
            contour = [b.degree - a.degree for a, b in zip(m.tones, m.tones[1:])]
            variety = len(set(t.degree for t in m.tones))
            rhythm = len(set(t.duration for t in m.tones))
            starts_phrase = m.source_start == next(n.start for n in melody.notes
                if (melody.phrases[m.phrase - 1] if m.phrase else 0) <= n.start)
            score = (2 * starts_phrase + min(3, len(selected) - 1) + 0.5 * rhythm
                     + 0.4 * len(set(contour)) - 3 * (variety == 1)
                     - 1.5 * (len(set(contour)) == 1))
            ranked.append(replace(m, score=score, occurrences=tuple(selected)))
    unique = {}
    for m in sorted(ranked, key=lambda m: (-m.score, m.source_start, -len(m.tones))):
        unique.setdefault(signature(m), m)
    return list(unique.values())[:limit]
