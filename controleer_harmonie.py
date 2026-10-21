#!/usr/bin/env python3
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
"""
Stap 4: formele controle van de zettingen in midi/ op de regels van de klassieke vierstemmige koraalzetting
(zie harmonie_regels.py voor de codes).

Per stuk:
  midi_controle/<stem>.musicxml   foute noten rood, met de code(s) als tekst onder de noot
  midi_controle/<stem>.txt        alle meldingen (maat, tel, code, noot, toelichting)
en samengevat over alle stukken: harmonie_controle.json en harmonie_controle.md.

Gebruik:
  .venv/bin/python controleer_harmonie.py [--only "Psalm 85"] [--omvang] [--force]
  .venv/bin/python controleer_harmonie.py --input-dir voorbeelden/ongecorrigeerd --output-dir voorbeelden/controle --report-dir voorbeelden
"""
import argparse
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

from harmonie_regels import DIR, Score, check, mark, report_lines, summary  # noqa: E402

OUT = DIR / "midi_controle"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="alleen stukken waarvan de bestandsnaam dit bevat")
    ap.add_argument("--omvang", action="store_true", help="ook de zangomvang van S/A/T/B toetsen (OMV)")
    ap.add_argument("--force", action="store_true", help="ook opnieuw doen als de uitvoer al nieuwer is")
    ap.add_argument("--input-dir", type=Path, default=DIR / "midi", help="map met partituren")
    ap.add_argument("--output-dir", type=Path, default=OUT, help="map voor gemarkeerde partituren en meldingen")
    ap.add_argument("--report-dir", type=Path, default=DIR, help="map voor harmonie_controle.json en .md")
    args = ap.parse_args()
    if args.input_dir.resolve() == args.output_dir.resolve():
        ap.error("bron- en uitvoermap moeten verschillen")

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    jpath = args.report_dir / "harmonie_controle.json"
    files = sorted(args.input_dir.glob("*.musicxml"))
    if args.only:
        files = [f for f in files if args.only in f.name]
    if not files:
        ap.error("geen MusicXML-bestanden gevonden voor deze selectie")
    prev = json.loads(jpath.read_text()) if jpath.exists() else {}
    stems = {p.stem for p in args.input_dir.glob("*.musicxml")}
    results = {k: v for k, v in prev.items() if k in stems}
    for f in files:
        out_xml = out_dir / f.name
        if not args.force and out_xml.exists() and out_xml.stat().st_mtime > f.stat().st_mtime and f.stem in prev:
            results[f.stem] = prev[f.stem]
            continue
        try:
            sc = Score(f)
            findings = check(sc, omvang=args.omvang)
            mark(sc)
            sc.write(out_xml, " – controle")
            lines = report_lines(findings)
            (out_dir / f"{f.stem}.txt").write_text("\n".join(lines) + "\n")
            s = summary(findings, len(sc.verticals))
            s["maten"] = max((v.measure for v in sc.verticals), default=0)
            results[f.stem] = s
            print(f"{f.stem[:60]:60s} verticalen={s['n_verticalen']:5d} fouten={s['totaal']:5d} "
                  f"({s['per_100']:5.1f}/100) {dict(Counter(s['codes']).most_common(4))}")
        except Exception as e:  # noqa: BLE001
            print(f"MISLUKT {f.stem}: {e}", file=sys.stderr)
            raise
    jpath.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    write_md(results, args.report_dir / "harmonie_controle.md")


def write_md(results: dict, path: Path | None = None):
    tot = Counter()
    n_vert = 0
    for s in results.values():
        tot.update(s["codes"])
        n_vert += s["n_verticalen"]
    codes = [c for c, _ in tot.most_common()]
    lines = ["# Formele harmonie-controle", "",
             f"{len(results)} stukken, {n_vert} verticalen, {sum(tot.values())} meldingen "
             f"({100 * sum(tot.values()) / max(1, n_vert):.1f} per 100 verticalen). "
             "De betekenis van de codes staat in docs/harmoniecontrole.md.", "",
             "## Totaal per code", "", "| code | aantal | per 100 verticalen |", "|---|---|---|"]
    for c in codes:
        lines.append(f"| {c} | {tot[c]} | {100 * tot[c] / max(1, n_vert):.1f} |")
    lines += ["", "## Per stuk", "", "| stuk | maten | verticalen | meldingen | per 100 | " + " | ".join(codes) + " |",
              "|---|---|---|---|---|" + "---|" * len(codes)]
    for stem, s in sorted(results.items(), key=lambda kv: -kv[1]["per_100"]):
        lines.append(f"| {stem[:45]} | {s.get('maten', '')} | {s['n_verticalen']} | {s['totaal']} | {s['per_100']} | "
                     + " | ".join(str(s["codes"].get(c, 0)) for c in codes) + " |")
    (path or DIR / "harmonie_controle.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
