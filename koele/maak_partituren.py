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
"tempo" (kwarten per minuut), "voltas" ({maatindex binnen sectie: "1."} of {maatindex: ("1.", aantal_maten)}), "teksten" ({maatindex: "D.S."}).
Optioneel in STUK: "regels"/"paginas" (maatnummers met nieuwe regel/pagina), "ondertitel", "componist",
"spatium" (kleinere notenbalk, standaard 1.75), "linkerhand": "gebroken" (popballad: gebroken akkoorden in de linkerhand in plaats van tenor + bas, zie vul()).

Tekstregels: lettergrepen gescheiden door spaties, 'ge-' koppelt aan de volgende lettergreep,
'_' slaat een noot over, '~' wordt een spatie.

Gebruik (vanuit de liedmap): ../.venv/bin/python ../koele/maak_partituren.py [naam ...] [--alleen-xml] [--zonder-controle]
"""

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
        # {maatindex: "1."} of {maatindex: ("1.", aantal_maten)}
        nummer, lengte = (volta, 1) if isinstance(volta, str) else volta
        for b in balken:
            rb = spanner.RepeatBracket(b[idx:idx + lengte], number=int(nummer.rstrip(".")))
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


def vul(boven, onder, gebroken=False):
    """Vollere, speelbare pianozetting (alleen voor de partituur, niet voor de regelcontrole).

    Waar het kan neemt de rechterhand de tenor erbij (melodie + alt + tenor, binnen een octaaf) en houdt de
    linkerhand alleen de bas; die bas krijgt dan bij frasebegin en -slot, op hele maten en in de slotcadens
    een octaaf eronder (Koele: LH-octaven vooral aan regeleinden en in het slot). Elders blijft het 2 + 2.
    Elke hand grijpt hoogstens een octaaf.

    gebroken=True (popballads, "linkerhand": "gebroken" in de bron): de linkerhand speelt in plaats van bas + tenor
    gebroken akkoorden vanaf de bas (grondtoon, kwint, octaaf in achtsten/kwarten); de akkoordtonen komen uit
    bas, tenor en alt, dus er verdwijnt geen harmonie. De slotnoot blijft een basoctaaf."""
    bm, om = _maten(boven), _maten(onder)
    sop = [(m.offset + n.offset, n) for m in bm for n in (_stem(m, "1").notesAndRests if _stem(m, "1") else [])]

    def sop_max(t0, t1):
        return max((n.pitch.midi for t, n in sop if not n.isRest and t < t1 and t + n.quarterLength > t0),
                   default=None)

    # 1. per maat: kan de tenor naar de rechterhand?
    ok = []
    for mb, mo in zip(bm, om):
        alt, ten = _stem(mb, "2"), _stem(mo, "1")
        goed = alt is not None and ten is not None
        if goed:
            an, tn = list(alt.notesAndRests), list(ten.notesAndRests)
            goed = len(an) == len(tn) and all(
                x.offset == y.offset and x.quarterLength == y.quarterLength and x.isRest == y.isRest
                and (x.isRest or (_tie(x) == _tie(y) and y.pitch.midi < x.pitch.midi)) for x, y in zip(an, tn))
            if goed:
                for y in tn:
                    if y.isRest:
                        continue
                    hoog = sop_max(mb.offset + y.offset, mb.offset + y.offset + y.quarterLength)
                    if hoog is None or hoog - y.pitch.midi > SPAN or y.pitch.midi < RH_MIN:
                        goed = False
        ok.append(goed)
    # overbindingen over de maatstreep: beide maten dezelfde keuze
    veranderd = True
    while veranderd:
        veranderd = False
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
    # 2. tenor verplaatsen
    for goed, mb, mo in zip(ok, bm, om):
        if not goed:
            continue
        alt, ten = _stem(mb, "2"), _stem(mo, "1")
        for x, y in zip(list(alt.notesAndRests), list(ten.notesAndRests)):
            if x.isRest:
                continue
            akk = chord.Chord([y.pitch, x.pitch], quarterLength=x.quarterLength)
            akk.tie, akk.stemDirection = x.tie, x.stemDirection
            akk.expressions, akk.articulations = list(x.expressions), list(x.articulations)
            if y.expressions and not akk.expressions:
                akk.expressions = [expressions.Fermata(type="upright")]
            alt.replace(x, akk)
        mo.remove(ten)
    if gebroken:
        _breek(om, ok, klank)
        _enkel(om)
        return
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
    for goed, mo in zip(ok, om):
        bas = _stem(mo, "2")
        for n in (bas.notesAndRests if bas is not None else []):
            if n.isRest:
                continue
            if _tie(n) in ("stop", "continue") and groepen:
                groepen[-1][2].append(n)
                groepen[-1][1].append(goed)
            else:
                groepen.append((mo.offset + n.offset, [goed], [n]))
    for k, (t, goeds, groep) in enumerate(groepen):
        laatste = k == len(groepen) - 1
        if not all(goeds) or groep[0].pitch.midi - 12 < (OCTAAF_MIN - 5 if laatste else OCTAAF_MIN):
            continue
        if not (t in begin or t in eind or sum(x.quarterLength for x in groep) >= 4 or k >= len(groepen) - 2):
            continue
        for x in groep:
            akk = chord.Chord([x.pitch.transpose(-12), x.pitch], quarterLength=x.quarterLength)
            akk.tie, akk.stemDirection = x.tie, x.stemDirection
            akk.expressions, akk.articulations = list(x.expressions), list(x.articulations)
            x.activeSite.replace(x, akk)
    _enkel(om)


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
    tegen.partName, tegen.partAbbreviation = "Tegenstem", "Teg."
    tegen.insert(0, instrument.Soprano())
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


def ruim_bereik(mscz, spatium=None):
    """Zet het bereik van de zangstemmen ruim, zodat MuseScore geen noten rood kleurt.
    Met spatium: kleinere notenbalk voor dit stuk (de MusicXML-import negeert die uit stijl.mss).
    Fermates krijgen 150% afspeelduur, ook na opnieuw bouwen vanuit MusicXML."""
    with zipfile.ZipFile(mscz) as z:
        delen = {n: z.read(n) for n in z.namelist()}
    for n, data in delen.items():
        if n.endswith(".mscx"):
            tekst = data.decode("utf-8")
            for tag, waarde in (("minPitchP", 21), ("minPitchA", 21), ("maxPitchP", 108), ("maxPitchA", 108)):
                tekst = re.sub(rf"<{tag}>\d+</{tag}>", f"<{tag}>{waarde}</{tag}>", tekst)
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
        problemen += [f"OPMAAK {m}" for m in opmaak.controleer(pdf)]
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
