"""Zet de bronnen in bron/*.py om naar MuseScore (.mscz) en PDF.

Draai vanuit een liedmap (bron/, uitvoer naar musescore/, pdf/, tmp/). Elke bron definieert STUK met secties.
Akkoordsymbolen boven de piano volgen de gekozen "akkoorden" en de werkelijk gezette bas, inclusief
omkeringen. Binnen een maat verschijnen alleen nieuwe harmonieën; iedere maat herhaalt het geldende akkoord.
Per sectie:

    "melodie"    de zangmelodie (eigen balk, met tekst)
    "tegenstem"  optioneel: tegenstem/bovenstem (eigen balk boven de melodie)
    "1" .. "4"   pianozetting: bovenbalk 1+2 (sopraan, alt), onderbalk 3+4 (tenor, bas).
                 "1" mag ontbreken: dan speelt de sopraan precies de melodie.
    "tekst"      lijst tekstregels bij de melodie

Notatie per stem:

    Bb3/4   noot (stap, voorteken # b n, octaaf, /duur met punten, 't' = triool: /8t)
            zonder voorteken geldt de voortekening; duur blijft staan tot hij wijzigt
    R/4     rust
    ~       achter een noot: overbinden naar de volgende
    ^       achter een noot: fermate
    M6/4    vooraan in een maat: maatwissel (alleen in "melodie" nodig, geldt voor alle balken)
    |  ||  :|  |:  |]   maatstreep, dubbele streep, herhaling, slotstreep

Optioneel in een sectie: "opmaat" (eerste maat is een opmaat), "kop" (tekst boven de eerste maat),
"tempo" (kwarten per minuut), "voltas" ({maatindex binnen sectie: "1."} of {maatindex: ("1.", aantal_maten)};
meerdere keren als "1.2.3.4."), "teksten" ({maatindex: "D.S."}).
Optioneel in STUK: "regels"/"paginas" (maatnummers met nieuwe regel/pagina; pagina's worden daarnaast
automatisch uitgebalanceerd, zie balanceer_paginas()), "ondertitel", "componist",
"spatium" (kleinere notenbalk, standaard 1.75), "linkerhand": "gebroken" (popballad: gebroken akkoorden in de linkerhand in plaats van tenor + bas, zie vul()),
"begeleiding": "akkoorden" (maten met zang: rechts alleen akkoorden zonder melodie, links de bas; voor-, tussen- en
naspel houden de melodie, zie akkoordbegeleiding()).

Tekstregels: lettergrepen gescheiden door spaties, 'ge-' koppelt aan de volgende lettergreep,
'_' slaat een noot over, '~' wordt een spatie.

Gebruik (vanuit de liedmap): ../.venv/bin/python ../koele/maak_partituren.py [naam ...] [--alleen-xml] [--zonder-controle]
"""

import copy
import importlib.util
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction
from pathlib import Path

from music21 import (articulations, bar, chord, clef, duration, expressions, harmony, instrument, key, layout, metadata, meter, note, pitch,
                     repeat, spanner, stream, tempo, tie)

HIER = Path(__file__).resolve().parent
ROOT = Path.cwd()  # de liedmap (bijv. muziekgroep_11_oct/) met bron/; scripts draaien vanuit die map
MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"
PIANO = ["1", "2", "3", "4"]

NOOT = re.compile(r"^([A-G])(##|bb|#|b|n)?(\d)(?:/(\d+)(\.*)(t?))?([~^]*)$")
RUST = re.compile(r"^R(?:/(\d+)(\.*)(t?))?$")
MAAT = re.compile(r"^M(\d+/\d+)$")
ALTER = {"##": 2, "#": 1, "n": 0, "b": -1, "bb": -2}
STREPEN = ("|", "||", ":|", "|:", "|]", ":|:")


def ql(dur, dots, triool):
    q = Fraction(4, int(dur)) * (2 - Fraction(1, 2 ** len(dots)))
    return q * Fraction(2, 3) if triool else q


def parse_stem(tekst, ks):
    """Geeft lijst van maten; elke maat = dict(elems, streep, maat)."""
    maten, huidig, dur, ts = [], [], Fraction(1), None
    for tok in tekst.split():
        if tok in STREPEN:
            maten.append(dict(elems=huidig, streep=tok, maat=ts))
            huidig, ts = [], None
            continue
        if m := MAAT.match(tok):
            ts = m.group(1)
            continue
        if m := RUST.match(tok):
            if m.group(1):
                dur = ql(m.group(1), m.group(2), m.group(3))
            huidig.append(("rust", None, dur, ""))
            continue
        m = NOOT.match(tok)
        if not m:
            raise ValueError(f"onbekend token {tok!r}")
        stap, acc, octaaf, d, dots, triool, mods = m.groups()
        if d:
            dur = ql(d, dots, triool)
        acc_ks = ks.accidentalByStep(stap)
        alter = ALTER[acc] if acc else (acc_ks.alter if acc_ks else 0)
        huidig.append(("noot", (stap, int(alter), int(octaaf)), dur, mods))
    if huidig:
        maten.append(dict(elems=huidig, streep="|", maat=ts))
    return maten


def lettergrepen(regel):
    uit = []
    for tok in regel.split():
        if tok == "_":
            uit.append(None)
            continue
        verder = tok.endswith("-") and len(tok) > 1
        uit.append((tok.rstrip("-").replace("~", " ") if verder else tok.replace("~", " "), verder))
    return uit


def maak_noot(elem):
    soort, p, dur, mods = elem
    if soort == "rust":
        n = note.Rest()
    else:
        stap, alter, octaaf = p
        n = note.Note()
        n.pitch.step = stap
        n.pitch.octave = octaaf
        if alter:
            n.pitch.accidental = alter
        if "^" in mods:
            n.expressions.append(expressions.Fermata())
    n.duration = duration.Duration(dur)
    return n


def stemmen_van(sec, ks):
    namen = ["melodie"] + (["tegenstem"] if "tegenstem" in sec else []) + PIANO
    bron = {s: sec.get(s, sec["melodie"]) for s in namen}
    return {s: parse_stem(bron[s], ks) for s in namen}


def sectie_maten(stuk, sec, ks):
    """Parse en valideer een sectie; geeft (stemmen, maatsoort per maat, lengte per maat)."""
    stemmen = stemmen_van(sec, ks)
    aantal = {s: len(v) for s, v in stemmen.items()}
    if len(set(aantal.values())) != 1:
        raise ValueError(f"{stuk['titel']} / {sec.get('kop', '')}: ongelijk aantal maten {aantal}")
    nmaten = aantal["melodie"]
    huidig = sec["maat"]
    maatsoorten, lengtes = [], []
    for i in range(nmaten):
        huidig = stemmen["melodie"][i]["maat"] or huidig
        maatsoorten.append(huidig)
        lens = {s: sum(e[2] for e in stemmen[s][i]["elems"]) for s in stemmen}
        if len(set(lens.values())) != 1:
            raise ValueError(f"{stuk['titel']} / {sec.get('kop', '')} maat {i + 1}: stemduren verschillen "
                             f"{ {s: str(v) for s, v in lens.items()} }")
        lengtes.append(lens["melodie"])
    return stemmen, maatsoorten, lengtes


