#!/usr/bin/env python3
"""
Heuristic formulation sanity-checks for literature-extracted media.

Flags internal inconsistencies that signal a bad LLM extraction, e.g. the
description/name promises amino acids / vitamins / minerals / sugars but none are
present in the components. Does NOT prove correctness (that needs the paper); it
surfaces the media most likely to be wrong.

Run:  python3 tools/validate_formulations.py [--report N]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")

AA = {"ala__L","arg__L","asn__L","asp__L","cys__L","gln__L","glu__L","gly","his__L","ile__L",
      "leu__L","lys__L","met__L","phe__L","pro__L","ser__L","thr__L","trp__L","tyr__L","val__L"}
VIT = {"thm","ribflv","nac","pnto__R","pydxn","fol","btn","cbl1","4abz","ascb__L"}
SUG = {"glc__D","fru","sucr","gal","malt","lcts","arab__L","rib__D","rmn","xyl__D","man","fuc__L"}
MIN = {"k","mg2","pi","ca2","fe2","fe3","na1","cl","so4","zn2","mn2","cu2","mobd","nh4"}

LIT = ("lit_", "complexlit_", "growthlit_")


def has(comps, ids):
    return any(c.get("bigg_metabolite") in ids for c in comps)


def check(d):
    text = ((d.get("name") or "") + " " + (d.get("description") or "") + " " +
            ((d.get("provenance") or {}).get("notes") or "")).lower()
    comps = d.get("components", [])
    warns = []
    if re.search(r"amino acid", text) and not has(comps, AA):
        warns.append("promises amino acids, none present")
    if re.search(r"vitamin", text) and not has(comps, VIT):
        warns.append("promises vitamins, none present")
    if re.search(r"\bminerals?\b", text) and not has(comps, MIN):
        warns.append("promises minerals, none present")
    real = [c for c in comps if c.get("mapping_method") not in ("mineral_base", "base")]
    if len(real) < 3:
        warns.append("fewer than 3 real components")
    return warns


def main():
    reportn = int(sys.argv[sys.argv.index("--report") + 1]) if "--report" in sys.argv else 25
    flagged = []
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        if not d["id"].startswith(LIT):
            continue
        w = check(d)
        if w:
            flagged.append((d["id"], d.get("name", "")[:46], w))
    # severity: media that promise >=2 categories absent = strong hallucination signal
    strong = [x for x in flagged if sum(1 for m in x[2] if "promises" in m) >= 2]
    print("lit media flagged:", len(flagged), "| strong (>=2 promised-but-absent):", len(strong))
    for i, (mid, nm, w) in enumerate(strong[:reportn]):
        print(f"  [{mid}] {nm} :: {'; '.join(w)}")
    return flagged, strong


if __name__ == "__main__":
    main()
