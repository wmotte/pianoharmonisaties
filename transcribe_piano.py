#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Zet piano-mp3's om naar leesbare bladmuziek (MusicXML) + MIDI.

Stap 1: transcriptie naar ruwe MIDI -> midi_raw/
        --model transkun  : Transkun v2 (Yan & Duan 2024, https://github.com/yujia-yan/transkun)  [standaard]
        --model bytedance : High-resolution piano transcription (Kong et al. 2020)
Stap 2: opschonen voor MuseScore -> midi/*.musicxml en midi/*.mid  (alleen deze stap: --reclean)
        - beat-tracking op de audio (rubato rechtgetrokken), tempo genormaliseerd naar --tempo-range
        - raster automatisch gekozen (8sten / 16den / triolen) of vast via --grid
        - maatsoort (3/4 of 4/4) via autocorrelatie van het accentpatroon (of vast via --meter); 2/4 en 3/2
          zijn met --meter 2 resp. --meter 6 te forceren; maatstrepen via Viterbi-tracking, incl. opmaat en
          een enkele langere/kortere maat bij een fermate of vertraging
        - handverdeling: splitspunt volgt het register (lokale 2-means), per akkoord splitsen bij het grootste
          gat met max. handspanning en max. reikwijdte buiten de eigen balk (--leap); noten gaan naar de
          andere hand als die stil is; spooknoten-filter; sleutelwissel als een hand lang in het andere register speelt
        - per hand: akkoorden krijgen één lengte, kleine overlappen/gaatjes weggewerkt, max. 2 stemmen
          (alleen een doorklinkende bas of bovenstem als 2e stem)
        - te lange/korte maat door een aangehouden noot -> gewone maat met fermate (zoals in het boek)
        - rechterhand ver boven de balk -> 8va
        - slotakkoord tot einde maat + fermate; dynamiek (pp..ff) relatief uit aanslagsterkte (mediaan = mf)
        - coupletherkenning -> herhalingstekens (uit te zetten met --no-repeats)
        - spelling per verticaal: akkoord als stapeling van tertsen (B-D#-F#, niet B-Eb-F#), anders
          toonsoort/modus (in mineur de verhoogde 6e/7e trap als kruis); pedaaltekens optioneel (--pedal)
        - log per stuk o.a. maat, maat_hint (3/2?), syncopen (aandeel aanslagen op de halve tel)

Gebruik:  transcribe_piano.py [opties] mp3/*.mp3      (zie --help)
Open in MuseScore bij voorkeur het .musicxml-bestand (de .mid is voor afspelen).
"""
import argparse
import logging
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import librosa
import numpy as np
import pretty_midi
import torch
import json
import re
from music21 import (bar, chord, clef, dynamics, expressions, instrument, interval, key, layout, metadata, meter,
                     note,
                     pitch, spanner, stream, tempo)
from audio_segmentatie import (compute_cut_points, detect_silence_gaps,
                               split_audio_file, standard_section_labels)
from plak_partituren import stitch_midi, stitch_scores


DIR = Path(__file__).resolve().parent
RAW = DIR / "midi_raw"
OUT = DIR / "midi"
LOG = DIR / "midi.log"
NICE = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64]  # noteerbare lengtes in rastereenheden
DYNAMICS = ["pp", "p", "mp", "mf", "f", "ff"]  # relatief: de mediane aanslagsterkte van het stuk = mf
DYN_STEP = 10  # velocity-verschil per dynamiekstap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ================================================================ stap 1: transcriptie
def pick_device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


class Transcriber:
    def __init__(self, model: str, device: str):
        self.model_name = model
        self.device = device
        if model == "bytedance":
            from piano_transcription_inference import PianoTranscription
            self.model = PianoTranscription(device=torch.device(device))

    def __call__(self, mp3: Path, raw_path: Path):
        if self.model_name == "transkun":
            subprocess.run([str(DIR / ".venv/bin/transkun"), "--device", self.device, str(mp3), str(raw_path)],
                           check=True, capture_output=True, text=True)
        else:
            from piano_transcription_inference import sample_rate
            audio, _ = librosa.load(str(mp3), sr=sample_rate, mono=True)
            self.model.transcribe(audio, str(raw_path))


# ================================================================ stap 2a: tijdraster
def beat_grid(audio, sr, onsets, end, tempo_range):
    """Beat-tijdstippen (sec) over de hele opname, tempo binnen tempo_range, plus bpm."""
    bpm, beats = librosa.beat.beat_track(y=audio, sr=sr, units="time", trim=False)
    bpm = float(np.atleast_1d(bpm)[0])
    beats = np.asarray(beats, dtype=float)
    if len(beats) < 4:  # fallback: vast raster
        step = 60.0 / (bpm or 80.0)
        beats = np.arange(0.0, end + step, step)
    period = float(np.median(np.diff(beats)))

    def onset_fit(b):  # hoeveel aanslagen liggen dicht bij een beat?
        return np.mean(np.min(np.abs(onsets[:, None] - b[None, :]), axis=1) < 0.08 * period)

    while 60.0 / period > tempo_range[1]:  # te snel: om de andere beat weglaten (fase met de meeste aanslagen)
        a, b = beats[::2], beats[1::2]
        beats = a if onset_fit(a) >= onset_fit(b) else b
        period *= 2
    while 60.0 / period < tempo_range[0]:  # te langzaam: tussenbeats invoegen
        beats = np.sort(np.concatenate([beats, (beats[:-1] + beats[1:]) / 2]))
        period /= 2
    period = float(np.median(np.diff(beats)))
    pre = np.arange(beats[0] - period, -period, -period)[::-1]
    post = np.arange(beats[-1] + period, end + 2 * period, period)
    beats = np.concatenate([pre, beats, post])
    # fase-correctie: de beat-tracker loopt vaak iets achter/voor op de aanslagen; leg het raster op de aanslagen
    frac = np.interp(onsets, beats, np.arange(len(beats))) % 1.0
    phase = np.angle(np.mean(np.exp(2j * np.pi * frac))) / (2 * np.pi)  # circulair gemiddelde in [-0.5, 0.5)
    beats = beats + phase * period
    return beats, 60.0 / period


def choose_grid(onsets_beats: np.ndarray) -> int:
    """Kies 2 (8sten), 4 (16den) of 3 (triolen): het grofste raster waar de aanslagen goed op vallen."""
    frac = onsets_beats % 1.0

    def hit(divs, tol=0.08):
        pts = np.arange(divs + 1) / divs
        return float(np.mean(np.min(np.abs(frac[:, None] - pts[None, :]), axis=1) < tol))

    h2, h3, h4 = hit(2), hit(3), hit(4)
    if h4 - h2 < 0.25 and h3 - h2 < 0.25:  # minder dan een kwart van de aanslagen echt op 16den/triolen: 8sten
        return 2
    return 3 if h3 > h4 + 0.05 else 4


def nice_length(units: float) -> int:
    return max(1, min(NICE, key=lambda k: abs(k - units)))


def nice_floor(units: int) -> int:
    return max([k for k in NICE if k <= units] or [1])


# ================================================================ stap 2b: noten -> handen -> groepen
def local_split(pitch_times, split, window):
    """Per aanslagmoment een splitspunt tussen beide handen op basis van de toonhoogtes in de omgeving
    (2-means op alle noten binnen +/- window): laag register -> splitspunt zakt mee, en andersom."""
    times = np.array([t for t, _ in pitch_times])
    pitches = np.array([p for _, p in pitch_times], dtype=float)
    order = np.argsort(times)
    times, pitches = times[order], pitches[order]
    cache = {}

    def at(t):
        key = int(t // (window / 4))  # per kwart-venster hergebruiken
        if key in cache:
            return cache[key]
        lo, hi = np.searchsorted(times, t - window), np.searchsorted(times, t + window)
        ps = pitches[lo:hi]
        thr = split
        if len(ps) >= 8:
            c1, c2 = np.percentile(ps, 25), np.percentile(ps, 75)
            for _ in range(10):
                near1 = np.abs(ps - c1) <= np.abs(ps - c2)
                if near1.all() or not near1.any():
                    break
                c1, c2 = ps[near1].mean(), ps[~near1].mean()
            if c2 - c1 >= 10:  # twee registers: splits ertussen
                thr = float(np.clip((c1 + c2) / 2, 48, 72))
            else:  # één register: alles naar de hand waar het thuishoort
                thr = 0 if ps.mean() >= split else 128
        cache[key] = thr
        return thr

    return at


def assign_hands(notes, beats, grid, split, leap=7, max_span=14, min_gap=3):
    """Ruwe noten -> per hand {onset: {pitch: (duur, velocity)}} in rastereenheden.
    Per aanslagmoment wordt gesplitst bij het grootste toonhoogte-gat (als dat groot genoeg is en binnen
    het middengebied ligt); een compact akkoord gaat in zijn geheel naar één hand. Een hand mag hoogstens
    `leap` halve tonen buiten zijn eigen notenbalk grijpen (links t/m A3+leap, rechts t/m E4-leap), tenzij het
    lokale splitspunt zelf al verder ligt (beide handen in hetzelfde register)."""
    idx = np.arange(len(beats), dtype=float)
    to_units = lambda t: float(np.interp(t, beats, idx)) * grid

    by_on = defaultdict(list)
    for n in notes:
        if n.velocity < 15:  # vrijwel onhoorbaar: model-ruis
            continue
        raw = to_units(n.start)
        on = round(raw)
        dur = max(0.5, to_units(n.end) - on)
        by_on[on].append((n.pitch, dur, n.velocity, raw))

    if grid == 4:  # geïsoleerde off-16den (geen buur-aanslag een 16de verderop) zijn timing-ruis: naar 8sten
        for on in sorted(by_on):
            if on % 2 == 1 and (on - 1) not in by_on and (on + 1) not in by_on:
                target = int(round(np.mean([r for *_, r in by_on[on]]) / 2)) * 2
                by_on.setdefault(target, []).extend(by_on.pop(on))

    split_at = local_split([(on, p) for on, lst in by_on.items() for p, *_ in lst], split, window=8 * grid)
    hands = {"R": {}, "L": {}}
    for on, lst in by_on.items():
        pitches = sorted(p for p, _, _, _ in lst)
        split = split_at(on)  # lokaal splitspunt (kan 0/128 zijn: alles naar één hand)
        thr = split
        if 0 < split < 128:
            lh_max, rh_min = max(57 + leap, split), min(64 - leap, split)  # reikwijdte buiten de eigen balk
            best = None
            for j in range(len(pitches) - 1):  # kandidaat-splitsingen: gat j, beide clusters speelbaar
                lo, hi = pitches[:j + 1], pitches[j + 1:]
                gap = hi[0] - lo[-1]
                if gap < min_gap or lo[-1] - lo[0] > max_span or hi[-1] - hi[0] > max_span:
                    continue
                if lo[-1] > lh_max or hi[0] < rh_min:  # te ver buiten de eigen balk
                    continue
                if np.mean(lo) >= split + 4 or np.mean(hi) < split - 4:  # onderste cluster hoort links, bovenste rechts
                    continue
                cand = (lo[-1] + hi[0]) / 2
                score = gap - 0.3 * abs(cand - split)
                if best is None or score > best[0]:
                    best = (score, cand)
            if best is not None:
                thr = best[1]
            elif pitches[-1] - pitches[0] <= max_span:  # compact akkoord / losse noot: in zijn geheel naar één hand
                if pitches[-1] > lh_max:
                    thr = 0
                elif pitches[0] < rh_min:
                    thr = 128
                else:
                    thr = 0 if np.mean(pitches) >= split else 128
        for p, dur, vel, _ in lst:
            grp = hands["R" if p >= thr else "L"].setdefault(on, {})
            d0, v0 = grp.get(p, (0.0, 0))
            grp[p] = (max(d0, dur), max(v0, vel))
    return hands


def build_groups(groups: dict, grid: int, hand: str):
    """{onset: {pitch: (duur, vel)}} -> gesorteerde lijst [onset, lengte, [(pitch, vel), ...]].
    Blokakkoord-notatie: een aanslag duurt tot de volgende aanslag van dezelfde hand (kleine gaatjes
    worden legato dichtgemaakt, echte rusten van een beat of meer blijven staan). Alleen een losse
    basnoot in de linkerhand mag als tweede stem doorklinken onder volgende aanslagen."""
    onsets = sorted(groups)
    out = []
    for on in onsets:
        grp = groups[on]
        vmax = max(v for _, v in grp.values())
        if len(grp) > 1:  # spooknoten: veel zachter dan de rest van het akkoord
            grp = {p: dv for p, dv in grp.items() if dv[1] >= max(20, 0.3 * vmax)}
        dur = float(np.median([d for d, _ in grp.values()]))  # akkoord: één lengte
        if dur >= grid / 2:  # vanaf een halve beat: lengte op halve beats
            dur = round(dur / (grid / 2)) * (grid / 2)
        out.append([on, nice_length(dur), sorted((p, v) for p, (_, v) in grp.items())])

    sustained = None  # de ene noot die mag doorklinken (bas in de linkerhand, melodienoot in de rechter)
    for i, g in enumerate(out):
        if sustained is not None and sustained[0] + sustained[1] <= g[0]:
            sustained = None
        if i + 1 == len(out):
            break
        on, dur, pitches = g
        gap = out[i + 1][0] - on
        if dur > gap:  # overlapt de volgende aanslag
            p = pitches[0][0]
            under = [q for j in range(i + 1, len(out)) if out[j][0] < on + dur for q, _ in out[j][2]]
            outside = all(q > p for q in under) if hand == "L" else all(q < p for q in under)
            if len(pitches) == 1 and dur - gap >= grid and sustained is None and outside:
                sustained = g  # doorklinkende bas / bovenstem: laten staan als 2e stem
            else:
                g[1] = max(1, nice_floor(gap))
        elif dur < gap < dur + grid and gap in NICE:  # gaatje korter dan een beat: legato
            g[1] = gap
    return out


def rebalance(hands, split):
    """Verplaats noten naar de andere hand als die hand op dat moment niets speelt:
    - onderste noten (<= E4) van een rechterhand-akkoord naar links, bovenste (>= A3) van links naar rechts;
    - een doorklinkende losse noot onder/boven een nieuwe aanslag van dezelfde hand eveneens."""
    def sounding(groups, a, b):
        return any(on < b and on + dur > a for on, dur, _ in groups)

    for hand, other, keep_if in (("R", "L", lambda p: p > split + 4), ("L", "R", lambda p: p < split - 4)):
        mine, theirs = hands.get(hand, []), hands.get(other, [])
        moved = []
        for g in mine:
            on, dur, pitches = g
            if sounding(theirs, on, on + dur):
                continue
            keep = [pv for pv in pitches if keep_if(pv[0])]
            cand = [pv for pv in pitches if not keep_if(pv[0])]
            if not cand:
                continue
            if not keep and not any(o is not g and on < o[0] < on + dur for o in mine):
                continue  # losse noot zonder nieuwe aanslag eroverheen: laten staan
            g[2] = keep
            moved.append([on, dur, cand])
        if moved:
            hands[hand] = [g for g in mine if g[2]]
            hands[other] = sorted(theirs + moved, key=lambda g: g[0])
    return {h: g for h, g in hands.items() if g}


# ================================================================ stap 2c: maat, opmaat, couplet
def detect_meter(hands, grid, forced=0):
    """(maatsoort-teller, accent-signaal, hint).
    Per beat een accent-signaal (aantal aanslagen, nootlengtes, akkoordwisseling); de maatsoort volgt uit
    de autocorrelatie van dat signaal op 3+6 beats versus 4+8 beats. De hint is "3/2" als het signaal wel
    om de 6 tellen maar niet om de 3 tellen terugkomt (koraal in 3/2; met --meter 6 te forceren)."""
    end_units = max(on + dur for g in hands.values() for on, dur, _ in g)
    nb = int(end_units // grid) + 2
    cnt, durs, chroma = np.zeros(nb), np.zeros(nb), np.zeros((nb, 12))
    for groups in hands.values():
        for on, dur, pitches in groups:
            for b in range(on // grid, min(nb, -(-(on + dur) // grid))):
                for p, _ in pitches:
                    chroma[b, p % 12] += 1
            if on % grid == 0:
                cnt[on // grid] += len(pitches)
                durs[on // grid] += dur / grid
    change = np.zeros(nb)  # harmonische verandering t.o.v. vorige beat
    for b in range(1, nb):
        a, c = chroma[b - 1], chroma[b]
        if a.any() and c.any():
            change[b] = 1 - np.dot(a, c) / (np.linalg.norm(a) * np.linalg.norm(c))
    sig = cnt / (cnt.max() or 1) + durs / (durs.max() or 1) + 2 * change

    def autocorr(lag):
        x = sig - sig.mean()
        return float(np.dot(x[:-lag], x[lag:]) / (len(x) - lag) / x.var()) if x.var() > 0 and len(x) > lag else 0.0

    if forced:
        m = forced
        hint = ""
    else:
        # automatisch alleen 3/4 tegen 4/4 (autocorrelatie op de maat + twee maten). 2/4 en 3/2 zijn via
        # --meter te forceren: de autocorrelatie alleen is te zwak om die betrouwbaar te onderscheiden.
        s3, s4 = autocorr(3) + autocorr(6), autocorr(4) + autocorr(8)
        s6 = autocorr(6) + autocorr(12)
        m = 3 if s3 > s4 else 4
        # hint: sterke 6-periodiciteit zonder accent om de 3 tellen wijst op 3/2 (koraal) i.p.v. 3/4
        hint = "3/2" if s6 > max(s3, s4) + 0.10 and autocorr(3) < 0.05 else ""
    return m, sig, hint


def track_bars(sig, m, penalty=2.5):
    """Maatstrepen leggen (Viterbi): normaal om de m beats, maar een enkele maat mag m+1 of m-1 beats
    lang zijn (tegen straf) zodat een fermate/vertraging waar de beat-tracker een tel extra of te weinig
    telt, niet de rest van het stuk uit de maat gooit. Geeft de beat-indices van de tel-1's terug."""
    nb = len(sig)
    NEG = -1e18
    score = np.full((nb, m), NEG)
    back = np.zeros((nb, m, 2), dtype=int)  # (vorige pos, vorige beat)
    score[0, :] = np.where(np.arange(m) == 0, sig[0], 0.0)
    for b in range(1, nb):
        for pos in range(m):
            gain = sig[b] if pos == 0 else 0.0
            cands = [(score[b - 1, (pos - 1) % m], (pos - 1) % m)]  # normale stap
            if pos == m - 1:
                cands.append((score[b - 1, m - 1] - penalty, m - 1))  # maat van m+1 beats
            if pos == 0:
                cands.append((score[b - 1, m - 2] - penalty, m - 2))  # maat van m-1 beats
            best = max(cands)
            score[b, pos] = best[0] + gain
            back[b, pos] = (best[1], b - 1)
    pos = int(np.argmax(score[nb - 1]))
    downbeats = []
    for b in range(nb - 1, -1, -1):
        if pos == 0:
            downbeats.append(b)
        pos = back[b, pos][0] if b > 0 else pos
    return sorted(downbeats)


def normalise_bars(hands, bars, grid, m):
    """Een afwijkend lange/korte maat waarvan het einde een aangehouden noot (of rust) is, is in werkelijkheid
    een fermate of vertraging: maak de maat weer m tellen door die noot in te korten/te verlengen en zet er
    een fermate op. Maten met aanslagen tot aan het einde blijven staan. Geeft (fermates, warp) terug:
    fermates = [(hand, eind_in_units)], warp = lijst (cut, delta) om andere tijdstippen mee te verschuiven."""
    full = m * grid
    fermatas, warp = [], []
    i = 1 if len(bars) > 1 and bars[0][1] < bars[1][1] else 0  # opmaat overslaan
    while i < len(bars):
        start, length = bars[i]
        if length != full:
            end, delta = start + length, full - length  # delta > 0: tel toevoegen, < 0: tel weghalen
            onsets = [on for g in hands.values() for on, _, _ in g if start <= on < end]
            last_on = max(onsets) if onsets else start
            cut = end + min(delta, 0)
            if last_on < cut and (delta < 0 or end - last_on >= grid):  # staart zonder aanslagen
                for hand, groups in hands.items():
                    spanned, last = False, None  # last: laatste noot vóór de snede (als de staart een rust is)
                    for g in groups:
                        on, b = g[0], g[0] + g[1]
                        if on >= cut:
                            g[0] += delta
                        elif b > cut or (delta > 0 and b == cut):  # noot loopt door de snede: rekken/inkorten
                            g[1] = max(cut, b + delta) - on
                            fermatas.append((hand, on + g[1]))
                            spanned = True
                        elif b > start and (last is None or b > last):
                            last = b
                    if not spanned and last is not None:
                        fermatas.append((hand, last))
                warp.append((cut, delta))
                bars[i] = (start, full)
                for j in range(i + 1, len(bars)):
                    bars[j] = (bars[j][0] + delta, bars[j][1])
        i += 1
    return fermatas, warp


def find_verses(hands, bar_starts, min_len=8, thr=0.92):
    """Zoek een blok maten dat r >= 2 keer achter elkaar wordt herhaald. -> (start, lengte, r) of None."""
    starts = np.array(bar_starts)

    def bar_of(on):
        return int(np.searchsorted(starts, on, side="right") - 1)

    chroma = defaultdict(lambda: np.zeros(12))
    for groups in hands.values():
        for on, dur, pitches in groups:
            for p, _ in pitches:
                chroma[bar_of(on)][p % 12] += dur
    n = max(chroma) + 1
    C = np.zeros((n, 12))
    for b, v in chroma.items():
        C[b] = v / (np.linalg.norm(v) or 1)

    def sim(a, b, L):
        return float(np.mean(np.sum(C[a:a + L] * C[b:b + L], axis=1)))

    best = None
    for L in range(min_len, n // 2 + 1):
        for s in range(0, n - 2 * L + 1):
            r = 1
            while s + (r + 1) * L <= n and sim(s, s + r * L, L) >= thr:
                r += 1
            if r >= 2 and (best is None or r * L > best[1] * best[2]):
                best = (s, L, r)
    return best


# ================================================================ stap 2d: partituur
def clean_title(stem: str) -> str:
    t = stem.split(" - ", 1)[-1].rsplit(" [", 1)[0]
    return t.split("｜")[0].split("|")[0].strip().strip("'\"“”‘’")


def split_rests(container):
    """Rusten in leesbare stukken hakken die op de tel liggen (geen dubbel-gepunteerde rusten)."""
    for r in list(container.getElementsByClass(note.Rest)):
        off, dur = float(r.offset), float(r.quarterLength)
        if r.duration.dots <= 1 and dur in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0) and (off % min(dur, 1.0) == 0):
            continue
        container.remove(r)
        o = off
        while dur > 1e-6:
            piece = next((x for x in (4.0, 2.0, 1.0, 0.5, 0.25) if x <= dur + 1e-6 and o % x < 1e-6), dur)
            container.insert(o, note.Rest(quarterLength=piece))
            o += piece
            dur -= piece


FIFTHS = {"F": -1, "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5}


def fifths_index(p) -> int:
    """Positie van een gespelde toon op de kwintencirkel (F=-1, C=0, G=1, ...; kruis +7, mol -7)."""
    return FIFTHS[p.step] + 7 * int(p.accidental.alter if p.accidental is not None else 0)


def spell_pc(pc: int, tonic_idx: int) -> pitch.Pitch:
    """Toonsoort-spelling van een pitch class (zonder octaaf): de spelling met hoogstens één voorteken die op de
    kwintencirkel het dichtst bij de voortekening (tonic_idx = aantal kruisen) ligt, met 4 strafpunten voor
    mollen; bij gelijke stand de kleinste ruwe afstand."""
    cands = []
    for letter in "CDEFGAB":
        base = pitch.Pitch(letter).pitchClass
        alter = (pc - base + 6) % 12 - 6
        if abs(alter) <= 1:
            q = pitch.Pitch(letter)
            if alter:
                q.accidental = pitch.Accidental(alter)
            cands.append(q)
    cost = lambda q: abs(fifths_index(q) - tonic_idx) + (4 if q.accidental is not None and q.accidental.alter < 0 else 0)
    return min(cands, key=lambda q: (cost(q), abs(fifths_index(q) - tonic_idx)))


LETTERS = "CDEFGAB"
LETTER_STEP = {"maj": (0, 2, 4), "min": (0, 2, 4), "dom7": (0, 2, 4, 6), "maj7": (0, 2, 4, 6),
               "min7": (0, 2, 4, 6), "dim": (0, 2, 4), "dim7": (0, 2, 4, 6), "m7b5": (0, 2, 4, 6),
               "sus4": (0, 3, 4), "sus2": (0, 1, 4), "aug": (0, 2, 4)}
CHORD_TEMPLATES = {"maj": (0, 4, 7), "min": (0, 3, 7), "dom7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11),
                   "min7": (0, 3, 7, 10), "dim": (0, 3, 6), "dim7": (0, 3, 6, 9), "m7b5": (0, 3, 6, 10),
                   "sus4": (0, 5, 7), "sus2": (0, 2, 7), "aug": (0, 4, 8)}
INTERVAL_STEP = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 5, 9: 5, 10: 6, 11: 6}


def key_spell_pc(pc: int, k: key.Key) -> pitch.Pitch:
    """Toonsoort-spelling met modus: in mineur worden de verhoogde 6e en 7e trap (harmonisch/melodisch
    mineur) als kruis gespeld, zodat de leidtoon niet als mol verschijnt (E mineur: D#, niet Eb)."""
    if k.mode == "minor":
        for deg in (6, 7):
            p = k.tonic.transpose("M6" if deg == 6 else "M7")
            if p.pitchClass == pc:
                return pitch.Pitch(p.name)
    return spell_pc(pc, k.sharps)


def _spell_pair(midis, out, k):
    """Tweeklank als terts/vijfde spellen (B + D#, niet B + Eb). Kandidaten voor beide letters/voortekens;
    de diatonische toon van de toonsoort telt zwaar, daarna zo weinig mogelijk voortekens en mollen, en een
    terts boven een sext (zodat B-D# wint van Eb-B). Zijn beide tonen diatonisch, dan blijft de toonsoortspelling."""
    pcs = sorted({m % 12 for m in midis})
    if len(pcs) != 2:
        return
    scale_pcs = {p.pitchClass for p in k.getScale().getPitches()}
    if pcs[0] in scale_pcs and pcs[1] in scale_pcs:
        return  # beide diatonisch: de toonsoortspelling is al goed
    tonic_idx = k.sharps
    best = None
    for lo_pc, hi_pc in (pcs, pcs[::-1]):
        step = INTERVAL_STEP.get((hi_pc - lo_pc) % 12)
        if step is None:
            continue
        for lo_letter in LETTERS:
            for lo_alt in (0, -1, 1):
                if (pitch.Pitch(lo_letter).pitchClass + lo_alt) % 12 != lo_pc:
                    continue
                hi_letter = LETTERS[(LETTERS.index(lo_letter) + step) % 7]
                hi_alt = (hi_pc - pitch.Pitch(hi_letter).pitchClass + 6) % 12 - 6
                if abs(hi_alt) > 1:
                    continue
                lo = pitch.Pitch(lo_letter)
                if lo_alt:
                    lo.accidental = pitch.Accidental(lo_alt)
                hi = pitch.Pitch(hi_letter)
                if hi_alt:
                    hi.accidental = pitch.Accidental(hi_alt)
                diat = int(lo_pc in scale_pcs) + int(hi_pc in scale_pcs)
                n_acc = abs(lo_alt) + abs(hi_alt)
                fifths = sum(abs(fifths_index(q) - tonic_idx) + (4 if q.accidental and q.accidental.alter < 0 else 0)
                             for q in (lo, hi))
                cost = (-diat, n_acc, fifths, step)
                if best is None or cost < best[0]:
                    best = (cost, lo, hi)
    if best:
        out[best[1].pitchClass] = best[1]
        out[best[2].pitchClass] = best[2]


def spell_vertical(midis, k: key.Key) -> dict:
    """Spelling van alle klinkende noten van één verticaal (beide handen samen). Eerst wordt geprobeerd
    het akkoord als stapeling van tertsen te spellen (B-D#-F#, niet B-Eb-F#); lukt dat niet, dan de
    toonsoortspelling per toon, en bij een tweeklank de intervalspelling."""
    pcs = sorted({m % 12 for m in midis})
    out = {pc: key_spell_pc(pc, k) for pc in pcs}
    if len(pcs) == 1:
        return out
    pcs_set = set(pcs)
    chord = None
    for root in pcs:  # de grondtoon moet zelf klinken
        for name, tpl in CHORD_TEMPLATES.items():
            tones = [(root + s) % 12 for s in tpl]
            matched = sum(1 for t in tones if t in pcs_set)
            if matched < 3 or len(tones) - matched > 1:  # minstens een drieklank, hoogstens één ontbrekende
                continue
            score = (matched, -len(tones))
            if chord is None or score > chord[0]:
                chord = (score, root, name, tpl)
    if chord is None:
        if len(pcs) == 2:
            _spell_pair(midis, out, k)
        return out
    _, root, name, tpl = chord
    tonic_idx = k.sharps
    best = None
    for letter in LETTERS:  # grondtoonspelling met zo min mogelijk voortekens over het hele akkoord
        if abs((root - pitch.Pitch(letter).pitchClass + 6) % 12 - 6) > 1:
            continue
        spelled = []
        for semi, step in zip(tpl, LETTER_STEP[name]):
            L = LETTERS[(LETTERS.index(letter) + step) % 7]
            a = ((root + semi) - pitch.Pitch(L).pitchClass + 6) % 12 - 6
            p = pitch.Pitch(L)
            if a:
                p.accidental = pitch.Accidental(a)
            spelled.append(p)
        if any(p.accidental and abs(p.accidental.alter) > 1 for p in spelled):
            continue
        n_acc = sum(abs(p.accidental.alter) for p in spelled if p.accidental)
        root_p = spelled[0]
        cost = (n_acc, abs(fifths_index(root_p) - tonic_idx) + (4 if root_p.accidental and root_p.accidental.alter < 0 else 0))
        if best is None or cost < best[0]:
            best = (cost, spelled)
    if best:
        for p in best[1]:
            out[p.pitchClass] = p
    return out


KEY_PROFILES = {  # Krumhansl-Kessler toonsoortprofielen (zoals music21 ze gebruikt)
    "major": np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]),
    "minor": np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]),
}
KEYS = [key.Key(pitch.Pitch(pc).name if mode == "major" else pitch.Pitch(pc).name.lower(), mode)
        for mode in ("major", "minor") for pc in range(12)]
for _i, _k in enumerate(KEYS):  # nooit meer dan 6 voortekens: G# majeur (8#) -> As majeur (4b), enz.
    if abs(_k.sharps) > 6:
        KEYS[_i] = key.Key(_k.tonic.getEnharmonic().name if _k.mode == "major" else _k.tonic.getEnharmonic().name.lower(), _k.mode)


def key_segments(hands, grid, bars, window=6, min_len=16):
    """Toonsoort per deel: per maat een Krumhansl-Schmuckler-schatting over +/- window maten; korte uitschieters
    (< min_len maten) worden weggefilterd, zodat alleen echte modulaties een nieuwe voortekening geven.
    -> [(start_units, Key)]"""
    starts = np.array([b[0] for b in bars])
    hist = np.zeros((len(bars), 12))
    for groups in hands.values():
        for on, dur, pitches in groups:
            b = min(len(bars) - 1, max(0, int(np.searchsorted(starts, on, side="right")) - 1))
            for p, _ in pitches:
                hist[b, p % 12] += dur
    profiles = np.array([np.roll(KEY_PROFILES[k.mode], k.tonic.pitchClass) for k in KEYS])
    profiles = (profiles - profiles.mean(axis=1, keepdims=True)) / profiles.std(axis=1, keepdims=True)
    best = []
    for i in range(len(bars)):
        h = hist[max(0, i - window):i + window + 1].sum(axis=0)
        if h.std() == 0:
            best.append(best[-1] if best else None)
            continue
        corr = profiles @ ((h - h.mean()) / h.std())
        best.append(KEYS[int(np.argmax(corr))])
    first = next((k for k in best if k is not None), KEYS[0])
    best = [k if k is not None else first for k in best]
    sharps = [k.sharps for k in best]
    while True:  # runs korter dan min_len samenvoegen met de langste buur
        runs, i = [], 0
        while i < len(sharps):
            j = i
            while j < len(sharps) and sharps[j] == sharps[i]:
                j += 1
            runs.append((i, j))
            i = j
        short = [(j - i, n) for n, (i, j) in enumerate(runs) if j - i < min_len]
        if len(runs) == 1 or not short:
            break
        _, n = min(short)
        i, j = runs[n]
        nb = [runs[x] for x in (n - 1, n + 1) if 0 <= x < len(runs)]
        a, b = max(nb, key=lambda r: r[1] - r[0])
        sharps[i:j] = [sharps[a]] * (j - i)
    segments = []
    for i, j in runs:
        cands = [k for k in best[i:j] if k.sharps == sharps[i]]
        k_ = max(set(cands), key=cands.count) if cands else next(k for k in KEYS if k.sharps == sharps[i])
        segments.append((int(bars[i][0]), k_))
    return segments


def time_signature(length_units, grid):
    """Maatsoort bij een maatlengte in rastereenheden: 6 tellen = 3/2 (Koele noteert zijn koraal zo),
    de rest als n/4; een afwijkende maat door een fermate blijft n/4."""
    n = length_units // grid
    return "3/2" if n == 6 else f"{n}/4"


def build_score(hands, grid, bpm, m, bars, title, pedal_units, verses, fermatas=()):
    """bars: lijst (start_units, lengte_units); de eerste maat mag korter zijn (opmaat)."""
    pickup = bars[0][1] // grid if len(bars) > 1 and bars[0][1] < bars[1][1] else 0
    n_bars_units = bars[-1][0] + bars[-1][1]
    end_ql = n_bars_units / grid

    score = stream.Score()
    score.metadata = metadata.Metadata(title=title, composer="Gerrit Koele (automatische transcriptie)")
    parts, elems = [], {"R": {}, "L": {}}
    for hand, clf in (("R", clef.TrebleClef()), ("L", clef.BassClef())):
        part = stream.PartStaff()
        part.insert(0, instrument.Piano())
        part.insert(0, clf)
        prev = None
        for start, length in bars:  # maatsoort bij elke verandering van maatlengte (opmaat, extra tel bij fermate)
            if length != prev:
                part.insert(start / grid, meter.TimeSignature(time_signature(length, grid)))
                prev = length
        if hand == "R":
            part.insert(0, tempo.MetronomeMark(number=round(bpm)))
        groups = hands[hand]
        for i, (on, dur, pitches) in enumerate(groups):
            if i == len(groups) - 1:  # slotakkoord: tot einde maat + fermate
                dur = n_bars_units - on
            ql = dur / grid
            if len(pitches) == 1:
                el = note.Note(pitches[0][0], quarterLength=ql)
                el.volume.velocity = pitches[0][1]
            else:
                # via Pitch(midi=): Chord([68, 65]) zou 'harmonisch' spellen als G#-E# in plaats van G#-F
                el = chord.Chord([pitch.Pitch(midi=p) for p, _ in pitches], quarterLength=ql)
                el.volume.velocity = max(v for _, v in pitches)
            if i == len(groups) - 1:
                el.expressions.append(expressions.Fermata())
            part.insert(on / grid, el)
            elems[hand][on] = el
        parts.append(part)

    # toonsoort schatten op alle noten samen, en de spelling daarop afstemmen
    segments = key_segments(hands, grid, bars)  # [(start_units, Key)]: voortekening per (modulerend) deel
    seg_starts = [st for st, _ in segments]
    ks = " -> ".join(str(k_) for _, k_ in segments)
    for hand, part in zip(("R", "L"), parts):
        for start, k_ in segments:
            part.insert(start / grid, key.KeySignature(k_.sharps))
    # spelling per verticaal (alle klinkende noten van beide handen samen): eerst als akkoord (stapeling van
    # tertsen), anders volgens de toonsoort/modus. Zo wordt een B+D#-tussendominant als terts gespeld en niet
    # als B+Eb, en verschijnt een verhoogde leidtoon in mineur als kruis.
    notes_all = []
    for part in parts:
        for el in part.notes:
            on = float(el.offset) * grid
            k_ = segments[max(0, int(np.searchsorted(seg_starts, on, side="right")) - 1)][1]
            notes_all.append((on, on + float(el.quarterLength) * grid, el, k_))
    for on in sorted({round(a) for a, _, _, _ in notes_all}):
        sounding = [el for a, b, el, _ in notes_all if a <= on < b]
        if not sounding:
            continue
        k_ = next(k_ for a, _, _, k_ in notes_all if round(a) == on)
        spelling = spell_vertical([p.midi for el in sounding for p in el.pitches], k_)
        for el in sounding:
            if round(float(el.offset) * grid) != on:
                continue
            for p in el.pitches:
                if p.accidental is not None and p.accidental.alter == 0:
                    p.accidental = None
                best = spelling[p.pitchClass]
                if best.name != p.name:
                    p.step, p.accidental = best.step, best.accidental
    for hand, part in zip(("R", "L"), parts):
        part.makeVoices(inPlace=True, fillGaps=False)
        part.makeMeasures(inPlace=True, refStreamOrTimeRange=[0, end_ql])
        part.makeTies(inPlace=True)
        measures = list(part.getElementsByClass(stream.Measure))
        if pickup:  # opmaat: maatsoort van de volle maat al in maat 1 tonen
            ts_full = list(measures[1].getElementsByClass(meter.TimeSignature))
            if ts_full:
                measures[1].remove(ts_full[0])
                for ts in list(measures[0].getElementsByClass(meter.TimeSignature)):
                    measures[0].remove(ts)
                measures[0].insert(0, ts_full[0])
                measures[0].paddingLeft = bars[1][1] // grid - pickup
        for mm in measures:
            mm.flattenUnnecessaryVoices(inPlace=True)  # maat met maar één echte stem: geen lege 2e stem vol rusten
            span = [0.0, mm.barDuration.quarterLength - mm.paddingLeft]  # hele maat vullen (anders maakt de
            for i, v in enumerate(mm.voices, start=1):  # MusicXML-stemmen tellen vanaf 1   export onzichtbare rusten)
                v.id = i
                v.makeRests(refStreamOrTimeRange=span, fillGaps=True, inPlace=True)
                split_rests(v)
            if not mm.voices:
                mm.makeRests(refStreamOrTimeRange=span, fillGaps=True, inPlace=True)
                split_rests(mm)
        if hand == "R":  # 8va voor maten die ver boven de balk uitkomen (zoals in het boek)
            rng = (64, 77)
            ledger = lambda ps: sum(max(0, rng[0] - p, p - rng[1]) for p in ps) / 3.5
            run = []
            for mm in measures + [None]:
                ps = [p.midi for p in mm.pitches] if mm is not None else []
                if ps and max(ps) >= 84 and ledger(ps) - ledger([p - 12 for p in ps]) > 1:
                    run.append(mm)
                    continue
                if run:
                    els = [el for m2 in run for el in m2.recurse().notes]
                    for el in els:
                        el.transpose(interval.Interval("P-8"), inPlace=True)  # genoteerd een octaaf lager (P-8: spelling blijft)
                    ott = spanner.Ottava(type="8va", transposing=True)
                    ott.addSpannedElements(els)
                    part.insert(0, ott)
                    run = []
        part.makeAccidentals(inPlace=True, cautionaryPitchClass=False)

        for end_units_f in [e for h, e in fermatas if h == hand]:  # fermate op de (laatste gebonden) noot
            cands = [el for el in part.flatten().notes if abs(el.offset + el.quarterLength - end_units_f / grid) < 1e-6]
            if cands:
                max(cands, key=lambda el: el.offset).expressions.append(expressions.Fermata())
        # sleutelwissel als een hand minstens 2 maten lang duidelijk minder hulplijnen heeft in de andere sleutel
        other, back = (clef.BassClef, clef.TrebleClef) if hand == "R" else (clef.TrebleClef, clef.BassClef)
        own_rng, other_rng = ((64, 77), (43, 57)) if hand == "R" else ((43, 57), (64, 77))
        ledger = lambda ps, rng: sum(max(0, rng[0] - p, p - rng[1]) for p in ps) / 3.5  # ~1 hulplijn per 3,5 halve toon
        flags = []
        for mm in measures:
            ps = [p.midi for p in mm.pitches]
            flags.append(bool(ps) and ledger(ps, other_rng) + 1 < ledger(ps, own_rng))
        cur = False
        for i, mm in enumerate(measures):
            want = flags[i] and (i + 1 < len(flags) and flags[i + 1] or i > 0 and flags[i - 1] and cur)
            if want != cur and i > 0:
                mm.insert(0, (other if want else back)())
                cur = want
        if hand == "R":  # dynamiek uit aanslagsterkte, relatief t.o.v. het stuk (mediaan = mf), per maat
            bar_vel = [np.mean([el.volume.velocity for el in mm.recurse().notes if el.volume.velocity] or [np.nan])
                       for mm in measures]
            med = np.nanmedian(bar_vel)
            last = None
            for i, mm in enumerate(measures):
                window = [v for v in bar_vel[i:i + 4] if not np.isnan(v)]  # vooruitkijkend gemiddelde over 4 maten
                if not window or np.isnan(bar_vel[i]):
                    continue
                lvl = int(np.clip(3 + round((np.mean(window) - med) / DYN_STEP), 0, len(DYNAMICS) - 1))
                if last is None or (abs(lvl - last[0]) >= 2 and i - last[1] >= 2) or (lvl != last[0] and i - last[1] >= 8):
                    mm.insert(0, dynamics.Dynamic(DYNAMICS[lvl]))
                    last = (lvl, i)
        if hand == "L" and pedal_units:  # pedaaltekens (optioneel)
            for p_on, p_off in pedal_units:
                spanned = [el for on, el in elems["L"].items() if p_on <= on < p_off]
                if spanned:
                    pm = expressions.PedalMark()
                    pm.addSpannedElements(spanned)
                    part.insert(0, pm)
        score.insert(0, part)

    if verses:  # couplet: één keer noteren met herhalingstekens
        s, L, r = verses
        for part in parts:
            measures = list(part.getElementsByClass(stream.Measure))
            if s + r * L > len(measures):
                continue
            measures[s].leftBarline = bar.Repeat(direction="start")
            measures[s + L - 1].rightBarline = bar.Repeat(direction="end", times=r)
            part.remove(measures[s + L:s + r * L], shiftOffsets=True)
            for i, mm in enumerate(part.getElementsByClass(stream.Measure), start=1):
                mm.number = i
    score.insert(0, layout.StaffGroup(parts, name="Piano", abbreviation="Pno.", symbol="brace"))
    return score, ks


def write_midi(hands, grid, bpm, m, path):
    out = pretty_midi.PrettyMIDI(initial_tempo=bpm, resolution=480)
    sig = (3, 2) if m == 6 else (m, 4)  # 6 tellen = 3/2, net als in de partituur
    out.time_signature_changes.append(pretty_midi.TimeSignature(sig[0], sig[1], 0))
    spu = 60.0 / bpm / grid
    inst = pretty_midi.Instrument(program=0, name="Piano")  # één track: MuseScore maakt er zelf 2 balken van
    for groups in hands.values():
        for on, dur, pitches in groups:
            for p, v in pitches:
                inst.notes.append(pretty_midi.Note(velocity=int(v), pitch=int(p), start=on * spu, end=(on + dur) * spu))
    out.instruments.append(inst)
    out.write(str(path))


def clean_section(audio, sr, notes, args, forced_meter=0, title="Deel", pedal_events=None):
    onsets = np.array(sorted(n.start for n in notes))
    beats, bpm = beat_grid(audio, sr, onsets, max(n.end for n in notes), args.tempo_range)
    idx = np.arange(len(beats), dtype=float)
    grid = args.grid or choose_grid(np.interp(onsets, beats, idx))

    hands = assign_hands(notes, beats, grid, args.split, args.leap)
    hands = {h: build_groups(g, grid, h) for h, g in hands.items() if g}
    hands = rebalance(hands, args.split)
    if not hands:
        raise RuntimeError("geen noten over na filteren")
    m, sig, meter_hint = detect_meter(hands, grid, forced=forced_meter)
    downbeats = track_bars(sig, m)

    # maten: vanaf de eerste aanslag; wat vóór de eerste tel-1 zit wordt opmaat
    first_beat = min(on for g in hands.values() for on, _, _ in g) // grid
    end_beat = -(-max(on + dur for g in hands.values() for on, dur, _ in g) // grid)
    downbeats = [d for d in downbeats if d > first_beat]
    edges = [first_beat] + downbeats
    while edges[-1] < end_beat:
        edges.append(edges[-1] + m)
    shift = -first_beat * grid
    bars = [((a - first_beat) * grid, (b - a) * grid) for a, b in zip(edges, edges[1:])]
    for g in hands.values():
        for grp in g:
            grp[0] += shift
    fermatas, warp = normalise_bars(hands, bars, grid, m)  # fermate i.p.v. afwijkende maat waar dat kan
    irregular = sum(1 for _, ln in bars[1:] if ln != m * grid)
    pickup = bars[0][1] // grid if len(bars) > 1 and bars[0][1] < bars[1][1] else 0

    def to_units(t):  # seconde -> rastereenheid in de partituur
        u = float(np.interp(t, beats, idx)) * grid + shift
        for cut, delta in warp:
            u = u + delta if u >= cut else u
        return u

    pedal_units = None
    if args.pedal and pedal_events:
        pedal_units, down = [], None
        for cc in sorted(pedal_events, key=lambda c: c.time):
            if cc.value >= 64 and down is None:
                down = cc.time
            elif cc.value < 64 and down is not None:
                pedal_units.append((round(to_units(down)), round(to_units(cc.time))))
                down = None
    verses = None if args.no_repeats else find_verses(hands, [b[0] for b in bars])

    score, ks = build_score(hands, grid, bpm, m, bars, title, pedal_units, verses, fermatas)
    n_groups = sum(len(g) for g in hands.values())
    offbeat = sum(1 for g in hands.values() for on, _, _ in g if on % grid) / max(n_groups, 1)  # aanslagen op de halve tel
    info = dict(noten=len(notes), R=sum(len(p) for _, _, p in hands.get("R", [])),
                L=sum(len(p) for _, _, p in hands.get("L", [])), bpm=round(bpm), raster=f"1/{grid * 4}",
                maat=time_signature(m * grid, grid), opmaat=pickup, fermates=len(fermatas),
                afwijkende_maten=irregular, toonsoort=ks, maat_hint=meter_hint or "-",
                syncopen=f"{round(100 * offbeat)}%",
                couplet=f"maat {verses[0] + 1}-{verses[0] + verses[1]} x{verses[2]}" if verses else "-")
    return {
        "score": score,
        "bpm": bpm,
        "m": m,
        "grid": grid,
        "hands": hands,
        "ks": ks,
        "bars": bars,
        "fermatas": fermatas,
        "info": info,
    }


def clean(mp3: Path, raw_path: Path, args):
    pm = pretty_midi.PrettyMIDI(str(raw_path))
    notes = [n for inst in pm.instruments for n in inst.notes]
    if not notes:
        raise RuntimeError("geen noten in transcriptie")
    audio, sr = librosa.load(str(mp3), sr=22050, mono=True)
    audio_dur = len(audio) / sr

    # Controleer splits.json configuratie
    splits_cfg = None
    cfg_path = DIR / "splits.json"
    if cfg_path.exists():
        try:
            all_splits = json.loads(cfg_path.read_text())
            for k, v in all_splits.items():
                if k in mp3.name:
                    splits_cfg = v
                    break
        except Exception as e:
            log.warning("Kon splits.json niet laden: %s", e)

    should_split = getattr(args, "split_sections", False) or bool(getattr(args, "splits", "")) or (splits_cfg is not None and getattr(args, "split_sections", False))

    sections = None
    labels = None
    meters = None

    if should_split:
        if getattr(args, "splits", ""):
            cuts = [float(x.strip()) for x in args.splits.split(",") if x.strip()]
            edges = [0.0] + cuts + [round(audio_dur, 3)]
            sections = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
        elif splits_cfg and "splits" in splits_cfg:
            cuts = [float(x) for x in splits_cfg["splits"]]
            edges = [0.0] + cuts + [round(audio_dur, 3)]
            sections = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
            labels = splits_cfg.get("labels")
            meters = splits_cfg.get("meters")
        else:
            min_silence = getattr(args, "min_silence", 1.0)
            silence_db = getattr(args, "silence_db", 30.0)
            min_dur = getattr(args, "min_dur", 10.0)
            gaps, dur = detect_silence_gaps(mp3, min_silence=min_silence, top_db=silence_db)
            sections = compute_cut_points(gaps, dur, min_section_dur=min_dur)

        if getattr(args, "meters", ""):
            meters = [int(x.strip()) for x in re.split(r"[, ]+", args.meters.strip()) if x.strip()]

    # Indien meerdere secties gevonden: verwerk per sectie en voeg samen
    if should_split and sections and len(sections) > 1:
        if labels is None or len(labels) != len(sections):
            labels = standard_section_labels(len(sections))
        if meters is None or len(meters) != len(sections):
            meters = [args.meter] * len(sections)

        log.info("   -> Opsplitsing in %d secties (%s)", len(sections), ", ".join(labels))
        sections_info = []
        for idx, ((st, et), lbl, m_forced) in enumerate(zip(sections, labels, meters)):
            sec_audio = audio[int(st * sr):int(et * sr)]
            sec_notes = [
                pretty_midi.Note(velocity=n.velocity, pitch=n.pitch, start=n.start - st, end=n.end - st)
                for n in notes if st <= n.start < et
            ]
            if not sec_notes:
                log.warning("      Geen noten in sectie %s (%.1f-%.1fs), overgeslagen", lbl, st, et)
                continue

            pedal_ev = [
                pretty_midi.ControlChange(number=c.number, value=c.value, time=c.time - st)
                for i in pm.instruments for c in i.control_changes
                if c.number == 64 and st <= c.time < et
            ] if args.pedal else None

            sec_res = clean_section(
                sec_audio, sr, sec_notes, args,
                forced_meter=m_forced, title=lbl, pedal_events=pedal_ev
            )
            sec_res["label"] = lbl
            sections_info.append(sec_res)
            log.info(
                "      Sectie %s: %s, bpm=%d, syncopen=%s, afwijkende_maten=%d",
                lbl, sec_res["info"]["maat"], sec_res["info"]["bpm"],
                sec_res["info"]["syncopen"], sec_res["info"]["afwijkende_maten"]
            )

        if getattr(args, "save_parts", False):
            mp3_out = DIR / "mp3_delen" / mp3.stem
            split_audio_file(mp3, sections, mp3_out, labels)
            xml_out = DIR / "midi_delen" / mp3.stem
            xml_out.mkdir(parents=True, exist_ok=True)
            for s_info in sections_info:
                s_xml = xml_out / f"{s_info['label']}.musicxml"
                s_info["score"].write("musicxml", fp=str(s_xml))

        title = clean_title(mp3.stem)
        combined_score = stitch_scores(sections_info, title)
        xml_path = OUT / f"{mp3.stem}.musicxml"
        combined_score.write("musicxml", fp=str(xml_path))
        xml_path.write_text(xml_path.read_text().replace('<note print-object="no" print-spacing="yes">', "<note>"))

        stitch_midi(sections_info, OUT / f"{mp3.stem}.mid")

        total_notes = sum(s["info"]["noten"] for s in sections_info)
        total_fermatas = sum(s["info"]["fermates"] for s in sections_info)
        total_irreg = sum(s["info"]["afwijkende_maten"] for s in sections_info)
        sec_summary = " -> ".join(f"{s['label']} ({s['info']['maat']})" for s in sections_info)
        info = dict(
            secties=len(sections_info),
            vorm=sec_summary,
            noten=total_notes,
            fermates=total_fermatas,
            afwijkende_maten=total_irreg,
        )
        return info

    # Reguliere verwerking (geen splitsing)
    pedal_ev = [
        c for i in pm.instruments for c in i.control_changes if c.number == 64
    ] if args.pedal else None

    title = clean_title(mp3.stem)
    res = clean_section(audio, sr, notes, args, forced_meter=args.meter, title=title, pedal_events=pedal_ev)
    xml_path = OUT / f"{mp3.stem}.musicxml"
    res["score"].write("musicxml", fp=str(xml_path))
    xml_path.write_text(xml_path.read_text().replace('<note print-object="no" print-spacing="yes">', "<note>"))
    write_midi(res["hands"], res["grid"], res["bpm"], res["m"], OUT / f"{mp3.stem}.mid")
    return res["info"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--model", choices=["transkun", "bytedance"], default="transkun")
    ap.add_argument("--grid", type=int, default=0, help="onderverdelingen per beat: 2 = 8sten, 4 = 16den, 3 = triolen (0 = automatisch)")
    ap.add_argument("--split", type=int, default=60, help="basis-toonhoogte voor de handverdeling (60 = centrale C)")
    ap.add_argument("--leap", type=int, default=7, help="max. halve tonen dat een hand buiten zijn eigen notenbalk grijpt (links boven A3, rechts onder E4)")
    ap.add_argument("--meter", type=int, default=0, choices=[0, 2, 3, 4, 6], help="maatsoort-teller: 2, 3, 4 of 6 tellen (= 3/2) (0 = automatisch)")
    ap.add_argument("--tempo-range", type=int, nargs=2, default=[60, 120], metavar=("MIN", "MAX"))
    ap.add_argument("--no-repeats", action="store_true", help="geen coupletherkenning / herhalingstekens")
    ap.add_argument("--pedal", action="store_true", help="pedaaltekens uit de transcriptie overnemen")
    ap.add_argument("--split-sections", action="store_true", help="automatisch stiltes detecteren en opsplitsen in voorspel/koraal/naspel")
    ap.add_argument("--min-silence", type=float, default=1.0, help="minimale stilte in sec voor sectiegrens (standaard: 1.0)")
    ap.add_argument("--silence-db", type=float, default=30.0, help="stilte-drempel in dB onder piek (standaard: 30)")
    ap.add_argument("--min-dur", type=float, default=10.0, help="minimale sectieduur in sec (standaard: 10)")
    ap.add_argument("--splits", type=str, default="", help="handmatige snijpunten in seconden (bijv. '64.18,144.82')")
    ap.add_argument("--meters", type=str, default="", help="handmatige maatsoorten per sectie (bijv. '4,6,4')")
    ap.add_argument("--save-parts", action="store_true", help="sla ook de losse mp3's en partituren op in mp3_delen/ en midi_delen/")
    ap.add_argument("--force", action="store_true", help="alles opnieuw maken (ook de ruwe transcriptie)")
    ap.add_argument("--reclean", action="store_true", help="alleen stap 2 opnieuw doen, ruwe transcriptie hergebruiken")
    args = ap.parse_args()

    RAW.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    device = pick_device()
    log.info("=== Start: %d bestanden, model=%s, device=%s, grid=%s, split=%d, maat=%s ===",
             len(args.files), args.model, device, args.grid or "auto", args.split, args.meter or "auto")
    transcribe = Transcriber(args.model, device)

    ok = skip = fail = 0
    for mp3 in args.files:
        raw_path = RAW / f"{mp3.stem}.{args.model}.mid"
        if (OUT / f"{mp3.stem}.musicxml").exists() and not (args.force or args.reclean):
            skip += 1
            continue
        log.info("-> %s", mp3.stem)
        t0 = time.time()
        try:
            if not raw_path.exists() or args.force:
                transcribe(mp3, raw_path)
            info = clean(mp3, raw_path, args)
            log.info("   OK: %s, %.0fs", ", ".join(f"{k}={v}" for k, v in info.items()), time.time() - t0)
            ok += 1
        except Exception as e:  # één mislukking mag de rest niet stoppen
            log.exception("   FOUT: %s", e)
            fail += 1

    log.info("=== Klaar: %d omgezet, %d overgeslagen (bestond al), %d mislukt ===", ok, skip, fail)


if __name__ == "__main__":
    main()