def bouw_sectie(stuk, sec, startnummer, laatste, vorige_maat, met_zang):
    """Geeft lijsten maten per balk: tegenstem (of None), zang, bovenbalk, onderbalk."""
    fifths = sec["toonsoort"]
    ks = key.KeySignature(fifths)
    stemmen, maatsoorten, lengtes = sectie_maten(stuk, sec, ks)
    heeft_tegen = "tegenstem" in stemmen and met_zang
    balk_stemmen = ([["tegenstem"]] if heeft_tegen else []) + ([["melodie"]] if met_zang else []) + [
        ["1", "2"], ["3", "4"]]
    balken = [[] for _ in balk_stemmen]
    tekst = [lettergrepen(r) for r in sec.get("tekst", [])]
    nmaten = len(lengtes)
    for i in range(nmaten):
        ts_str = maatsoorten[i]
        volle = meter.TimeSignature(ts_str).barDuration.quarterLength
        lengte = lengtes[i]
        opmaat = i == 0 and sec.get("opmaat")
        if lengte != volle and not opmaat and not (laatste and i == nmaten - 1):
            raise ValueError(f"{stuk['titel']} maat {startnummer + i}: duur {lengte} past niet in {ts_str}")
        for b, namen in enumerate(balk_stemmen):
            m = stream.Measure(number=startnummer + i)
            if i == 0:
                m.insert(0, key.KeySignature(fifths))
            if ts_str != (maatsoorten[i - 1] if i else vorige_maat):
                m.insert(0, meter.TimeSignature(ts_str))
            if opmaat:
                m.paddingLeft = float(volle - lengte)
            elif lengte != volle:
                m.paddingRight = float(volle - lengte)
            for v, s in enumerate(namen):
                voice = stream.Voice(id=str(v + 1))
                for elem in stemmen[s][i]["elems"]:
                    n = maak_noot(elem)
                    if len(namen) == 2 and not n.isRest:
                        n.stemDirection = "up" if v == 0 else "down"
                    voice.append(n)
                m.insert(0, voice)
            slot = stemmen["melodie"][i]["streep"]
            if slot == "||":
                m.rightBarline = bar.Barline("double")
            elif slot in (":|", ":|:"):
                m.rightBarline = bar.Repeat(direction="end")
            elif slot == "|]" or (laatste and i == nmaten - 1):
                m.rightBarline = bar.Barline("final")
            if i > 0 and stemmen["melodie"][i - 1]["streep"] in ("|:", ":|:"):
                m.leftBarline = bar.Repeat(direction="start")
            elif i == 0 and sec.get("herhaal_begin"):
                m.leftBarline = bar.Repeat(direction="start")
            balken[b].append(m)

    # overbindingen per stem
    for b, namen in enumerate(balk_stemmen):
        for v, s in enumerate(namen):
            noten = [n for m in balken[b] for n in m.voices[v].notesAndRests]
            elems = [e for maat in stemmen[s] for e in maat["elems"]]
            for k, (n, e) in enumerate(zip(noten, elems)):
                if "~" in e[3]:
                    n.tie = tie.Tie("start") if not (n.tie and n.tie.type == "stop") else tie.Tie("continue")
                    noten[k + 1].tie = tie.Tie("stop")

    # tekst bij de melodie (zangbalk, of bij ontbreken daarvan de sopraan)
    zb = balk_stemmen.index(["melodie"]) if met_zang else balk_stemmen.index(["1", "2"])
    noten = [n for m in balken[zb] for n in m.voices[0].notesAndRests]
    pos = [0] * len(tekst)
    koppel = {}
    for n in noten:
        if n.isRest or (n.tie and n.tie.type in ("stop", "continue")):
            continue
        for vi, greep in enumerate(tekst):
            if pos[vi] >= len(greep):
                continue
            g = greep[pos[vi]]
            pos[vi] += 1
            if g is None:
                continue
            n.addLyric(g[0], lyricNumber=vi + 1)
            koppel[id(n.lyrics[-1])] = g[1]
    for vi, greep in enumerate(tekst):
        if pos[vi] != len(greep):
            raise ValueError(f"{stuk['titel']} / {sec.get('kop', '')}: tekstregel {vi + 1} heeft {len(greep)} "
                             f"lettergrepen, {pos[vi]} noten gebruikt")
        vorig = False
        for n in noten:
            lyr = next((x for x in n.lyrics if x.number == vi + 1), None)
            if lyr is None:
                continue
            verder = koppel[id(lyr)]
            lyr.syllabic = {(False, False): "single", (False, True): "begin",
                            (True, True): "middle", (True, False): "end"}[(vorig, verder)]
            vorig = verder

    bovenste = balken[0]
    if sec.get("tempo"):
        mm = tempo.MetronomeMark(number=sec["tempo"], referent=note.Note(type="quarter"))
        bovenste[0].insert(0, mm)
    if sec.get("kop"):
        if re.fullmatch(r"[A-Z]", sec["kop"]):
            label = expressions.RehearsalMark(sec["kop"])
        else:
            label = expressions.TextExpression(sec["kop"])
        bovenste[0].insert(0, label)
    for idx, txt in sec.get("teksten", {}).items():
        te = expressions.TextExpression(txt)
        bovenste[idx].insert(bovenste[idx].highestTime if txt.startswith(("D.S", "D.C", "Fine")) else 0, te)
    for idx, volta in sec.get("voltas", {}).items():
        # {maatindex: "1."} of {maatindex: ("1.", aantal_maten)}; meerdere keren als "1.2.3.4."
        nummer, lengte = (volta, 1) if isinstance(volta, str) else volta
        nummers = [int(n) for n in nummer.split(".") if n]
        nummer = str(nummers[0]) if len(nummers) == 1 else f"{nummers[0]}-{nummers[-1]}"
        for b in balken:
            rb = spanner.RepeatBracket(b[idx:idx + lengte], number=nummer)
            b[idx].insert(0, rb)
    if sec.get("segno") is not None:
        bovenste[sec["segno"]].insert(0, repeat.Segno())
    return balken, heeft_tegen, maatsoorten[-1]


OCTAAF_MIN = 31  # G1: lager wordt een linkerhandoctaaf te dof
SPAN = 12  # maximale greep per hand
RH_MIN = 53  # F3: lagere tenor blijft in de linkerhand (anders veel hulplijnen onder de vioolsleutel)


def _maten(staf):
    return list(staf.getElementsByClass(stream.Measure))


def _stem(m, vid):
    return next((v for v in m.voices if v.id == vid), None)


def _tie(n):
    return n.tie.type if n.tie else None


