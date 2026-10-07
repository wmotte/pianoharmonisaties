"""Zet alt, tenor en bas bij een gekozen akkoordenreeks (dynamisch programmeren over liggingen).

In een sectie staat dan in plaats van "2", "3", "4" een regel "akkoorden", met maatstrepen als in de stemmen:

    "akkoorden": "Em/2 D/2 | G/4 C/4 G:B/2 | ..."

    Em/2      akkoord (music21-symbool: C, Cm, C7, Cmaj7, Csus4, Csus2, Cadd9, Cm7, Cdim, C6 ...) met duur
    G:B/2     omkering: bas B
    =/2       vorig akkoord loopt door (alt, tenor en bas overgebonden)
    R/2       piano (alt, tenor, bas) rust

De sopraan van de piano is de melodie ("1" of "melodie"). Harde eisen bij het zoeken:
- akkoord compleet (kwint mag ontbreken), alleen akkoordtonen in alt/tenor, bas = grondtoon of opgegeven bas;
- geen parallelle kwinten/octaven (ook tegenbeweging) tussen welk paar dan ook, inclusief de tegenstem;
- alt onder de laagste melodienoot van het akkoord, tenor onder de alt, bas niet boven de tenor;
- speelbaar: sopraan-alt en tenor-bas binnen een octaaf, alt-tenor binnen een octaaf;
- septiem niet verdubbeld en dalend (of liggend) opgelost; leidtoon niet verdubbeld.
Zachte kosten: weinig beweging in alt en tenor, geen verdubbelde terts in majeur, kwint liever aanwezig,
geen verborgen kwint/octaaf in de buitenstemmen, geen overlap.
"""

from fractions import Fraction

from music21 import harmony, key, pitch

import maak_partituren as mp

INF = float("inf")
BEREIK = {"B": (33, 60), "T": (45, 67), "A": (50, 74)}


def parse_akkoorden(tekst):
    """Lijst maten; elke maat = lijst (symbool, duur)."""
    maten, huidig, dur = [], [], Fraction(1)
    for tok in tekst.split():
        if tok in mp.STREPEN:
            maten.append(huidig)
            huidig = []
            continue
        sym, _, d = tok.rpartition("/")
        m = mp.re.match(r"^(\d+)(\.*)(t?)$", d)
        if not sym or not m:
            raise ValueError(f"akkoordtoken {tok!r} heeft geen duur")
        dur = mp.ql(*m.groups())
        huidig.append((sym, dur))
    if huidig:
        maten.append(huidig)
    return maten


class Akkoord:
    def __init__(self, sym):
        self.sym = sym
        figuur, _, bas = sym.partition(":")
        cs = harmony.ChordSymbol(figuur.replace("b", "-") if len(figuur) > 1 and figuur[1] == "b" else figuur)
        self.namen = {p.pitchClass: p.name for p in cs.pitches}
        self.root = cs.root().pitchClass
        if bas:
            bp = pitch.Pitch(bas.replace("b", "-") if len(bas) > 1 else bas)
            self.bas = bp.pitchClass
            self.namen.setdefault(bp.pitchClass, bp.name)
            self.vast = True
        else:
            self.bas = self.root
            self.vast = False
        pcs = [p.pitchClass for p in cs.pitches]
        iv = {(pc - self.root) % 12 for pc in pcs}
        self.terts = next(((self.root + i) % 12 for i in (3, 4) if i in iv), None)
        self.kwint = next(((self.root + i) % 12 for i in (7, 6, 8) if i in iv), None)
        sept = (9,) if "dim7" in figuur else (10, 11)
        self.septiem = next(((self.root + i) % 12 for i in sept if i in iv), None)
        self.majeur = self.terts is not None and (self.terts - self.root) % 12 == 4
        self.nodig = {pc for pc in pcs if pc != self.kwint}
        self.alle = set(pcs)
        # bas: opgegeven, of grondtoon met de terts (sextakkoord) als duurdere uitwijkmogelijkheid
        self.bassen = [(self.bas, 0.0)] if self.vast or self.terts is None else [(self.root, 0.0), (self.terts, 12.0)]


