#!/usr/bin/env python3
"""Hypercorrectie: bas en binnenstemmen herzetten met een vaste melodie.

De bestaande regelcontrole is de zoekdoelfunctie en controleert ook de export.
Alleen een uitvoer zonder meldingen krijgt de status 'volledig'.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from music21 import pitch

from analyse_stijl import label_chord
from corrigeer_harmonie import apply, respell
from harmonie_regels import (DIR, Score, Vertical, assign_slots, check, chord_spelling,
                             mark, report_lines, summary)

ALGORITHM = 'hypercorrectie-1'


@lru_cache(maxsize=4096)
def labelled(pcs, bass):
    return label_chord(set(pcs), bass)


@lru_cache(maxsize=8192)
def named_pitch(midi, name):
    p = pitch.Pitch(name)
    p.octave = midi // 12 - 1
    p.octave += (midi - int(p.midi)) // 12
    return p


@dataclass(eq=False)
class SearchNote:
    id: int
    midi: int
    staff: str
    on: float
    end: float
    measure: int
    beat: float
    name: str = 'C'
    codes: list = field(default_factory=list)

    @property
    def spitch(self):
        return named_pitch(self.midi, self.name)


def melody_ids(sc):
    """De hoogste klinkende rechterhandnoot vormt de vaste melodie."""
    result = set()
    for v in sc.verticals:
        right = [r for r in v.notes if r.staff == 'R']
        if right:
            top = max(r.midi for r in right)
            result.update(r.id for r in right if r.midi == top)
    return result


class Search:
    """Lokale herzetting met exacte regelcontrole, inclusief liggende noten."""
    def __init__(self, sc, radius=36):
        self.sc = sc
        self.orig = {r.id: r.midi for r in sc.recs}
        self.values = dict(self.orig)
        self.recs = {r.id: r for r in sc.recs}
        self.v_ids = [tuple(r.id for r in v.notes) for v in sc.verticals]
        self.attack = {r.id: j for j, v in enumerate(sc.verticals) for r in v.notes if r.on == v.on}
        # Alle hoogste noten blijven vast, inclusief unisono en latere bovenstemmen.
        self.melody = melody_ids(sc)
        # Behoud de oorspronkelijke spelling van de vaste melodie.
        self.fixed_names = {i: self.recs[i].spitch.name for i in self.melody}
        self.mutable = set(self.orig) - self.melody
        self.dependencies = []
        self.affected = defaultdict(set)
        for j in range(len(self.v_ids)):
            ids = set(self.v_ids[j])
            if j:
                ids.update(self.v_ids[j - 1])
            for i in list(ids):
                ids.update(self.v_ids[self.attack[i]])
            dep = tuple(sorted(ids))
            self.dependencies.append(dep)
            for i in dep:
                self.affected[i].add(j)
        self.source_pcs = [{self.orig[i] % 12 for i in ids} for ids in self.v_ids]
        self.source_labels = [v.label for v in sc.verticals]
        self.candidates = {}
        for i in sorted(self.mutable):
            r = self.recs[i]
            upper = min(max((self.orig[n] for n in ids if self.recs[n].staff == 'R'), default=108)
                        for ids in self.v_ids if i in ids)
            self.candidates[i] = tuple(m for m in range(max(21, r.midi - radius),
                                                         min(108, upper, r.midi + radius) + 1))
        # Caches horen bij deze zoekopdracht en houden geen eerdere partituren vast.
        self.factor = lru_cache(maxsize=16000)(self._factor)
        self.spelling = lru_cache(maxsize=16000)(self._spelling)
        self.current = [self.evaluate(j, self.values) for j in range(len(self.v_ids))]
        self.evaluations = 0

    def _spelling(self, j, pitches):
        v = self.sc.verticals[j]
        notes = [SimpleNamespace(midi=m) for m in sorted(pitches)]
        label = labelled(tuple(sorted({m % 12 for m in pitches})), min(pitches) % 12)
        return {pc: p.name for pc, p in chord_spelling(
            SimpleNamespace(notes=notes, key=v.key, label=label)).items()}

    def _factor(self, j, pitches):
        values = dict(zip(self.dependencies[j], pitches))
        records = {}
        for i in set(self.v_ids[j]) | (set(self.v_ids[j - 1]) if j else set()):
            r = self.recs[i]
            attack = self.attack[i]
            name = self.fixed_names.get(i)
            if name is None:
                name = self.spelling(attack, tuple(values[n] for n in self.v_ids[attack]))[values[i] % 12]
            records[i] = SearchNote(i, values[i], r.staff, r.on, r.end, r.measure, r.beat, name)
        verticals = []
        for k in ([j - 1, j] if j else [j]):
            v = self.sc.verticals[k]
            notes = sorted([records[i] for i in self.v_ids[k]], key=lambda r: r.midi)
            pcs = tuple(sorted({r.midi % 12 for r in notes}))
            vv = Vertical(v.on, notes, v.measure, v.beat, v.key, labelled(pcs, notes[0].midi % 12))
            assign_slots(vv)
            verticals.append(vv)
        findings = check(SimpleNamespace(verticals=verticals), include_ids=True)
        errors = {(f['note_id'], f['code']) for f in findings}
        cur = verticals[-1]
        # Anti-uitvlakking: geen verlies van klankdichtheid of nieuwe unisono's per hand.
        pcs = {r.midi % 12 for r in cur.notes}
        if len(pcs) < len(self.source_pcs[j]):
            errors.add((-j - 1, 'KLEURVERLIES'))
        counts = Counter((r.staff, r.midi) for r in cur.notes)
        original_counts = Counter((self.recs[i].staff, self.orig[i]) for i in self.v_ids[j])
        if sum(c - 1 for c in counts.values()) > sum(c - 1 for c in original_counts.values()):
            errors.add((-j - 1, 'UNISONO'))
        soft = 0.0
        source = self.source_pcs[j]
        soft += 3.0 * len(source - pcs) + 1.5 * len(pcs - source)
        soft += 2.0 * (cur.label[1] != self.source_labels[j][1])
        soft += 1.0 * (cur.label[0] != self.source_labels[j][0])
        for r in cur.notes:
            if r.on == cur.on:
                d = abs(r.midi - self.orig[r.id])
                soft += (0.5 if d else 0) + 0.12 * d
        if j:
            # De baslijn en de spreiding volgen zoveel mogelijk de broncontour.
            prev = verticals[0]
            source_delta = min(self.orig[i] for i in self.v_ids[j]) - min(self.orig[i] for i in self.v_ids[j - 1])
            delta = cur.notes[0].midi - prev.notes[0].midi
            soft += 0.3 * abs(delta - source_delta)
            soft += 2.0 * (source_delta != 0 and delta == 0)
            if self.source_pcs[j] != self.source_pcs[j - 1] and pcs == {r.midi % 12 for r in prev.notes}:
                soft += 5.0
        return frozenset(errors), soft

    def evaluate(self, j, values):
        return self.factor(j, tuple(values[i] for i in self.dependencies[j]))

    def trial(self, changes):
        affected = set().union(*(self.affected[i] for i in changes))
        values = self.values | changes
        updated = {j: self.evaluate(j, values) for j in affected}
        error_delta = sum(len(e[0]) - len(self.current[j][0]) for j, e in updated.items())
        soft_delta = sum(e[1] - self.current[j][1] for j, e in updated.items())
        self.evaluations += 1
        return (error_delta, soft_delta), updated

    def commit(self, changes, updated):
        self.values.update(changes)
        for j, result in updated.items():
            self.current[j] = result

    def objective(self):
        return sum(len(e[0]) for e in self.current), sum(e[1] for e in self.current)

    def anchor_trial(self, anchor, deadline):
        """Herstel een liggende bronnoot en herzet haar gehele begeleidingsomgeving."""
        saved_values, saved_current = dict(self.values), list(self.current)
        region = set(self.affected[anchor])
        _, updated = self.trial({anchor: self.orig[anchor]})
        self.commit({anchor: self.orig[anchor]}, updated)
        try:
            for _ in range(8):
                bad = [j for j in region if self.current[j][0]]
                if not bad or time.monotonic() >= deadline:
                    break
                winner = None
                ids = set().union(*(self.dependencies[j] for j in bad)) & (self.mutable - {anchor})
                for i in sorted(ids):
                    if time.monotonic() >= deadline:
                        break
                    for m in self.candidates[i]:
                        if m == self.values[i]:
                            continue
                        score, update = self.trial({i: m})
                        if winner is None or score < winner[0]:
                            winner = score, {i: m}, update
                if winner is None or winner[0] >= (0, -1e-6):
                    break
                self.commit(winner[1], winner[2])
                region.update(winner[2])
            changes = {i: m for i, m in self.values.items() if m != saved_values[i]}
        finally:
            self.values, self.current = saved_values, saved_current
        if not changes:
            return None
        score, update = self.trial(changes)
        return score, changes, update

    def solve(self, rounds=100, seed=0, seconds=300, progress=None):
        rng = random.Random(seed)
        start = time.monotonic()
        best_values, best_objective = dict(self.values), self.objective()
        completed = 0
        tabu = {}
        for sweep in range(rounds):
            bad = [j for j, result in enumerate(self.current) if result[0]]
            if not bad or time.monotonic() - start >= seconds:
                break
            rng.shuffle(bad)
            accepted = 0
            for j in bad:
                if not self.current[j][0]:
                    continue
                if time.monotonic() - start >= seconds:
                    break
                ids = sorted(set(self.dependencies[j]) & self.mutable)
                options = []
                for i in ids:
                    if time.monotonic() - start >= seconds:
                        break
                    for m in self.candidates[i]:
                        if m == self.values[i] or tabu.get((i, m), -1) > sweep:
                            continue
                        changes = {i: m}
                        score, updated = self.trial(changes)
                        options.append((score, changes, updated))
                options.sort(key=lambda x: x[0])
                if not options:
                    continue
                winner = options[0]
                if sweep > 0 and winner[0] >= (0, -1e-6):
                    # Gecoördineerde reparaties ontsnappen aan éénnoots-minima.
                    for _, first, _ in options[:8]:
                        for i in ids:
                            if time.monotonic() - start >= seconds:
                                break
                            if i in first:
                                continue
                            for m in self.candidates[i]:
                                if m == self.values[i] or tabu.get((i, m), -1) > sweep:
                                    continue
                                changes = first | {i: m}
                                score, updated = self.trial(changes)
                                if score < winner[0]:
                                    winner = score, changes, updated
                        if winner[0][0] < 0 or time.monotonic() - start >= seconds:
                            break
                if sweep > 0 and winner[0] >= (0, -1e-6):
                    anchors = sorted((i for i in ids if self.values[i] != self.orig[i]
                                      and self.orig[i] in self.candidates[i]
                                      and self.recs[i].end - self.recs[i].on > 1),
                                     key=lambda i: (-(self.recs[i].end - self.recs[i].on), i))
                    for anchor in anchors[:2]:
                        if time.monotonic() - start >= seconds:
                            break
                        proposal = self.anchor_trial(anchor, start + seconds)
                        if proposal and proposal[0] < winner[0]:
                            winner = proposal
                if winner[0] < (0, -1e-6):
                    self.commit(winner[1], winner[2])
                    accepted += 1
                # Een begrensde herstart mag tijdelijk een regel terugbrengen.
                elif sweep % 3 == 2:
                    pool = [o for o in options[:80] if o[0][0] <= options[0][0][0] + 3]
                    choice = rng.choice(pool)
                    for i in choice[1]:
                        tabu[i, self.values[i]] = sweep + 4
                    self.commit(choice[1], choice[2])
                    accepted += 1
                obj = self.objective()
                if obj < best_objective:
                    best_objective, best_values = obj, dict(self.values)
            completed = sweep + 1
            if progress:
                progress(completed, best_objective[0], self.evaluations)
            if not accepted and sweep % 3 == 2:
                break
        self.values = best_values
        self.current = [self.evaluate(j, self.values) for j in range(len(self.v_ids))]
        return {i: m for i, m in self.values.items() if m != self.orig[i]}, dict(
            rondes=completed, evaluaties=self.evaluations, seconden=round(time.monotonic() - start, 2),
            zoekfouten=best_objective[0], melodienoten_vast=len(self.melody))


def refresh(sc):
    for v in sc.verticals:
        v.notes.sort(key=lambda r: r.midi)
        v.label = labelled(tuple(sorted({r.midi % 12 for r in v.notes})), v.notes[0].midi % 12)
        assign_slots(v)
    for r in sc.recs:
        r.codes.clear()


def metrics(sc):
    pcs = [tuple(sorted({r.midi % 12 for r in v.notes})) for v in sc.verticals]
    types = Counter(v.label[1] for v in sc.verticals)
    total = max(1, len(pcs))
    entropy = -sum((n / total) * math.log2(n / total) for n in Counter(pcs).values())
    bass = [min(r.midi for r in v.notes) for v in sc.verticals]
    return dict(noten=len(sc.recs), unieke_klanken=len(set(pcs)), akkoordtypen=dict(types),
                klankentropie=round(entropy, 4),
                gemiddelde_toonklassen=round(sum(map(len, pcs)) / total, 4),
                basbewegingen=sum(a != b for a, b in zip(bass, bass[1:])))


def articulate_accompaniment(sc):
    """Herarticuleer alleen liggende binnennoten onder een te grote bovenspreiding.

    Splitsing van het notatie-element behoudt bindingen van alle andere noten.
    De opnieuw aangeslagen binnennoot krijgt een afzonderlijke zoekvariabele.
    """
    melody = melody_ids(sc)
    selected = set()
    for v in sc.verticals:
        upper = [v.slots[s] for s in ('S', 'A', 'T') if s in v.slots]
        for high, low in zip(upper, upper[1:]):
            if high.midi - low.midi > 12 and low.on < v.on and low.id not in melody:
                selected.add(low.id)
    plans = {}
    for r in sc.recs:
        if r.id not in selected:
            continue
        for segment in [r] + list(getattr(r, 'tied', [])):
            el = segment.parent or segment.obj
            start = el.getOffsetInHierarchy(sc.parts[r.staff])
            cuts = {v.on - start for v in sc.verticals
                    if start < v.on < start + float(el.quarterLength)}
            plan = plans.setdefault(id(el), (el, set(), set()))
            plan[1].update(cuts)
            plan[2].add(segment.obj.pitch.nameWithOctave)
    added = 0
    for el, cuts, names in plans.values():
        original_notes = el.notes if el.isChord else [el]
        added += len(cuts) * len(names) + sum(
            n.pitch.nameWithOctave in names and n.tie is not None and n.tie.type in ('stop', 'continue')
            for n in original_notes)
        site, start = el.activeSite, el.offset
        fragments = []
        rest, last = el, 0.0
        for cut in sorted(cuts):
            left, rest = rest.splitAtQuarterLength(cut - last, retainOrigin=False)
            fragments.append((last, left))
            last = cut
        fragments.append((last, rest))
        # Behoud volgorde en eindpunten van octaaflijnen, bogen en andere spanners.
        spanners = list(el.getSpannerSites())
        site.remove(el)
        for offset, fragment in fragments:
            for n in (fragment.notes if fragment.isChord else [fragment]):
                if n.pitch.nameWithOctave in names:
                    n.tie = None
            site.insert(start + offset, fragment)
        for span in spanners:
            original_elements = list(span.getSpannedElements())
            expanded = []
            for element in original_elements:
                expanded.extend([f for _, f in fragments] if element is el else [element])
                span.spannerStorage.remove(element)
            span.addSpannedElements(expanded)
    return added


def preservation(source, result):
    """Controleer vaste melodie, tijdsdekking en vergelijkbare muzikale kenmerken."""
    protected = melody_ids(source)
    signature = lambda r: (r.staff, r.on, r.end, r.midi, r.spitch.name)
    wanted = Counter(signature(r) for r in source.recs if r.id in protected)
    available = Counter(signature(r) for r in result.recs)
    melody_ok = not (wanted - available)
    # Splitsen is toegestaan, gaten of extra klinkende stemmen zijn dat niet.
    def coverage(sc):
        events = Counter()
        for r in sc.recs:
            events[r.staff, r.on] += 1
            events[r.staff, r.end] -= 1
        return events
    timing_ok = coverage(source) == coverage(result)
    similarities, unchanged, density_ok = [], [], True
    for b in result.verticals:
        active = [r for r in source.recs if r.on <= b.on < r.end - 1e-6]
        pcs_a, pcs_b = {r.midi % 12 for r in active}, {r.midi % 12 for r in b.notes}
        similarities.append(len(pcs_a & pcs_b) / max(1, len(pcs_a | pcs_b)))
        label_a = labelled(tuple(sorted(pcs_a)), min((r.midi for r in active), default=0) % 12)
        unchanged.append(label_a[:2] == b.label[:2])
        density_ok &= len(pcs_b) >= len(pcs_a)
    before, after = metrics(source), metrics(result)
    similarity = sum(similarities) / max(1, len(similarities))
    harmonic_identity = sum(unchanged) / max(1, len(unchanged))
    gates = dict(melodie_identiek=melody_ok, tijdsdekking_identiek=timing_ok,
                 toonklasdichtheid_behouden=density_ok,
                 klankvariatie_behouden=after['klankentropie'] + 1e-6 >= 0.95 * before['klankentropie'],
                 harmonische_verwantschap=similarity >= 0.85,
                 akkoordidentiteit_behouden=harmonic_identity >= 0.8,
                 basbeweging_behouden=after['basbewegingen'] >= 0.9 * before['basbewegingen'])
    return dict(controles=gates, geslaagd=all(gates.values()),
                toonklasseovereenkomst=round(similarity, 4),
                gelijke_akkoordlabels=round(harmonic_identity, 4))


def prepared_fingerprint(sc):
    records = [(r.id, r.staff, float(r.on), float(r.end), r.midi, r.spitch.name)
               for r in sc.recs]
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()


def run_file(source, out, *, rounds=100, seed=0, seconds=300, radius=36, checkpoint=None):
    sc = Score(source)
    before = summary(check(sc), len(sc.verticals))
    original_metrics = metrics(sc)
    source_score = Score(source)
    added = articulate_accompaniment(sc)
    if added:
        with tempfile.TemporaryDirectory() as tmp:
            prepared = Path(tmp) / 'prepared.musicxml'
            sc.write(prepared)
            sc = Score(prepared)
    search = Search(sc, radius=radius)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    prepared_hash = prepared_fingerprint(sc)
    if checkpoint is not None:
        if checkpoint.get('bron_sha256') != source_hash or checkpoint.get('voorbereiding_sha256') != prepared_hash:
            raise ValueError('hervatten geweigerd: bron of voorbereiding is gewijzigd')
        initial = {int(i): m for i, m in checkpoint.get('wijzigingen', {}).items()}
        if any(i not in search.mutable or m not in search.candidates[i] for i, m in initial.items()):
            raise ValueError('hervatten geweigerd: wijzigingen passen niet binnen de zoekruimte')
        search.values.update(initial)
        search.current = [search.evaluate(j, search.values) for j in range(len(search.v_ids))]
    original_names = {r.id: r.spitch.nameWithOctave for r in sc.recs}
    changes, search_report = search.solve(rounds=rounds, seed=seed, seconds=seconds,
        progress=lambda n, e, trials: print(f'  ronde {n}: zoekfouten={e}, kandidaten={trials}', flush=True) if n == 1 or n % 10 == 0 or e == 0 else None)
    apply(sc, changes)
    refresh(sc)
    # Spelling van de vaste melodie blijft intact, ook bij een ander akkoordlabel.
    fixed = [(n.obj, n.obj.pitch.nameWithOctave) for r in sc.recs if r.id in search.melody
             for n in [r] + list(getattr(r, 'tied', []))]
    respell(sc)
    for obj, name in fixed:
        obj.pitch = pitch.Pitch(name)
    refresh(sc)
    findings = check(sc)
    mark(sc, {i: original_names[i] for i in changes})
    for part in sc.parts.values():
        part.makeAccidentals(inPlace=True, overrideStatus=True, cautionaryPitchClass=False)
    sc.write(out, ' – hypercorrectie')
    exported = Score(out)
    findings = check(exported)
    after = summary(findings, len(exported.verticals))
    out.with_suffix('.txt').write_text('\n'.join(report_lines(findings)) + '\n')
    retained = preservation(source_score, exported)
    result = dict(instellingen=dict(algoritme=ALGORITHM, rounds=rounds, seed=seed, seconds=seconds, radius=radius, hervat=checkpoint is not None),
                  bron_sha256=source_hash, voorbereiding_sha256=prepared_hash, wijzigingen=changes,
                  status='volledig' if not findings and not search_report['zoekfouten'] and retained['geslaagd'] else 'onvolledig',
                  behoud=retained,
                  gewijzigd=len(changes), extra_aanslagen=len(sc.recs) - original_metrics['noten'], voor=before, na=after, zoektocht=search_report,
                  rijkheid_voor=original_metrics, rijkheid_na=metrics(exported))
    print(f'{source.stem}: {before["totaal"]} -> {after["totaal"]}, {result["status"]}', flush=True)
    return result


def write_report(results, path):
    lines = ['# Hypercorrectie', '',
             'De melodie blijft vast. Bas en binnenstemmen mogen veranderen. Liggende binnenstemmen',
             'kunnen gericht opnieuw worden aangeslagen. De meldingen hieronder zijn na export opnieuw',
             'berekend met de volledige formele regelcontrole.', '',
             '| Stuk | Voor | Na | Toonhoogtes gewijzigd | Extra aanslagen | Status |',
             '|---|---:|---:|---:|---:|---|']
    for name, r in sorted(results.items()):
        lines.append(f"| {name} | {r['voor']['totaal']} | {r['na']['totaal']} | "
                     f"{r['gewijzigd']} | {r['extra_aanslagen']} | {r['status']} |")
    lines += ['', '## Behoud van rijkheid en variatie', '',
              'De uitvoer moet per klank minstens evenveel toonklassen behouden. Daarnaast gelden',
              'ondergrenzen van 95% voor klankentropie, 90% voor het aantal basbewegingen,',
              '85% voor gemiddelde toonklasseovereenkomst (Jaccard) en 80% voor gelijke akkoordlabels.',
              'Dit zijn meetbare acceptatiecriteria, geen bewijs van artistieke kwaliteit.', '',
              '| Stuk | Klankentropie voor → na | Toonklasseovereenkomst | Gelijke akkoordlabels | Alle controles geslaagd |',
              '|---|---:|---:|---:|---|']
    for name, r in sorted(results.items()):
        b = r['behoud']
        lines.append(f"| {name} | {r['rijkheid_voor']['klankentropie']:.3f} → "
                     f"{r['rijkheid_na']['klankentropie']:.3f} | "
                     f"{100*b['toonklasseovereenkomst']:.1f}% | {100*b['gelijke_akkoordlabels']:.1f}% | "
                     f"{'ja' if b['geslaagd'] else 'nee'} |")
    lines += ['', 'De JSON bevat de afzonderlijke controles, zoekinstellingen en resterende regelcodes.',
              'Een begrensde zoektocht kan onvolledig eindigen. De melodie wordt dan niet losgelaten.', '']
    path.write_text('\n'.join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-dir', type=Path, default=DIR / 'midi')
    ap.add_argument('--output-dir', type=Path, default=DIR / 'midi_hypercorrectie')
    ap.add_argument('--only')
    ap.add_argument('--rounds', type=int, default=100)
    ap.add_argument('--seconds', type=float, default=300)
    ap.add_argument('--radius', type=int, default=36)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--resume', action='store_true', help='hervat een resultaat voor exact dezelfde bron')
    args = ap.parse_args()
    if args.rounds < 1 or not math.isfinite(args.seconds) or args.seconds <= 0 or args.radius < 1:
        ap.error('rounds, seconds en radius moeten positief zijn')
    if args.input_dir.resolve() == args.output_dir.resolve():
        ap.error('bron- en uitvoermap moeten verschillen')
    files = sorted(f for f in args.input_dir.glob('*.musicxml') if not args.only or args.only in f.name)
    if not files:
        ap.error('geen MusicXML-bestanden gevonden')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / 'hypercorrectie.json'
    results = json.loads(path.read_text()) if path.exists() else {}
    for source in files:
        results[source.stem] = run_file(source, args.output_dir / source.name, rounds=args.rounds,
                                       seed=args.seed, seconds=args.seconds, radius=args.radius,
                                       checkpoint=results.get(source.stem) if args.resume else None)
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
        write_report(results, args.output_dir / 'hypercorrectie.md')
    return 0 if all(results[f.stem]['status'] == 'volledig' for f in files) else 2


if __name__ == '__main__':
    raise SystemExit(main())