def gitaarakkoorden(stuk, boven):
    """Akkoordsymbolen boven de piano uit de gekozen harmonie en de werkelijk gezette bas.

    Iedere maat krijgt een akkoord bij de eerste klinkende harmonie. Binnen de maat alleen opnieuw
    bij een andere harmonie of omkering; doorgangen in de melodie en arpeggio's geven geen extra symbolen.
    Een '=' loopt door, 'R' onderbreekt de harmonie. Symbolen voegen geen speelnoten toe.
    """
    import zetter

    maten = iter(_maten(boven))
    huidig = None
    for sec in stuk["secties"]:
        ks = key.KeySignature(sec["toonsoort"])
        basmaten = parse_stem(sec["4"], ks)
        if "akkoorden" not in sec:
            # Uitgeschreven stemmen zonder akkoordplan vragen een afzonderlijke harmonische analyse.
            for _ in basmaten:
                next(maten)
            huidig = None
            continue
        akkmaten = zetter.parse_akkoorden(sec["akkoorden"])
        if len(akkmaten) != len(basmaten):
            raise ValueError(f"{stuk['titel']}: akkoordmaten en basmaten verschillen")
        for akkm, basm in zip(akkmaten, basmaten):
            m = next(maten)
            offset, vorig = Fraction(0), None
            for sym, dur in akkm:
                if sym == "R":
                    if huidig is not None:
                        nc = harmony.NoChord()
                        nc.placement = "above"
                        m.insert(offset, nc)
                    huidig, vorig = None, None
                else:
                    if sym != "=":
                        huidig = sym.partition(":")[0]
                    if huidig is None:
                        raise ValueError(f"{stuk['titel']} maat {m.number}: '=' zonder vorig akkoord")
                    tijd, bas = Fraction(0), None
                    for soort, p, duur, _ in basm["elems"]:
                        if tijd <= offset < tijd + duur:
                            if soort == "noot":
                                bas = maak_noot((soort, p, duur, "")).pitch
                            break
                        tijd += duur
                    if bas is None:
                        raise ValueError(f"{stuk['titel']} maat {m.number}: akkoord zonder klinkende bas")
                    figuur = re.sub(r"^([A-G])b", r"\1-", huidig)
                    cs = harmony.ChordSymbol(figuur)
                    if bas.pitchClass != cs.root().pitchClass:
                        cs = harmony.ChordSymbol(f"{figuur}/{bas.name}")
                    if cs.figure != vorig:
                        cs.placement = "above"
                        cs.writeAsChord = False
                        m.insert(offset, cs)
                    vorig = cs.figure
                offset += dur
            if offset != sum(e[2] for e in basm["elems"]):
                raise ValueError(f"{stuk['titel']} maat {m.number}: akkoordduur en basduur verschillen")


def _grens(stem):
    """Alle noot- en rustgrenzen (offsets) in een stem."""
    uit = set()
    for e in stem.notesAndRests:
        uit.add(e.offset)
        uit.add(e.offset + e.quarterLength)
    return uit


def _laagste(n):
    return min(n.pitches, key=lambda p: p.midi) if n.isChord else n.pitch


def _deel(e, punten):
    """Deel element e op de (binnenliggende) offsets punten in overbonden stukken: [(offset, stuk), ...]."""
    punten = sorted(g for g in punten if e.offset < g < e.offset + e.quarterLength)
    if not punten:
        return [(e.offset, e)]
    randen = [e.offset] + punten + [e.offset + e.quarterLength]
    oud = _tie(e)
    uit = []
    for i, (p0, p1) in enumerate(zip(randen, randen[1:])):
        d = copy.deepcopy(e)
        d.quarterLength = p1 - p0
        if i > 0:
            d.expressions, d.articulations, d.lyrics = [], [], []
        if not e.isRest:
            eerste, laatste = i == 0, i == len(randen) - 2
            if eerste and oud in (None, "start"):
                soort = "start"
            elif laatste and oud in (None, "stop"):
                soort = "stop"
            else:
                soort = "continue"
            d.tie = tie.Tie(soort)
        uit.append((p0, d))
    return uit


def _splits_op(stem, grenzen):
    """Deel de elementen van stem die over een van de grenzen heen liggen in overbonden noten."""
    for e in list(stem.notesAndRests):
        stukken = _deel(e, grenzen)
        if len(stukken) == 1:
            continue
        stem.replace(e, stukken[0][1])
        for p0, d in stukken[1:]:
            stem.insert(p0, d)


def _voeg(stem, y):
    """Voeg noot y (uit een andere stem van dezelfde maat) als akkoordtoon toe aan stem. Beide worden op
    elkaars grenzen gesplitst (overbonden noten), daarna vormt elk deel een akkoord met wat er in stem
    klinkt; een rust in stem wordt door de noot vervangen."""
    t0, t1 = y.offset, y.offset + y.quarterLength
    _splits_op(stem, {t0, t1})
    for o, d in _deel(y, _grens(stem)):
        e = next((e for e in stem.notesAndRests if e.offset == o), None)
        if e is None:
            stem.insert(o, d)
            continue
        if e.isRest:
            d.stemDirection = e.stemDirection
            stem.replace(e, d)
            continue
        akk = chord.Chord(list(e.pitches) + [d.pitch], quarterLength=e.quarterLength)
        akk.stemDirection = e.stemDirection
        akk.expressions, akk.articulations = list(e.expressions), list(e.articulations)
        if d.expressions and not akk.expressions:
            akk.expressions = [expressions.Fermata(type="upright")]
        for n_, p_ in (zip(e.notes, e.pitches) if e.isChord else ((e, e.pitch),)):
            if n_.tie is not None:
                akk.setTie(n_.tie, p_)
        if d.tie is not None:
            akk.setTie(d.tie, d.pitch)
        stem.replace(e, akk)