def segmenten(stuk):
    """Alle akkoordsegmenten over alle secties (met absolute tijd), plus per sectie de indeling."""
    segs = []
    t0 = Fraction(0)
    for si, sec in enumerate(stuk["secties"]):
        if "akkoorden" not in sec:
            _, _, lengtes = mp.sectie_maten(stuk, sec, key.KeySignature(sec["toonsoort"]))
            t0 += sum(lengtes)
            continue
        ks = key.KeySignature(sec["toonsoort"])
        maten = parse_akkoorden(sec["akkoorden"])
        toonaard = key.Key(sec["toonaard"]) if sec.get("toonaard") else ks.asKey("major")
        lt = toonaard.getLeadingTone().pitchClass
        lts = {ks.asKey("major").getLeadingTone().pitchClass, ks.asKey("minor").getLeadingTone().pitchClass, lt}
        t = t0
        for mi, maat in enumerate(maten):
            for sym, dur in maat:
                segs.append(dict(sec=si, maat=mi, sym=sym, on=t, end=t + dur, dur=dur, lt=lt, lts=lts,
                                 akk=None if sym in ("=", "R") else Akkoord(sym)))
                t += dur
        t0 = t
    # akkoord aan begin of eind van een sectie of naast een pianorust: grondligging (tenzij de bas is opgegeven)
    for i, seg in enumerate(segs):
        volg = segs[i + 1] if i + 1 < len(segs) else None
        vorig = segs[i - 1] if i else None
        seg["slot"] = (volg is None or volg["sym"] == "R" or volg["sec"] != seg["sec"]
                       or vorig is None or vorig["sym"] == "R" or vorig["sec"] != seg["sec"])
    return segs


def tijdlijn(stuk, naam):
    lijst = []
    t0 = Fraction(0)
    for sec in stuk["secties"]:
        ks = key.KeySignature(sec["toonsoort"])
        bron = sec.get(naam, sec["melodie"]) if naam == "1" else sec.get(naam)
        maten = mp.parse_stem(bron, ks) if bron else mp.parse_stem(sec["melodie"], ks)
        t = t0
        for maat in maten:
            for soort, p, dur, mods in maat["elems"]:
                if bron and soort == "noot":
                    stap, alter, octaaf = p
                    lijst.append((t, t + dur, 12 * (octaaf + 1) + "C D EF G A B".index(stap) + alter))
                t += dur
        t0 = t
    return lijst


def klinkt(lijst, t, voor=False):
    """Toon die op t klinkt (of, met voor=True, de laatste toon vóór t, ook over een korte rust heen)."""
    if voor:
        eerder = [(on, m) for on, end, m in lijst if on < t and end >= t - 4]
        return max(eerder)[1] if eerder else None
    for on, end, m in lijst:
        if on <= t < end:
            return m
    return None


def kandidaten(seg, S, teg):
    akk = seg["akk"]
    s0 = klinkt(S, seg["on"])
    smin = min([m for on, end, m in S if on < seg["end"] and end > seg["on"]], default=None)
    smax = max([m for on, end, m in S if on < seg["end"] and end > seg["on"]], default=None)
    plafond = (smin - 1) if smin is not None else 76
    uit = []
    bassen = dict(akk.bassen[:1] if seg["slot"] else akk.bassen)
    for b in range(*BEREIK["B"]):
        if b % 12 not in bassen:
            continue
        for t in range(max(b + 1, BEREIK["T"][0]), min(BEREIK["T"][1], b + 12) + 1):
            if t % 12 not in akk.alle:
                continue
            for a in range(max(t + 1, BEREIK["A"][0]), min(BEREIK["A"][1], t + 12, plafond) + 1):
                if a % 12 not in akk.alle:
                    continue
                if s0 is not None and s0 - a > 12:
                    continue
                if smax is not None and smax - a > 14:
                    continue
                stemmen = [b, t, a] + ([s0] if s0 is not None and s0 % 12 in akk.alle else [])
                pcs = [m % 12 for m in stemmen]
                if not akk.nodig <= set(pcs):
                    continue
                if akk.septiem is not None and pcs.count(akk.septiem) > 1:
                    continue
                if akk.majeur and akk.terts in seg["lts"] and pcs.count(akk.terts) > 1:
                    continue
                k = bassen[b % 12] * (2.5 if seg["dur"] >= 4 else 1)
                if akk.kwint is not None and akk.kwint not in pcs:
                    k += 2.5
                if akk.terts is not None and pcs.count(akk.terts) > 1:
                    k += 8 if akk.majeur else 1.5
                if b % 12 != akk.root and pcs.count(b % 12) > 1:
                    k += 3
                if t - b < 3 and b < 48:
                    k += 3  # dichte ligging laag in de bas klinkt modderig
                k += abs(a - 62) * 0.05 + abs(t - 55) * 0.05 + abs(b - 45) * 0.03
                uit.append(((b, t, a), k))
    return uit


