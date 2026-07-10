#!/usr/bin/env python3
"""
Expand named standard base media to their correct composition.

For each medium that references a standard base (M9, LB, MOPS, ...), add the base's
defined salt scaffold + hydrolysate decomposition + trace elements, while KEEPING
the supplements/carbon source the extraction captured. Fixes media that had only the
supplement (e.g. "M9 + vitamin B1 + trace elements + acetate" that was reduced to
acetate) by restoring the M9 salts, thiamine and trace metals.

Base-derived components are marked mapping_method="base_medium_expansion",
mapping_confidence="standard_formulation", derived_from=<base>.

Run:  python3 tools/expand_base_media.py [--dry] [--all]
  --all : also expand mediadive/food media (default: only auto-extracted lit media)
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")
sys.path.insert(0, HERE)
from base_media import BASES, detect_base            # noqa: E402
from complex_ingredients import decompose            # noqa: E402
from map_metabolite import Mapper                     # noqa: E402

MAP = Mapper(); DICT = MAP.dict
def valid(b): return b in DICT

CARBON = {"glc__D","ac","glyc","fru","gal","succ","lac__L","lac__D","malt","sucr","lcts","cit",
          "etoh","glcn","xyl__D","arab__L","man","mnl","srb__L","rmn","fuc__L","rib__D","pyr",
          "cellb","tre","melib","raffin","gam","acgam","ppa","but","for","meoh","glyclt"}
MINERAL = {"na1","pi","k","cl","nh4","mg2","so4","ca2","h2o","h","fe2","fe3","mn2","zn2","cu2",
           "cobalt2","mobd","ni2","hco3","mops","h2s","slnt","cit","ac"}


def comp(bid, method, conf, lb, derived=None):
    rec = DICT.get(bid, {})
    c = {"name": rec.get("name", bid), "bigg_metabolite": bid, "exchange": "EX_%s_e" % bid,
         "lower_bound": lb, "upper_bound": 1000.0, "concentration_mM": None,
         "xref": rec.get("xrefs", {}), "in_biggr": rec.get("in_biggr", False),
         "exchange_source": ("biggr" if rec.get("in_biggr") else "bigg"),
         "mapping_method": method, "mapping_confidence": conf}
    if derived:
        c["derived_from"] = derived
    return c


def expand(d):
    text = (d.get("name") or "") + " " + (d.get("description") or "")
    base = detect_base(text)
    if not base:
        return False
    spec = BASES[base]
    comps = d.get("components", [])
    have = {c.get("exchange") for c in comps}
    present_bids = {c.get("bigg_metabolite") for c in comps}
    added = 0

    def add(c):
        nonlocal added
        if c["exchange"] not in have:
            comps.append(c); have.add(c["exchange"]); added += 1

    # 1) defined scaffold (minerals -1000, other defined -1)
    for b in spec["defined"]:
        if valid(b):
            lb = -1000.0 if b in MINERAL else (-10.0 if b in CARBON else -1.0)
            add(comp(b, "base_medium_expansion", "standard_formulation", lb, base))
    # 2) complex hydrolysates -> decomposition (labelled approximation)
    for ing in spec["complex"]:
        dec = decompose(ing, valid=valid)
        if dec:
            for b in dec[1]:
                add(comp(b, "complex_decomposition", "approximation", -1.0, ing))
    # 3) trace elements when the base carries them or the recipe mentions them
    if spec["trace"] or re.search(r"trace element|trace metal|micronutrient", text, re.I):
        for b in ["fe2","fe3","mn2","zn2","cu2","cobalt2","mobd","ni2"]:
            if valid(b):
                add(comp(b, "base_medium_expansion", "standard_formulation", -1000.0, base + " trace elements"))
    # 4) thiamine / vitamin B1 if mentioned
    if re.search(r"vitamin\s*b\s*-?\s*1|thiamin|thiamine", text, re.I) and valid("thm"):
        add(comp("thm", "base_medium_expansion", "standard_formulation", -1.0, base))
    # 5) default carbon source, only if none present and not "without carbon"
    if spec["carbon"] and valid(spec["carbon"]):
        has_carbon = any(b in CARBON for b in present_bids) or any(
            c.get("bigg_metabolite") in CARBON for c in comps)
        if not has_carbon and not re.search(r"without (a )?carbon|no carbon|carbon.?free", text, re.I):
            add(comp(spec["carbon"], "base_medium_expansion", "standard_formulation", -10.0, base + " default carbon"))
    # 6) oxygen from base if anaerobic
    if spec["oxygen"] == "anaerobic":
        d["components"] = [c for c in comps if c.get("exchange") != "EX_o2_e"]
        d["oxygen"] = "anaerobic"; d["aerobic"] = False
        d["oxygen_note"] = "%s base is anaerobic" % base
        comps = d["components"]

    d["components"] = comps
    d["n_components"] = len(comps)
    d["n_mapped"] = len(comps)
    d["n_in_biggr"] = sum(1 for c in comps if c.get("in_biggr"))
    d["base_medium"] = base
    prov = d.setdefault("provenance", {})
    prov["base_expansion"] = "Base '%s' expanded to standard composition: %s" % (base, spec["cite"])
    return added > 0


def main():
    dry = "--dry" in sys.argv
    do_all = "--all" in sys.argv
    changed = 0; by_base = {}
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        if not do_all and not d["id"].startswith(("lit_", "complexlit_", "growthlit_")):
            continue
        n0 = len(d.get("components", []))
        if expand(d):
            changed += 1
            by_base[d.get("base_medium")] = by_base.get(d.get("base_medium"), 0) + 1
            if not dry:
                with open(f, "w") as fh:
                    json.dump(d, fh, ensure_ascii=False)
    print("media expanded:", changed)
    for b, n in sorted(by_base.items(), key=lambda x: -x[1]):
        print("  %-10s %d" % (b, n))


if __name__ == "__main__":
    main()