def vul(boven, onder, gebroken=False):
    """Vollere, speelbare pianozetting (alleen voor de partituur, niet voor de regelcontrole).

    De rechterhand neemt de tenor erbij (melodie + alt + tenor, binnen een octaaf) en de linkerhand houdt de
    bas; die bas krijgt bij frasebegin en -slot, op hele maten en in de slotcadens een octaaf eronder (Koele:
    LH-octaven vooral aan regeleinden en in het slot). Een tenornoot die niet in de rechterhand past (meer
    dan een octaaf onder de melodie, of onder F3) komt als samenklank bij de bas in de linkerhand. Een
    liggende noot tegenover een bewegende stem wordt in overbonden noten gedeeld. Elke hand grijpt hoogstens
    een octaaf. Geeft de telling {"rechts": n, "links": n} van de verplaatste tenornoten.

    gebroken=True (popballads, "linkerhand": "gebroken" in de bron): de linkerhand speelt in plaats van bas + tenor
    gebroken akkoorden vanaf de bas (grondtoon, kwint, octaaf in achtsten/kwarten); de akkoordtonen komen uit
    bas, tenor en alt, dus er verdwijnt geen harmonie. De slotnoot blijft een basoctaaf."""
    bm, om = _maten(boven), _maten(onder)
    sop = [(m.offset + n.offset, n) for m in bm for n in (_stem(m, "1").notesAndRests if _stem(m, "1") else [])]

    def sop_max(t0, t1):
        return max((n.pitch.midi for t, n in sop if not n.isRest and t < t1 and t + n.quarterLength > t0),
                   default=None)

    # 1. per tenornoot: past hij in de rechterhand? Binnen een octaaf onder de hoogste melodienoot die
    #    tijdens de noot klinkt (of onder de alt als de melodie rust), niet onder F3 en onder de alt.
    #    Bij een gebroken linkerhand telt het per maat: alle tenornoten naar rechts of geen.
    plan = []  # (maat onder, alt, bas, tenornoot, naar rechts)
    ok = []  # per maat: alle tenornoten naar rechts
    for mb, mo in zip(bm, om):
        alt, ten, bas = _stem(mb, "2"), _stem(mo, "1"), _stem(mo, "2")
        if alt is None or ten is None or bas is None:
            ok.append(False)
            continue
        alles = True
        for y in ten.notes:
            y0, y1 = y.offset, y.offset + y.quarterLength
            boven = [x for x in alt.notes if x.offset < y1 and x.offset + x.quarterLength > y0]
            hoog = sop_max(mb.offset + y0, mb.offset + y1)
            if hoog is None:
                hoog = max((x.pitch.midi for x in boven), default=None)
            past = (hoog is not None and hoog - y.pitch.midi <= SPAN and y.pitch.midi >= RH_MIN
                    and all(x.pitch.midi > y.pitch.midi for x in boven))
            plan.append([mo, alt, bas, y, past])
            alles = alles and past
        ok.append(alles)
    # een overbonden tenornoot blijft met zijn vervolg in dezelfde hand
    veranderd = True
    while veranderd:
        veranderd = False
        for p1, p2 in zip(plan, plan[1:]):
            if _tie(p1[3]) in ("start", "continue") and p1[4] != p2[4]:
                p1[4] = p2[4] = False
                veranderd = True
        for i in range(len(om) - 1):
            ten = _stem(om[i], "1")
            laatste = ten.notesAndRests[-1] if ten is not None and len(ten.notesAndRests) else None
            if laatste is not None and _tie(laatste) in ("start", "continue") and ok[i] != ok[i + 1]:
                ok[i] = ok[i + 1] = False
                veranderd = True
    # klanken van alt en tenor per moment, voor de gebroken linkerhand
    klank = [(mb.offset + n.offset, mb.offset + n.offset + n.quarterLength, n.pitch.midi)
             for mb, mo in zip(bm, om) for st in (_stem(mb, "2"), _stem(mo, "1")) if st is not None
             for n in st.notes]
    # 2. tenor verplaatsen: naar de alt (drieklank in de rechterhand) of, als hij daar niet past, als
    #    samenklank bij de bas (linkerhand). Gebroken linkerhand: alleen hele maten naar rechts.
    telling = {"rechts": 0, "links": 0}
    for mo, alt, bas, y, past in plan:
        if gebroken and not ok[om.index(mo)]:
            continue
        _voeg(alt if past else bas, y)
        telling["rechts" if past else "links"] += 1
    for mo in om:
        ten = _stem(mo, "1")
        if ten is not None and (not gebroken or ok[om.index(mo)]):
            mo.remove(ten)
    if gebroken:
        _breek(om, ok, klank)
        _enkel(om)
        return telling
    # 3. frasegrenzen uit de melodie: een noot van >= 3 tellen of gevolgd door een rust sluit een frase af
    begin, eind = set(), set()
    for (t0, n0), (t1, n1) in zip(sop, sop[1:]):
        lang = not n0.isRest and (n0.quarterLength >= 3 or n1.isRest)
        if not n1.isRest and (n0.isRest or lang):
            begin.add(t1)
        if lang and _tie(n0) not in ("stop", "continue"):
            eind.add(t0)
    if sop and not sop[0][1].isRest:
        begin.add(sop[0][0])
    # 4. basoctaven, alleen in maten waar de linkerhand alleen de bas speelt
    groepen = []
    for mo in om:
        bas = _stem(mo, "2")
        for n in (bas.notesAndRests if bas is not None else []):
            if n.isRest:
                continue
            goed = not n.isChord  # een samenklank bas + tenor krijgt geen octaaf
            if _tie(n) in ("stop", "continue") and groepen:
                groepen[-1][2].append(n)
                groepen[-1][1].append(goed)
            else:
                groepen.append((mo.offset + n.offset, [goed], [n]))
    for k, (t, goeds, groep) in enumerate(groepen):
        laatste = k == len(groepen) - 1
        if not all(goeds) or groep[0].pitch.midi - 12 < (OCTAAF_MIN - 5 if laatste else OCTAAF_MIN):
            continue
        # na een leidtoon (halve toon eronder) geen octaaf: de onderste lijn zou dan een septiem omlaag
        # springen en de controle ziet de leidtoon niet meer stapsgewijs oplossen (LT)
        if k and _laagste(groepen[k - 1][2][-1]).midi == groep[0].pitch.midi - 1:
            continue
        if not (t in begin or t in eind or sum(x.quarterLength for x in groep) >= 4 or k >= len(groepen) - 2):
            continue
        for x in groep:
            akk = chord.Chord([x.pitch.transpose(-12), x.pitch], quarterLength=x.quarterLength)
            akk.tie, akk.stemDirection = x.tie, x.stemDirection
            akk.expressions, akk.articulations = list(x.expressions), list(x.articulations)
            x.activeSite.replace(x, akk)
    _enkel(om)
    return telling


LIGGING = (53, 74)  # rechterhandakkoorden in de akkoordbegeleiding: F3 t/m D5
MIDDEN = 64  # E4: voorkeursmidden van die akkoorden


def _ligging(pcs, vorige, boven_bas):
    """Gesloten ligging van de toonklassen binnen een octaaf, boven de bas en zo dicht mogelijk bij de vorige."""
    beste, kosten = None, None
    for start in range(max(LIGGING[0], boven_bas + 1), LIGGING[1] + 1):
        if start % 12 not in pcs:
            continue
        noten = [start]
        while len(noten) < len(pcs):
            p = noten[-1] + 1
            while p % 12 not in pcs:
                p += 1
            noten.append(p)
        if noten[-1] > LIGGING[1] or noten[-1] - noten[0] > SPAN:
            continue
        k = abs(sum(noten) / len(noten) - MIDDEN) * 0.3
        if vorige:
            k += sum(min(abs(p - q) for q in vorige) for p in noten)
        if kosten is None or k < kosten:
            beste, kosten = noten, k
    return beste


def _losse_bindingen(maat, stemmen, soort):
    """Bindingen naar of uit een herschreven buurmaat weghalen ('start' aan het eind, 'stop' aan het begin)."""
    if stemmen is not None and not maat.voices:
        return  # alleen de bas, die blijft doorklinken
    for v in (maat.voices or [maat]):
        if stemmen is not None and v.id not in stemmen:
            continue
        noten = list(v.notes)
        for n in noten[-1:] if soort == "start" else noten[:1]:
            if n.tie is None:
                continue
            if soort == "start" and n.tie.type in ("start", "continue"):
                n.tie = tie.Tie("stop") if n.tie.type == "continue" else None
            elif soort == "stop" and n.tie.type in ("stop", "continue"):
                n.tie = tie.Tie("start") if n.tie.type == "continue" else None


def _spel(p, namen):
    """Toonhoogte p (midi) gespeld volgens het akkoordsymbool (Db, niet C#)."""
    t = pitch.Pitch(namen[p % 12]) if p % 12 in namen else pitch.Pitch(midi=p)
    t.octave = 4
    t.octave += (p - t.midi) // 12
    return t


def _stilte(zangmaat):
    """Vensters (begin, eind) binnen de maat waarin de zang rust of een noot aanhoudt (vanaf de tweede tel van
    een noot van minstens twee tellen, overbindingen meegerekend)."""
    delen = []  # (begin, eind, rust)
    for n in zangmaat.recurse().notesAndRests:
        t0, t1 = Fraction(n.offset), Fraction(n.offset) + Fraction(n.quarterLength)
        vervolg = not n.isRest and n.tie is not None and n.tie.type in ("stop", "continue")
        if vervolg and delen and not delen[-1][2]:
            delen[-1] = (delen[-1][0], t1, False)
        elif vervolg:
            delen.append((t0 - 1, t1, False))  # aangehouden uit de vorige maat
        else:
            delen.append((t0, t1, n.isRest))
    vensters = []
    for t0, t1, rust in delen:
        if not rust:
            if t1 - t0 < 2:
                continue
            t0 += 1
        t0 = max(t0, Fraction(0))
        if vensters and vensters[-1][1] == t0:
            vensters[-1] = (vensters[-1][0], t1)
        else:
            vensters.append((t0, t1))
    return vensters