def parallel(p1, q1, p2, q2):
    if p1 is None or q1 is None or p2 is None or q2 is None or p1 == p2 or q1 == q2:
        return False
    i1, i2 = abs(p1 - q1) % 12, abs(p2 - q2) % 12
    return (i1 == i2 == 7) or (i1 == i2 == 0)


def overgang(vorig, nu, seg_v, seg, S, teg):
    (b1, t1, a1), (b2, t2, a2) = vorig, nu
    s1, s2 = klinkt(S, seg["on"], voor=True), klinkt(S, seg["on"])
    g1, g2 = klinkt(teg, seg["on"], voor=True), klinkt(teg, seg["on"])
    oud = {"B": b1, "T": t1, "A": a1, "S": s1, "G": g1}
    nieuw = {"B": b2, "T": t2, "A": a2, "S": s2, "G": g2}
    namen = list(oud)
    # sopraan sluit direct aan (geen rust ertussen)?
    s_direct = s1 is not None and any(end == seg["on"] and m == s1 for on, end, m in S)
    for i in range(len(namen)):
        for j in range(i + 1, len(namen)):
            x, y = namen[i], namen[j]
            if {x, y} == {"S", "G"}:
                continue  # melodie en tegenstem liggen vast
            if parallel(oud[x], oud[y], nieuw[x], nieuw[y]):
                return INF
    k = abs(a2 - a1) + abs(t2 - t1) * 0.9 + max(0, abs(b2 - b1) - 7) * 0.3
    # verborgen kwint/octaaf buitenstemmen
    if s1 is not None and s2 is not None:
        ds, db = s2 - s1, b2 - b1
        if ds and db and (ds > 0) == (db > 0) and abs(ds) > 2 and (s2 - b2) % 12 in (0, 7) \
                and (s1 - b1) % 12 != (s2 - b2) % 12:
            return INF
    # overlap
    if a2 < t1 or t2 > a1 or t2 < b1 or b2 > t1:
        return INF
    # alt niet boven de vorige sopraan (alleen als die direct aansluit, niet over een rust heen)
    if s_direct and a2 > s1:
        return INF
    # melodische intervallen in alt en tenor: geen tritonus, overmatige secunde of sprong > sext
    for v1, v2, akk1, akk2 in ((a1, a2, seg_v["akk"], seg["akk"]), (t1, t2, seg_v["akk"], seg["akk"])):
        d = abs(v2 - v1)
        if d == 6 or d > 9:
            return INF
        if d == 3 and akk1 is not None and akk2 is not None:
            n1, n2 = akk1.namen.get(v1 % 12, "C"), akk2.namen.get(v2 % 12, "C")
            if abs("CDEFGAB".index(n1[0]) - "CDEFGAB".index(n2[0])) in (1, 6):
                return INF
    # septiem oplossen
    akk_v = seg_v["akk"]
    if akk_v is not None and akk_v.septiem is not None and seg["akk"] is not None:
        for v1, v2 in ((a1, a2), (t1, t2), (b1, b2)):
            if v1 % 12 == akk_v.septiem and v2 - v1 not in (0, -1, -2):
                k += 10
    # leidtoon in alt/tenor stapsgewijs omhoog bij V -> I
    if seg_v["lt"] is not None and akk_v is not None and seg["akk"] is not None and akk_v.majeur \
            and akk_v.terts == seg_v["lt"] and (seg["akk"].root - akk_v.root) % 12 == 5:
        for v1, v2 in ((a1, a2), (t1, t2)):
            if v1 % 12 == seg_v["lt"] and v2 - v1 != 1:
                k += 2.5
    # gelijke beweging van alle drie onderstemmen vermijden
    if (a2 - a1) * (t2 - t1) > 0 and (t2 - t1) * (b2 - b1) > 0:
        k += 1.5
    return k


