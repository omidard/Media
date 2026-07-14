#!/usr/bin/env python3
"""
Expert curation of a few canonical laboratory media (MRS, LB, MacConkey) to their
full, correctly-bounded, cited formulations.

The auto-extraction / base-expansion left these missing the inorganic base, the
carbon source, and (for MRS) Mn2+ — which is load-bearing for lactic acid bacteria,
which accumulate mM Mn2+ in place of SOD (Archibald & Fridovich 1981). Here each
canonical medium is written out fully with sensible FBA bounds: a limiting carbon
source, unlimited mineral/salt ions, a moderate Mn2+ bound, and O2 set to the real
cultivation regime. Complex ingredients are decomposed (labelled approximations,
with references). Any paper-specific carbon source / supplement already captured on a
medium is preserved.

Run:  python3 tools/curate_wellknown_media.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")
sys.path.insert(0, HERE)
from map_metabolite import Mapper                     # noqa: E402
from complex_ingredients import decompose, REFS, ingredient_key  # noqa: E402
from enrich_coverage import recover                    # noqa: E402

MAP = Mapper(); DICT = MAP.dict
def valid(b): return b in DICT

# carbon sources / additives to PRESERVE if a medium already carries them (paper-specific)
CARBON = {"glc__D","lcts","malt","sucr","fru","gal","lac__L","lac__D","glyc","for","pyr",
          "cellb","tre","man","mnl","xyl__D","arab__L","rmn","fuc__L","rib__D","melib","raffin",
          "gam","acgam","etoh","glcn","cit","succ","meoh"}
SUPPLEMENT = CARBON | {"cys__L","thm","btn","hemeD","pheme","4abz","ade","gua","ura","o2"}

REF_MRS = ("De Man JC, Rogosa M, Sharpe ME. A medium for the cultivation of lactobacilli. "
           "J Appl Bacteriol 1960;23(1):130-135. doi:10.1111/j.1365-2672.1960.tb00188.x. "
           "Mn2+ requirement of lactic acid bacteria: Archibald & Fridovich, J Bacteriol 1981;146(3):928-936.")
REF_LB = ("Bertani G. Studies on lysogenesis I. J Bacteriol 1951;62(3):293-300; "
          "Sambrook & Russell, Molecular Cloning (CSHL, 2001). LB (Lennox): tryptone 10, yeast extract 5, NaCl 5 g/L; no added sugar.")
REF_MAC = ("MacConkey A. Lactose-fermenting bacteria in faeces. J Hyg (Lond) 1905;5(3):333-379. "
           "Standard MacConkey agar: peptone, lactose 10 g/L, bile salts, NaCl, neutral red, crystal violet, agar.")

# canonical formulations: (complex_ingredients, defined [(bigg, lower_bound, role)], oxygen, ref, uncovered[])
def C(*ids): return list(ids)
MRS = {
    "complex": ["peptone", "beef extract", "yeast extract"],
    "defined": [("glc__D", -15.0, "carbon source (glucose 20 g/L, limiting)"),
                ("ocdcea", -1.0, "oleate (Tween-80 surfactant / membrane fatty acid)"),
                ("ac", -5.0, "acetate (Na-acetate 5 g/L, selective agent)"),
                ("cit", -1.0, "citrate (diammonium citrate)"),
                ("nh4", -10.0, "ammonium (diammonium citrate)"),
                ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate (K2HPO4)"),
                ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate (MgSO4/MnSO4)"),
                ("mn2", -1.0, "MANGANESE (MnSO4) — mM Mn is the LAB oxidative-stress defence"),
                ("na1", -1000.0, "Na (Na-acetate)"), ("cl", -1000.0, "chloride"),
                ("ca2", -1000.0, "Ca"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
    "oxygen": "anaerobic", "ref": REF_MRS,
    "note": "MRS cultivation is microaerophilic-to-anaerobic; LAB grow by fermentation, so O2 uptake is off by default.",
}
LB = {
    "complex": ["tryptone", "yeast extract"],
    "defined": [("na1", -1000.0, "Na (NaCl)"), ("cl", -1000.0, "chloride (NaCl)"),
                ("pi", -1000.0, "phosphate (from hydrolysates)"), ("so4", -1000.0, "sulfate"),
                ("nh4", -1000.0, "ammonium (from hydrolysates)"), ("k", -1000.0, "K"),
                ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"), ("fe2", -1000.0, "Fe"),
                ("mn2", -1000.0, "Mn"), ("zn2", -1000.0, "Zn"), ("cu2", -1000.0, "Cu"),
                ("h2o", -1000.0, ""), ("h", -1000.0, "")],
    "oxygen": "facultative", "ref": REF_LB,
    "note": "LB has NO added sugar; carbon and energy come from the amino acids/peptides of tryptone and yeast extract. Typically grown aerobically.",
}
MAC = {
    "complex": ["peptone"],
    "defined": [("lcts", -10.0, "lactose 10 g/L (differential carbon source)"),
                ("na1", -1000.0, "Na (NaCl)"), ("cl", -1000.0, "chloride (NaCl)"),
                ("pi", -1000.0, "phosphate"), ("so4", -1000.0, "sulfate"),
                ("nh4", -1000.0, "ammonium"), ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"),
                ("ca2", -1000.0, "Ca"), ("o2", -10.0, "aerobic"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
    "oxygen": "aerobic", "ref": REF_MAC,
    "uncovered": [("Bile salts", "selective agent (inhibits Gram-positives); not a defined metabolite exchange"),
                  ("Crystal violet", "selective dye; not a nutrient"),
                  ("Neutral red", "pH indicator dye; not a nutrient"),
                  ("Agar", "gelling agent; not a nutrient")],
}


def comp(bid, lb, role, method="wellknown_curation", conf="curated"):
    rec = DICT.get(bid, {})
    c = {"name": rec.get("name", bid), "bigg_metabolite": bid, "exchange": "EX_%s_e" % bid,
         "lower_bound": lb, "upper_bound": 1000.0, "concentration_mM": None,
         "xref": rec.get("xrefs", {}), "in_biggr": rec.get("in_biggr", False),
         "exchange_source": ("biggr" if rec.get("in_biggr") else "bigg"),
         "mapping_method": method, "mapping_confidence": conf}
    if role:
        c["role"] = role
    return c


def build(spec, keep_existing=None):
    comps = {}
    drefs = {}
    # complex ingredient decomposition (labelled approximations, with refs)
    for ing in spec["complex"]:
        d = decompose(ing, valid=valid)
        if d:
            drefs[ing] = REFS.get(ingredient_key(ing), "")
            for b in d[1]:
                comps.setdefault("EX_%s_e" % b, comp(b, -1.0, None, "complex_decomposition", "approximation"))
                comps["EX_%s_e" % b]["derived_from"] = ing
                if drefs[ing]:
                    comps["EX_%s_e" % b]["decomposition_ref"] = drefs[ing]
    # defined components (override decomposition where they overlap, e.g. explicit bounds)
    for bid, lb, role in spec["defined"]:
        if valid(bid):
            comps["EX_%s_e" % bid] = comp(bid, lb, role)
    # preserve any paper-specific supplement already on the medium
    for c in (keep_existing or []):
        b = c.get("bigg_metabolite"); ex = c.get("exchange")
        if b in SUPPLEMENT and ex not in comps:
            c2 = dict(c); c2["role"] = c.get("role", "paper-specific supplement")
            if b in CARBON and (c2.get("lower_bound", 0) or 0) > -5:
                c2["lower_bound"] = -10.0
            comps[ex] = c2
    return comps, drefs


_AMT = re.compile(r"\d[\d.]*\s*(?:g/l|mg/l|g|mm|mol/l|m|%|w/v|v/v|µm|um|nm|mg)\b", re.I)
_STOP = re.compile(r"\b(total|feed|feeding|final|broth|medium|agar|control|supplement|supplemented|with|and)\b", re.I)
def name_supplements(name):
    """Map any '+ <compound>' additions named in the medium title to components."""
    out = {}
    for seg in re.split(r"\s*\+\s*", name or "")[1:]:
        seg = re.sub(r"\([^)]*\)", "", seg)
        seg = _AMT.sub("", seg); seg = _STOP.sub("", seg).strip(" ,.-")
        if len(seg) < 2:
            continue
        r = recover(seg, {})
        for c in (r if isinstance(r, list) else ([r] if r else [])):
            b = c.get("bigg_metabolite")
            if b in CARBON and (c.get("lower_bound", 0) or 0) > -5:
                c["lower_bound"] = -10.0
            c["role"] = "supplement (from medium name: '%s')" % seg
            out.setdefault(c["exchange"], c)
    return out


def curate(d, spec, kind):
    comps, drefs = build(spec, d.get("components", []))
    # add supplements named in the title (e.g. "+ 40 g/L sodium formate")
    for ex, c in name_supplements(d.get("name", "")).items():
        comps.setdefault(ex, c)
    if spec["oxygen"] == "anaerobic":
        comps.pop("EX_o2_e", None)
    d["components"] = sorted(comps.values(), key=lambda c: c["exchange"])
    d["oxygen"] = spec["oxygen"]; d["aerobic"] = (spec["oxygen"] != "anaerobic")
    d["oxygen_note"] = spec.get("note", "")
    d["base_medium"] = kind
    d["n_components"] = len(d["components"])
    d["n_mapped"] = len(d["components"])
    d["n_in_biggr"] = sum(1 for c in d["components"] if c.get("in_biggr"))
    # uncovered: keep MacConkey selective agents, else clear
    if spec.get("uncovered"):
        d["uncovered"] = [{"name": n, "reason": "non_nutrient", "curation": "no_exchange",
                           "xref": {}, "note": why} for n, why in spec["uncovered"]]
    prov = d.setdefault("provenance", {})
    prov["verification"] = "expert-curated (canonical formulation)"
    prov["wellknown_reference"] = spec["ref"]
    prov.pop("formulation_warning", None)
    if drefs:
        prov["decomposition_refs"] = {k: v for k, v in drefs.items() if v}
    return d


def main():
    dry = "--dry" in sys.argv
    n = {"MRS": 0, "LB": 0, "MacConkey": 0}
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f)); nm = d.get("name") or ""
        spec = kind = None
        if re.search(r"\bMRS\b|de man|rogosa", nm, re.I):
            spec, kind = MRS, "MRS"
        elif re.search(r"macconkey|mac conkey", nm, re.I):
            spec, kind = MAC, "MacConkey"
        elif re.search(r"\bLB\b|\bLBv2\b|luria|lysogen|lennox|bertani", nm, re.I):
            spec, kind = LB, "LB"
        if not spec:
            continue
        curate(d, spec, kind); n[kind] += 1
        if not dry:
            with open(f, "w") as fh:
                json.dump(d, fh, ensure_ascii=False)
    # create a canonical MacConkey record if none exist
    if n["MacConkey"] == 0:
        rec = {"id": "std_macconkey_agar", "name": "MacConkey agar (standard)", "category": "laboratory",
               "organism_scope": "enteric / Gram-negative selective", "aerobic": True,
               "description": "MacConkey agar — selective and differential medium for Gram-negative enteric bacteria; lactose fermenters are distinguished by neutral-red colour change.",
               "namespace": "bigg",
               "provenance": {"source_type": "standard", "citation": REF_MAC, "doi": "", "url": ""}}
        curate(rec, MAC, "MacConkey")
        if not dry:
            json.dump(rec, open(os.path.join(MEDIA, rec["id"] + ".json"), "w"), ensure_ascii=False)
        n["MacConkey"] += 1
    print("curated:", n)


if __name__ == "__main__":
    main()