# linkerhandfiguren per twee tellen (b = bas, m = midden, t = top); ze wisselen elkaar af
LH_FIGUREN = ([("b", 0.5), ("m", 0.5), ("t", 1)],
              [("b", 0.5), ("m", 0.5), ("t", 0.5), ("m", 0.5)],
              [("b", 1.5), ("m", 0.5)])


def _inzetten(zangmaat, t0, t1):
    """Aantal nieuw gezongen noten in [t0, t1)."""
    return sum(1 for n in zangmaat.recurse().notes
               if t0 <= Fraction(n.offset) < t1 and (n.tie is None or n.tie.type == "start"))


def _omkering(ligging, op, ondergrens):
    """Dezelfde gesloten ligging een omkering hoger (op) of lager, of None als die buiten LIGGING valt."""
    if op:
        nieuw = ligging[1:] + [ligging[0] + 12]
    else:
        nieuw = [ligging[-1] - 12] + ligging[:-1]
    return nieuw if max(LIGGING[0], ondergrens) <= nieuw[0] and nieuw[-1] <= LIGGING[1] else None


def _rh_figuur(t0, t1, ligging, inzetten, k, ondergrens):
    """Rechterhand voor één akkoord van twee tellen, afhankelijk van de zang: onder een drukke melodie
    afwisselend aangehouden of met een 'duw' op 2-en (4. + 8); onder een rustige melodie beweegt de bovenstem
    op tel 2 naar de volgende akkoordtoon (kleine tegenmelodie). Andere duren: één aanslag."""
    d = t1 - t0
    if d != 2 or t0 % 1:
        return [(t0, ligging, d)]
    if inzetten >= 3:
        return [(t0, ligging, d)] if k % 2 == 0 else [(t0, ligging, Fraction(3, 2)), (t0 + Fraction(3, 2), ligging, Fraction(1, 2))]
    ander = _omkering(ligging, k % 2 == 0, ondergrens) or _omkering(ligging, k % 2 == 1, ondergrens)
    return [(t0, ligging, 1), (t0 + 1, ander, 1)] if ander else [(t0, ligging, d)]