def zet_stuk(stuk):
    """Vult "2", "3" en "4" in voor elke sectie met "akkoorden"."""
    if not any("akkoorden" in s for s in stuk["secties"]):
        return stuk
    segs = segmenten(stuk)
    S = tijdlijn(stuk, "1")
    teg = tijdlijn(stuk, "tegenstem")
    lagen = []  # per segment: dict staat -> (kosten, vorige staat)
    vorige_echte = None
    for i, seg in enumerate(segs):
        if seg["sym"] == "R":
            lagen.append(None)
            continue
        if seg["sym"] == "=":
            lagen.append("=")
            continue
        kand = kandidaten(seg, S, teg)
        if not kand:
            raise ValueError(f"{stuk['titel']}: geen ligging voor {seg['sym']} in sectie {seg['sec'] + 1} "
                             f"maat {seg['maat'] + 1}")
        laag = {}
        if vorige_echte is None:
            for st, k in kand:
                laag[st] = (k, None)
        else:
            vl, vseg = vorige_echte
            for st, k in kand:
                beste = (INF, None)
                for vst, (vk, _) in vl.items():
                    if vk == INF:
                        continue
                    c = vk + k + overgang(vst, st, vseg, seg, S, teg)
                    if c < beste[0]:
                        beste = (c, vst)
                laag[st] = beste
            if all(v[0] == INF for v in laag.values()):
                raise ValueError(f"{stuk['titel']}: geen regelgoede verbinding naar {seg['sym']} in sectie "
                                 f"{seg['sec'] + 1} maat {seg['maat'] + 1}")
        lagen.append(laag)
        vorige_echte = (laag, seg)
        # een rust breekt de keten niet: de verbinding loopt van het laatste klinkende akkoord
    # terug lopen
    keuze = [None] * len(segs)
    st = None
    for i in range(len(segs) - 1, -1, -1):
        laag = lagen[i]
        if laag is None or laag == "=":
            continue
        if st is None:
            st = min(laag, key=lambda s: laag[s][0])
        keuze[i] = st
        st = laag[st][1]
    # "=" neemt de ligging van het vorige akkoord over
    for i, seg in enumerate(segs):
        if seg["sym"] == "=":
            keuze[i] = keuze[i - 1]
            seg["akk"] = segs[i - 1]["akk"]
    schrijf(stuk, segs, keuze)
    return stuk


def noot(m, akk, dur, tie_naar_volgende):
    pc = m % 12
    naam = akk.namen.get(pc) if akk else None
    p = pitch.Pitch(naam) if naam else pitch.Pitch(midi=m)
    p.octave = 4
    while p.midi < m:
        p.octave += 1
    while p.midi > m:
        p.octave -= 1
    acc = {None: "n", 0: "n", 1: "#", -1: "b", 2: "##", -2: "bb"}[int(p.alter) if p.accidental else None]
    return f"{p.step}{acc}{p.octave}/{duur_tekst(dur)}{'~' if tie_naar_volgende else ''}"


def duur_tekst(dur):
    for basis in (1, 2, 4, 8, 16, 32):
        for punten in range(3):
            if mp.ql(basis, "." * punten, "") == dur:
                return f"{basis}{'.' * punten}"
            if mp.ql(basis, "." * punten, "t") == dur:
                return f"{basis}{'.' * punten}t"
    raise ValueError(f"duur {dur} niet te noteren als één waarde")


def kan_noteren(dur):
    try:
        duur_tekst(dur)
        return True
    except ValueError:
        return False


def schrijf(stuk, segs, keuze):
    per_sec = {}
    for i, seg in enumerate(segs):
        per_sec.setdefault(seg["sec"], []).append(i)
    for si, idxs in per_sec.items():
        sec = stuk["secties"][si]
        regels = {"2": [], "3": [], "4": []}
        maten = parse_akkoorden(sec["akkoorden"])
        strepen = [tok for tok in sec["akkoorden"].split() if tok in mp.STREPEN]
        k = 0
        for mi, maat in enumerate(maten):
            items = {"2": [], "3": [], "4": []}  # per stem: [midi of None, duur, akkoord, overbinden]
            for _ in maat:
                i = idxs[k]
                seg = segs[i]
                volgende = segs[i + 1] if i + 1 < len(segs) else None
                for stem, pos in (("2", 2), ("3", 1), ("4", 0)):
                    if seg["sym"] == "R":
                        m, tie = None, False
                    else:
                        m = keuze[i][pos]
                        tie = volgende is not None and volgende["sym"] == "=" and keuze[i + 1][pos] == m
                    vorig = items[stem][-1] if items[stem] else None
                    # liggende toon (of doorlopende rust) binnen de maat: één langere noot i.p.v. opnieuw aanslaan
                    if vorig is not None and vorig[0] == m and kan_noteren(vorig[1] + seg["dur"]):
                        vorig[1] += seg["dur"]
                        vorig[3] = tie
                    else:
                        items[stem].append([m, seg["dur"], seg["akk"], tie])
                k += 1
            for stem, lijst in items.items():
                for m, dur, akk, tie in lijst:
                    regels[stem].append(f"R/{duur_tekst(dur)}" if m is None else noot(m, akk, dur, tie))
            streep = strepen[mi] if mi < len(strepen) else "|"
            for stem in regels:
                regels[stem].append(streep)
        for stem, toks in regels.items():
            sec[stem] = " ".join(toks)