def akkoordbegeleiding(stuk, zang, boven, onder):
    """Begeleidingsvariant ("begeleiding": "akkoorden"): in elke maat waarin gezongen wordt speelt de rechterhand
    akkoorden uit "akkoorden" (gesloten ligging, zonder melodie) en de linkerhand gebroken akkoorden vanaf de
    gezette bas. Maten zonder zang (voorspel, tussenspel, naspel) houden de pianozetting met melodie, en op een
    'R' in "akkoorden" (zoals de opmaat na het voorspel) speelt de rechterhand de melodie mee, zodat de piano
    daar niet stilvalt.

    Per akkoord van twee tellen kiest _rh_figuur() een figuur naar de drukte van de zang, anders één aanslag.
    Bij meer dan drie toonklassen (septiem, add9) vervalt in de rechterhand de grondtoon,
    die al in de bas klinkt. Rust de zang een tel of langer of houdt ze een lange noot aan, dan speelt de rechterhand daar een kort loopje in
    achtsten door de akkoordtonen (afwisselend op en neer), zoals de opvullingen in de Sela-uitgaven.
    De linkerhand breekt elke basnoot van een tel of langer onder de rechterhand, met de figuren uit LH_FIGUREN
    om en om (een andere cycluslengte dan de rechterhand, zodat het patroon niet steeds hetzelfde klinkt); waar de zang
    een tel stilstaat loopt de linkerhand in achtsten door. Elke basnoot komt in het octaaf dat het dichtst bij de
    vorige ligt, zodat de baslijn doorloopt in plaats van te springen."""
    import zetter

    zm, bm, om = _maten(zang), _maten(boven), _maten(onder)
    akkmaten = [m for sec in stuk["secties"] for m in zetter.parse_akkoorden(sec["akkoorden"])]
    if len(akkmaten) != len(bm):
        raise ValueError(f"{stuk['titel']}: akkoordbegeleiding vraagt akkoorden in elke sectie")
    zingt = [any(not n.isRest for n in m.recurse().notesAndRests) for m in zm]
    vorige, sym, vol, loopjes, rh_k, lh_k, vorige_bas = None, None, None, 0, 0, 0, None
    for i, (akkm, mb, mo) in enumerate(zip(akkmaten, bm, om)):
        if not zingt[i]:
            vorige = None
            continue
        # linkerhand: alleen de bas (stem 2, of de enige stem als de tenor al naar rechts is)
        for v in list(mo.voices):
            if v.id != "2":
                mo.remove(v)
        _enkel([mo])
        bassen = [p.midi for n in mo.recurse().notes for p in n.pitches]
        # rechterhand: oude inhoud weg, akkoorden erin
        oud = list(mb.recurse().notesAndRests)
        fermate = any(isinstance(e, expressions.Fermata) for n in oud for e in n.expressions)
        sopraan = next((v for v in mb.voices if v.id == "1"), mb)
        melodie = [(Fraction(n.offset), n) for n in sopraan.notesAndRests if not n.isRest]
        for v in list(mb.voices):
            mb.remove(v)
        for n in list(mb.notesAndRests):
            mb.remove(n)
        aanslagen = []  # [figuur zonder bas, duur, volledig symbool]
        for s, d in akkm:
            if (s == "=" and aanslagen and aanslagen[-1][0] is not None
                    and duration.Duration(aanslagen[-1][1] + d).type != "complex"):
                aanslagen[-1][1] += d
                continue
            if s != "=":
                sym, vol = (None, None) if s == "R" else (s.partition(":")[0], s)
            aanslagen.append([sym, d, vol])
        stil = _stilte(zm[i])
        o, liggingen = Fraction(0), []
        for s, d, v_sym in aanslagen:
            d = Fraction(d)
            if s is None:
                # zonder akkoord ('R', bijv. de opmaat na het voorspel) speelt de piano de melodie mee
                t = o
                for t0, n in melodie:
                    if o <= t0 and t0 + Fraction(n.quarterLength) <= o + d:
                        if t0 > t:
                            mb.insert(t, note.Rest(quarterLength=t0 - t))
                        n.stemDirection = "unspecified"
                        mb.insert(t0, n)
                        t = t0 + Fraction(n.quarterLength)
                if t < o + d:
                    mb.insert(t, note.Rest(quarterLength=o + d - t))
                o += d
                continue
            ak = zetter.Akkoord(s)
            pcs = ak.alle - {ak.root} if len(ak.alle) > 3 else ak.alle
            ondergrens = max(bassen, default=0) + 1
            vorige = _ligging(pcs, vorige, ondergrens - 1)
            eerste = vorige
            # loopje in de eerste zangrust van minstens een tel binnen dit akkoord (niet op de eerste tel)
            loop = None
            for a, e in stil:
                w0, w1 = -(-max(a, o + 1) // 1), min(e, o + d) // 1
                if w1 - w0 >= 1:
                    lengte = min(w1 - w0, 2)
                    loop = (w1 - lengte, w1)
                    break
            delen = [(o, loop[0] if loop else o + d)] + ([(loop[1], o + d)] if loop and loop[1] < o + d else [])
            gebruikt = [eerste]
            for t0, t1 in delen:
                if t1 <= t0:
                    continue
                for a, lg, q in _rh_figuur(t0, t1, vorige, _inzetten(zm[i], t0, t1), rh_k, ondergrens):
                    mb.insert(a, chord.Chord([_spel(p, ak.namen) for p in lg], quarterLength=q))
                    vorige = lg
                    gebruikt.append(lg)
                rh_k += 1
            liggingen.append((o, o + d, [min(min(lg) for lg in gebruikt)], v_sym))
            if loop:
                tonen = vorige + [vorige[0] + 12]
                reeks = tonen[:3] + [tonen[-1]] if loop[1] - loop[0] == 2 else tonen[-3:-1]
                if loopjes % 2:
                    reeks = reeks[::-1]
                loopjes += 1
                for k, p in enumerate(reeks):
                    mb.insert(loop[0] + Fraction(k, 2), note.Note(_spel(p, ak.namen), quarterLength=0.5))
            o += d
        if fermate:
            mb.notesAndRests.last().expressions.append(expressions.Fermata(type="upright"))
        # linkerhand gebroken: per basnoot bas-midden-top onder de rechterhand; een basnoot die over meer
        # akkoorden doorloopt (Em -> C/E) breekt per akkoord
        for n in list(mo.notes):
            t, d = Fraction(n.offset), Fraction(n.quarterLength)
            segmenten = [(max(t, x[0]), min(t + d, x[1]), x) for x in liggingen if x[0] < t + d and x[1] > t]
            if d < 1 or n.tie is not None or n.expressions or not segmenten or segmenten[0][0] != t:
                continue
            basis = min(p.midi for p in n.pitches)
            basnaam = min(n.pitches, key=lambda x: x.midi).name
            patroon = []
            for s0, s1, ligging in segmenten:
                ak = zetter.Akkoord(ligging[3])
                pcs = ak.alle | {ak.bas}
                rh_min = min(ligging[2])
                namen = dict(ak.namen)
                namen[basis % 12] = basnaam
                # baslijn laten doorlopen: het octaaf (bij voorkeur C2-E3, anders vanaf A1; ruimte voor een kwint
                # onder de rechterhand) dat het dichtst bij de vorige basnoot ligt
                kandidaten = [basis + 12 * k for k in range(-3, 2) if 36 <= basis + 12 * k <= 52
                              and basis + 12 * k + 7 < rh_min]
                kandidaten = kandidaten or [basis + 12 * k for k in range(-3, 2) if 33 <= basis + 12 * k <= 52
                                            and basis + 12 * k + 7 < rh_min]
                if kandidaten:
                    laag = min(kandidaten, key=lambda p: abs(p - (vorige_bas if vorige_bas is not None else basis)))
                else:
                    laag = basis
                    if laag > 52 and laag - 12 >= 33:
                        laag -= 12
                    while laag + 12 >= rh_min and laag - 12 >= 33:
                        laag -= 12
                vorige_bas = laag
                op = [p for p in range(laag + 1, laag + 13) if p % 12 in pcs and p < rh_min]
                rest = s1 - s0
                if not op or rest < 1:
                    patroon.append((laag, rest, namen))
                    continue
                # midden bij voorkeur de kwint boven de bas (bas-kwint-octaaf), anders de op één na hoogste toon
                top, mid = op[-1], (laag + 7 if laag + 7 in op[:-1] else op[-2] if len(op) > 1 else op[-1])
                stap = {"b": laag, "m": mid, "t": top}
                while rest >= 2:
                    t0 = s1 - rest
                    # houdt de zang een tel stil (lange noot of rust), dan loopt de linkerhand in achtsten door
                    stilstand = not _inzetten(zm[i], t0, t0 + 1) or not _inzetten(zm[i], t0 + 1, t0 + 2)
                    figuur = LH_FIGUREN[1] if stilstand else LH_FIGUREN[lh_k % len(LH_FIGUREN)]
                    patroon += [(stap[x], q, namen) for x, q in figuur]
                    lh_k += 1
                    rest -= 2
                if rest >= 1:
                    patroon += [(laag, 0.5, namen), (mid, 0.5, namen)]
                    rest -= 1
                if rest > 0:
                    patroon.append((top, rest, namen))
            mo.remove(n)
            for p, q, namen in patroon:
                mo.insert(t, note.Note(_spel(p, namen), quarterLength=q))
                t += Fraction(q)
        # bindingen van en naar niet-herschreven buurmaten
        for j, soort in ((i - 1, "start"), (i + 1, "stop")):
            if 0 <= j < len(bm) and not zingt[j]:
                _losse_bindingen(bm[j], None, soort)
                _losse_bindingen(om[j], {"1"}, soort)

def _enkel(maten):
    """Maat met nog maar één stem (tenor weg): stem opheffen, anders zet MuseScore een onzichtbare
    (grijze) hele rust in stem 1."""
    for m in maten:
        stemmen = list(m.voices)
        if len(stemmen) != 1:
            continue
        v = stemmen[0]
        inhoud = [(e.offset, e) for e in v.notesAndRests]
        m.remove(v)
        for o, e in inhoud:
            e.stemDirection = "unspecified"
            m.insert(o, e)


def _breek(om, ok, klank):
    """Gebroken linkerhand: per basnoot herhaald patroon bas-x-top (1/8 1/8 1/4), alles binnen een octaaf."""
    basnoten = [(mo, n) for mo in om for n in (_stem(mo, "2").notes if _stem(mo, "2") is not None else [])]
    for k, (mo, n) in enumerate(basnoten):
        t0, b = mo.offset + n.offset, n.pitch.midi
        if k == len(basnoten) - 1:
            if b - 12 >= OCTAAF_MIN - 5:
                akk = chord.Chord([n.pitch.transpose(-12), n.pitch], quarterLength=n.quarterLength)
                akk.tie, akk.stemDirection = n.tie, n.stemDirection
                akk.expressions = list(n.expressions)
                n.activeSite.replace(n, akk)
            continue
        d = n.quarterLength
        if d < 1 or n.expressions:
            continue
        pcs = {b % 12} | {p % 12 for a, e, p in klank if a <= t0 < e}
        laag = b - 12 if b > 52 and b - 12 >= 33 else b
        rh = [p for a, e, p in klank if a < t0 + d and e > t0 and (ok[om.index(mo)] or p > b + 12)]
        boven = min(rh) if rh else 200
        while laag + 12 >= boven and laag - 12 >= 33:
            laag -= 12
        op = [p for p in range(laag + 1, laag + 13) if p % 12 in pcs and p < boven]
        if not op:
            continue
        top = op[-1]
        mid = op[-2] if len(op) > 1 else op[-1]
        patroon = []
        rest = d
        while rest >= 2:
            patroon += [(laag, 0.5), (mid, 0.5), (top, 1)]
            rest -= 2
        if rest >= 1:
            patroon += [(laag, 0.5), (mid, 0.5)]
            rest -= 1
        if rest > 0:
            patroon.append((top, rest))
        stem, plek = n.activeSite, n.offset
        stem.remove(n)
        o = plek
        for p, q in patroon:
            nn = note.Note(p, quarterLength=q)
            nn.stemDirection = "down"
            stem.insert(o, nn)
            o += q
    # tenorstem is opgegaan in de gebroken akkoorden
    for goed, mo in zip(ok, om):
        ten = _stem(mo, "1")
        if ten is not None and not goed:
            mo.remove(ten)


def voorspel_pauze(balken):
    """Eerste sectie zonder zang (voorspel/intro): pauze aan het eind (fermate + caesuur) als dat de zang niet
    raakt, d.w.z. de zang zwijgt de hele sectie en geen noot (piano of tegenstem) loopt over in het zingen.
    Geeft True als het voorspel herkend is (dan krijgt de zang een eigen regel en label)."""
    *stemmen, rh, lh = balken
    if any(not n.isRest for m in stemmen[-1] for n in m.recurse().notesAndRests):
        return False
    for v in [v for m in [b[-1] for b in stemmen] + [rh[-1], lh[-1]] for v in (m.voices or [m])]:
        noten = list(v.notesAndRests)
        if noten and noten[-1].tie is not None and noten[-1].tie.type in ("start", "continue"):
            return True
    for b in stemmen:
        b[-1].recurse().notesAndRests.last().expressions.append(expressions.Fermata(type="upright"))
    for i, m in enumerate((rh[-1], lh[-1])):
        # fermate op de laatst aangeslagen noot van de balk (boven rechts, onder links)
        n = max((x for x in m.recurse().notes), key=lambda x: x.getOffsetBySite(x.activeSite))
        n.expressions.append(expressions.Fermata(type="upright" if i == 0 else "inverted"))
        if i == 0:
            n.articulations.append(articulations.Caesura())
    return True


def bouw(stuk, met_zang=True):
    score = stream.Score()
    score.metadata = metadata.Metadata()
    score.metadata.title = stuk["titel"]
    score.metadata.composer = stuk.get("componist", "")
    if stuk.get("ondertitel"):
        score.metadata.lyricist = stuk["ondertitel"]
    tegen = stream.Part()
    # "tegenstemnaam": (naam, afkorting) in STUK, bijv. ("Dwarsfluit", "Fl.") voor een fluitbovenstem
    tegen.partName, tegen.partAbbreviation = stuk.get("tegenstemnaam", ("Tegenstem", "Teg."))
    instr = instrument.Flute() if "fluit" in tegen.partName.lower() else instrument.Soprano()
    instr.partName = instr.instrumentName = tegen.partName
    instr.partAbbreviation = instr.instrumentAbbreviation = tegen.partAbbreviation
    tegen.insert(0, instr)
    tegen.insert(0, clef.TrebleClef())
    zang = stream.Part()
    zang.partName, zang.partAbbreviation = stuk.get("zangnaam", "Zang"), "Z."
    zang.insert(0, instrument.Soprano())
    zang.insert(0, clef.TrebleClef())
    boven, onder = stream.PartStaff(), stream.PartStaff()
    boven.partName = "Piano"
    boven.insert(0, clef.TrebleClef())
    onder.insert(0, clef.BassClef())

    secties = stuk["secties"]
    heeft_tegen_ooit = met_zang and any("tegenstem" in s for s in secties)
    nummer = 0 if secties[0].get("opmaat") else 1
    vorige_maat = None
    voorspel_eind, regels_extra = None, set()
    for si, sec in enumerate(secties):
        balken, heeft_tegen, vorige_maat_nieuw = bouw_sectie(stuk, sec, nummer, si == len(secties) - 1,
                                                             vorige_maat, met_zang)
        vorige_maat = vorige_maat_nieuw
        if heeft_tegen_ooit and not heeft_tegen:
            # tegenstem zwijgt in deze sectie: rusten
            leeg = []
            for m in balken[0]:
                mm = stream.Measure(number=m.number)
                for el in m.getElementsByClass((key.KeySignature, meter.TimeSignature)):
                    mm.insert(0, type(el)(el.sharps) if isinstance(el, key.KeySignature) else
                              meter.TimeSignature(el.ratioString))
                r = note.Rest(quarterLength=sum(x.quarterLength for x in m.voices[0].notesAndRests))
                r.fullMeasure = True
                mm.append(r)
                mm.paddingLeft, mm.paddingRight = m.paddingLeft, m.paddingRight
                mm.rightBarline, mm.leftBarline = m.rightBarline, m.leftBarline
                leeg.append(mm)
            balken = [leeg] + balken
        doelen = ([tegen] if heeft_tegen_ooit else []) + ([zang] if met_zang else []) + [boven, onder]
        if met_zang and si > 0 and voorspel_eind is not None:
            # overgang voorspel -> zang: eigen regel en een kaderlabel "Zang"
            if balken[0][0].number not in stuk.get("paginas", []):
                regels_extra.add(balken[0][0].number)
            label = expressions.TextExpression("Zang")
            label.style.enclosure, label.style.fontWeight = "rectangle", "bold"
            balken[0][0].insert(0, label)
            voorspel_eind = None
        if met_zang and si == 0 and len(secties) > 1 and voorspel_pauze(balken):
            voorspel_eind = balken[0][-1].number
        for m in balken[0]:
            if m.number in stuk.get("paginas", []):
                m.insert(0, layout.PageLayout(isNew=True))
            elif m.number in stuk.get("regels", []) or m.number in regels_extra:
                m.insert(0, layout.SystemLayout(isNew=True))
        for doel, b in zip(doelen, balken):
            for m in b:
                doel.append(m)
        nummer += len(balken[0])
    if heeft_tegen_ooit:
        score.insert(0, tegen)
    if met_zang:
        score.insert(0, zang)
    score.insert(0, boven)
    score.insert(0, onder)
    score.insert(0, layout.StaffGroup([boven, onder], symbol="brace", barTogether=True))
    if met_zang:
        vul(boven, onder, gebroken=stuk.get("linkerhand") == "gebroken")
        if stuk.get("begeleiding") == "akkoorden":
            akkoordbegeleiding(stuk, zang, boven, onder)
        gitaarakkoorden(stuk, boven)
    return score


def nabewerk(pad):
    """Voortekens laat MuseScore zelf bepalen; music21 zet er soms overbodige bij.
    Stemmen op de tweede balk krijgen nummer 5+ (MusicXML-conventie), anders schuift MuseScore ze op en
    vult stem 1 met onzichtbare (grijze) rusten."""
    boom = ET.parse(pad)
    for n in boom.getroot().iter("note"):
        for acc in n.findall("accidental"):
            n.remove(acc)
    for maat in boom.getroot().iter("measure"):
        per_balk = {}
        for el in maat:
            st, v = el.find("staff"), el.find("voice")
            if el.tag in ("note", "forward") and v is not None:
                per_balk.setdefault(st.text if st is not None else "1", []).append(v)
        for balk, stemmen in per_balk.items():
            volgorde = sorted({int(v.text) for v in stemmen})
            basis = 5 if balk == "2" else 1
            for v in stemmen:
                v.text = str(basis + volgorde.index(int(v.text)))
    boom.write(pad, encoding="UTF-8", xml_declaration=True)


def fermate_duur(tekst):
    """MuseScore-fermates afspelen op 150% van de notatieduur."""
    def zet(match):
        fermate = ET.fromstring(match[0])
        for oud in fermate.findall("timeStretch"):
            fermate.remove(oud)
        ET.SubElement(fermate, "timeStretch").text = "1.5"
        return ET.tostring(fermate, encoding="unicode")

    return re.sub(r"<Fermata\b[^>]*>.*?</Fermata>", zet, tekst, flags=re.S)


TITELKADER = 6  # hoogte titelkader in sp (MuseScore-import: 10)


def ruim_bereik(mscz, spatium=None):
    """Zet het bereik van de zangstemmen ruim, zodat MuseScore geen noten rood kleurt.
    Met spatium: kleinere notenbalk voor dit stuk (de MusicXML-import negeert die uit stijl.mss).
    Fermates krijgen 150% afspeelduur, ook na opnieuw bouwen vanuit MusicXML.
    Het titelkader wordt lager (TITELKADER sp), zodat er meer ruimte is voor de muziek."""
    with zipfile.ZipFile(mscz) as z:
        delen = {n: z.read(n) for n in z.namelist()}
    for n, data in delen.items():
        if n.endswith(".mscx"):
            tekst = data.decode("utf-8")
            for tag, waarde in (("minPitchP", 21), ("minPitchA", 21), ("maxPitchP", 108), ("maxPitchA", 108)):
                tekst = re.sub(rf"<{tag}>\d+</{tag}>", f"<{tag}>{waarde}</{tag}>", tekst)
            tekst = re.sub(r"(<VBox>\s*<height>)[\d.]+(</height>)", rf"\g<1>{TITELKADER}\g<2>", tekst, count=1)
            delen[n] = fermate_duur(tekst).encode("utf-8")
        if spatium and n.endswith(".mss"):
            delen[n] = re.sub(rb"<spatium>[\d.]+</spatium>", f"<spatium>{spatium}</spatium>".encode(), data)
    with zipfile.ZipFile(mscz, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in delen.items():
            z.writestr(n, data)


def mscore(args, doel):
    # mscore 4.x crasht soms bij het afsluiten nadat het bestand al geschreven is
    doel.unlink(missing_ok=True)
    subprocess.run([MSCORE, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not doel.exists():
        raise RuntimeError(f"MuseScore maakte {doel} niet")


def laad_module(pad):
    """De bron als module (STUK nog zonder gezette alt/tenor/bas)."""
    pad = Path(pad)
    spec = importlib.util.spec_from_file_location(pad.stem, pad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def laad(pad):
    """De bron met door zetter.py gezette pianostemmen."""
    import zetter
    return zetter.zet_stuk(laad_module(pad).STUK)


def grijze_rusten(mscz):
    """Aantal onzichtbare rusten in de MuseScore-partituur (grijs in de editor, onzichtbaar in de PDF)."""
    with zipfile.ZipFile(mscz) as z:
        return sum(z.read(n).decode("utf-8").count("<visible>0</visible>")
                   for n in z.namelist() if n.endswith(".mscx"))


def balanceer_paginas(stuk, mscz):
    """Verdeelt de systemen gelijkmatig over de pagina's: zet stuk["paginas"] op de maatnummers waar pagina 2,
    3, ... moeten beginnen (opmaak.balans, bestaande "paginas" blijven staan). Geeft de nieuw toegevoegde
    maatnummers; leeg als de verdeling al in balans is."""
    import opmaak
    starts = opmaak.balans(opmaak.systemen_per_pagina(mscz))
    if not starts:
        return []
    eerste = 0 if stuk["secties"][0].get("opmaat") else 1
    nummers = [eerste + i for i in starts]
    oud = set(stuk.get("paginas", []))
    stuk["paginas"] = sorted(oud | set(nummers))
    return [n for n in nummers if n not in oud]


def controle(b, sc, mscz, pdf):
    """Alle automatische controles van één gebouwd stuk; lijst met problemen (leeg = goed).
    Waarschuwingen van de stemcontrole (tegenstem wrijft) worden getoond maar keuren niet af."""
    import controleer
    import greep
    import opmaak
    regels, meldingen, waarschuwingen = controleer.controleer_bron(b)
    problemen = [f"REGEL maat {f['measure']} tel {f['beat']:g} {f['code']} {f['note']}: {f['detail']}" for f in regels]
    problemen += [f"STEM {m}" for m in meldingen]
    problemen += [f"GREEP {g} (> octaaf)" for g in greep.spans(sc)]
    if mscz is not None:
        grijs = grijze_rusten(mscz)
        if grijs:
            problemen.append(f"GRIJS {grijs} onzichtbare rusten in de .mscz")
        problemen += [f"OPMAAK {m}" for m in opmaak.controleer(mscz)]
    return problemen, waarschuwingen


def main(args):
    alleen_xml = "--alleen-xml" in args
    met_controle = "--zonder-controle" not in args
    namen = [a for a in args if not a.startswith("--")]
    if not (ROOT / "bron").is_dir():
        sys.exit(f"geen bron/ in {ROOT}: draai vanuit de liedmap, bijv. cd muziekgroep_11_oct")
    sys.path.insert(0, str(HIER))
    bronnen = sorted((ROOT / "bron").glob("*.py"))
    if namen:
        bronnen = [b for b in bronnen if b.stem in namen]
    tmp = ROOT / "tmp" / "xml"
    tmp.mkdir(parents=True, exist_ok=True)
    stijl = HIER / "stijl.mss"
    fout = False
    for b in bronnen:
        stuk = laad(b)
        naam = stuk.get("bestandsnaam", stuk["titel"])
        xml = tmp / f"{b.stem}.musicxml"
        sc = bouw(stuk)
        sc.write("musicxml", fp=xml)
        nabewerk(xml)
        mscz = pdf = None
        if not alleen_xml:
            for d in ("musescore", "pdf"):
                (ROOT / d).mkdir(exist_ok=True)
            mscz = ROOT / "musescore" / f"{naam}.mscz"
            pdf = ROOT / "pdf" / f"{naam}.pdf"
            mscore(["-S", str(stijl), "-o", str(mscz), str(xml)], mscz)
            ruim_bereik(mscz, stuk.get("spatium"))
            mscore(["-o", str(pdf), str(mscz)], pdf)
            nieuw = balanceer_paginas(stuk, mscz)
            if nieuw:
                # pagina's uit balans (bijv. 5 regels op p2, 3 op p3): breuken zetten en opnieuw bouwen
                print(f"{b.stem}: nieuwe pagina bij maat {', '.join(map(str, nieuw))} (balans)")
                sc = bouw(stuk)
                sc.write("musicxml", fp=xml)
                nabewerk(xml)
                mscore(["-S", str(stijl), "-o", str(mscz), str(xml)], mscz)
                ruim_bereik(mscz, stuk.get("spatium"))
                mscore(["-o", str(pdf), str(mscz)], pdf)
        if not met_controle:
            print(f"{b.stem}: gebouwd (zonder controle)")
            continue
        problemen, waarschuwingen = controle(b, sc, mscz, pdf)
        fout |= bool(problemen)
        print(f"{b.stem}: {'ok' if not problemen else f'{len(problemen)} problemen'}"
              + (f" ({len(waarschuwingen)} waarschuwingen)" if waarschuwingen else ""))
        for p in problemen:
            print(f"  {p}")
        for w in waarschuwingen:
            print(f"  LET OP {w}")
    sys.exit(1 if fout else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
