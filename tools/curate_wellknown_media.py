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
CARBON = {"glc__D","lcts","malt","sucr","fru","gal","lac__L","lac__D","glyc","pyr",
          "cellb","tre","man","mnl","xyl__D","arab__L","rmn","fuc__L","rib__D","melib","raffin",
          "gam","acgam","etoh","glcn","cit","succ","meoh",
          # organic acids used as sole carbon/energy source on minimal media
          "ac","ppa","but","fum","mal__L","akg","glyclt","hxa","glx","2ddglcn","for"}
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

# ---- the rest of the top-10 laboratory media ----
REF_M9 = ("M9 minimal medium — Sambrook J, Russell DW, Molecular Cloning: A Laboratory Manual, 3rd ed. "
          "CSHL Press 2001. Salts: Na2HPO4, KH2PO4, NaCl, NH4Cl; + 2 mM MgSO4, 0.1 mM CaCl2, ~0.2-0.4% carbon source (glucose).")
REF_TSB = ("Tryptic Soy Broth (Soybean-Casein Digest Medium) — BD Bionutrient Technical Manual; USP <62>. "
           "Casein peptone 17, soy peptone 3, NaCl 5, K2HPO4 2.5, dextrose 2.5 g/L.")
REF_BHI = ("Brain Heart Infusion — Rosenow EC, J Dent Res 1919; BD BHI formulation: brain/heart infusion solids, "
           "proteose peptone 10, NaCl 5, Na2HPO4 2.5, dextrose 2 g/L.")
REF_NB = ("Nutrient Broth — Atlas RM, Handbook of Microbiological Media (CRC Press). Peptone 5 g + meat/beef extract 3 g "
          "+ NaCl 5 g/L; no added sugar (carbon from the digest).")
REF_TB = ("Terrific Broth — Tartof KD, Hobbs CA, Bethesda Res Lab Focus 1987;9:12; Sambrook & Russell 2001. "
          "Tryptone 12, yeast extract 24 g/L, 0.4% glycerol, potassium phosphate buffer (KH2PO4 0.017 M, K2HPO4 0.072 M).")
REF_YT = ("2xYT — Sambrook & Russell, Molecular Cloning 2001; Miller 1972. Tryptone 16, yeast extract 10, NaCl 5 g/L; no added sugar.")
REF_SOB = ("SOB/SOC — Hanahan D, J Mol Biol 1983;166(4):557-580. SOB: tryptone 20, yeast extract 5, NaCl 0.5 g/L, "
           "2.5 mM KCl, 10 mM MgCl2, 10 mM MgSO4; SOC = SOB + 20 mM glucose.")
REF_MOPS = ("MOPS minimal medium — Neidhardt FC, Bloch PL, Smith DF, J Bacteriol 1974;119(3):736-747. "
            "40 mM MOPS + 4 mM tricine, K2HPO4, NH4Cl, K2SO4, MgCl2, CaCl2, FeSO4, NaCl, micronutrients, glucose.")

_MINBASE = [("pi", -1000.0, "phosphate"), ("so4", -1000.0, "sulfate"), ("nh4", -1000.0, "ammonium"),
            ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"),
            ("na1", -1000.0, "Na"), ("cl", -1000.0, "chloride"), ("h2o", -1000.0, ""), ("h", -1000.0, "")]
_TRACE = [("fe2", -1000.0, "Fe"), ("mn2", -1000.0, "Mn"), ("zn2", -1000.0, "Zn"),
          ("cu2", -1000.0, "Cu"), ("cobalt2", -1000.0, "Co"), ("mobd", -1000.0, "Mo"), ("ni2", -1000.0, "Ni")]

M9 = {"complex": [], "defined": _MINBASE + _TRACE + [("o2", -20.0, "aerobic")],
      "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_M9,
      "note": "M9 is a defined MINIMAL medium: salts + a single carbon source. Glucose is the default carbon; any carbon named on the medium is used instead."}
TSB = {"complex": ["casein peptone", "soytone"],
       "defined": [("glc__D", -10.0, "dextrose (carbon)"), ("na1", -1000.0, "Na (NaCl)"),
                   ("cl", -1000.0, "chloride"), ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate"),
                   ("so4", -1000.0, "sulfate"), ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"),
                   ("o2", -20.0, "aerobic"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
       "oxygen": "facultative", "ref": REF_TSB, "note": "General-purpose medium; casein + soy peptone + dextrose."}
BHI = {"complex": ["proteose_peptone", "beef extract"],
       "defined": [("glc__D", -10.0, "dextrose (carbon)")] + _MINBASE + [("o2", -20.0, "aerobic")],
       "oxygen": "facultative", "ref": REF_BHI, "note": "Rich medium for fastidious organisms; brain/heart infusion + peptone + dextrose."}
NB = {"complex": ["peptone", "beef extract"],
      "defined": _MINBASE + [("o2", -20.0, "aerobic")],
      "oxygen": "facultative", "ref": REF_NB, "note": "Classic general medium; peptone + meat extract + NaCl, no added sugar."}
TB = {"complex": ["tryptone", "yeast extract"],
      "defined": [("glyc", -10.0, "glycerol (carbon)"), ("k", -1000.0, "K (phosphate buffer)"),
                  ("pi", -1000.0, "phosphate (buffer, high)")] + _MINBASE[1:] + [("o2", -30.0, "aerobic, vigorous")],
      "oxygen": "aerobic", "ref": REF_TB, "note": "High-density E. coli medium; very rich (24 g/L yeast extract) with glycerol and strong phosphate buffer."}
YT2 = {"complex": ["tryptone", "yeast extract"],
       "defined": _MINBASE + [("o2", -20.0, "aerobic")],
       "oxygen": "facultative", "ref": REF_YT, "note": "Rich medium (phage/cloning); tryptone + yeast extract + NaCl, no added sugar."}
SOB = {"complex": ["tryptone", "yeast extract"],
       "defined": [("na1", -1000.0, "Na (NaCl)"), ("cl", -1000.0, "chloride"), ("k", -1000.0, "K (KCl)"),
                   ("mg2", -1000.0, "Mg (MgCl2/MgSO4)"), ("so4", -1000.0, "sulfate"), ("pi", -1000.0, "phosphate"),
                   ("nh4", -1000.0, "ammonium"), ("ca2", -1000.0, "Ca"), ("o2", -20.0, "aerobic"),
                   ("h2o", -1000.0, ""), ("h", -1000.0, "")],
       "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_SOB,
       "note": "Transformation-recovery medium; SOC = SOB + 20 mM glucose."}
MOPS = {"complex": [],
        "defined": [("mops", -1000.0, "MOPS buffer")] + _MINBASE + _TRACE + [("o2", -20.0, "aerobic")],
        "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_MOPS,
        "note": "Neidhardt MOPS-buffered defined minimal medium; glucose default carbon."}

# kind -> (spec, match regex, exclude regex or None, std_id, std_name)
REGISTRY = [
    ("MacConkey", MAC, r"macconkey|mac conkey", None, "std_macconkey_agar", "MacConkey agar (standard)"),
    ("MRS", MRS, r"\bMRS\b|de man|rogosa", None, "std_mrs_broth", "MRS broth (standard, De Man-Rogosa-Sharpe)"),
    ("TSB", TSB, r"tryptic soy|\bTSB\b|\bTSA\b|soybean.?casein", r"without|[- ]free\b|derived", "std_tsb", "Tryptic Soy Broth (standard)"),
    ("BHI", BHI, r"brain.?heart|\bBHIS?\b", r"without|[- ]free\b|limited|derived", "std_bhi", "Brain Heart Infusion (standard)"),
    ("Terrific", TB, r"terrific", None, "std_terrific_broth", "Terrific Broth (standard)"),
    ("SOB", SOB, r"\bSOB\b|\bSOC\b", r"halophil|modified", "std_sob_soc", "SOB / SOC (standard)"),
    ("2xYT", YT2, r"2\s*[x×]\s*yt", r"artificial|sea.?water|\bASW\b", "std_2xyt", "2xYT (standard)"),
    ("MOPS", MOPS, r"\bMOPS\b (minimal|defined)|minimal.{0,12}\bMOPS\b|\bMOPS\b minimal", r"ez\s*rich|rich defined", "std_mops_minimal", "MOPS minimal medium (standard, Neidhardt)"),
    ("Nutrient", NB, r"nutrient broth|nutrient agar", r"modified|dap-|granucult|derived", "std_nutrient_broth", "Nutrient Broth (standard)"),
    ("M9", M9, r"\bM9\b", r"derived|\bBee9\b|artificial|sea.?water|modified", "std_m9_minimal", "M9 minimal medium (standard)"),
    ("LB", LB, r"\bLB\b|\bLBv2\b|luria|lysogen|lennox|bertani", r"artificial|sea.?water|\bASW\b", "std_lb_broth", "LB broth (standard, Lennox)"),
]


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
    # default carbon source only if the medium has none (minimal media)
    if spec.get("default_carbon"):
        if not any((c.get("bigg_metabolite") in CARBON) for c in comps.values()):
            b, lbnd = spec["default_carbon"]
            if valid(b):
                comps["EX_%s_e" % b] = comp(b, lbnd, "default carbon source (glucose)")
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


def match(nm):
    """Return the first REGISTRY entry whose pattern matches and exclude does not."""
    for kind, spec, pat, excl, sid, sname in REGISTRY:
        if re.search(pat, nm, re.I) and not (excl and re.search(excl, nm, re.I)):
            return kind, spec, pat, excl, sid, sname
    return None


def main():
    dry = "--dry" in sys.argv
    from collections import Counter
    n = Counter(); skipped = Counter()
    # 1) curate matching plain-standard media (skip already-expert-curated + excluded)
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f)); nm = d.get("name") or ""
        ver = (d.get("provenance") or {}).get("verification", "")
        # never overwrite an expert-curated or paper-verified medium.
        if ver.startswith("expert-curated") or ver.startswith("paper-verified"):
            continue
        # skip database-sourced recipes (DSMZ MediaDive / USDA / FooDB / HMDB) — those
        # are real published recipes, not ours to replace with a generic canonical.
        if d["id"].startswith(("mediadive_", "usda_", "food_", "biospecimen_")):
            continue
        m = match(nm)
        if not m:
            # count near-misses that were excluded, for reporting
            for kind, spec, pat, excl, sid, sname in REGISTRY:
                if re.search(pat, nm, re.I) and excl and re.search(excl, nm, re.I):
                    skipped[kind] += 1; break
            continue
        kind, spec = m[0], m[1]
        curate(d, spec, kind); n[kind] += 1
        if not dry:
            with open(f, "w") as fh:
                json.dump(d, fh, ensure_ascii=False)
    # 2) ensure a clean canonical std_ record exists for every registry medium
    created = []
    for kind, spec, pat, excl, sid, sname in REGISTRY:
        path = os.path.join(MEDIA, sid + ".json")
        if os.path.exists(path):
            # refresh the existing std record to the current spec
            rec = json.load(open(path))
        else:
            rec = {"id": sid, "name": sname, "category": "laboratory",
                   "organism_scope": "general laboratory", "aerobic": True, "namespace": "bigg",
                   "description": "%s — canonical reference formulation." % sname,
                   "provenance": {"source_type": "standard", "citation": spec["ref"], "doi": "", "url": ""}}
            created.append(sid)
        rec["name"] = sname
        rec.setdefault("description", "%s — canonical reference formulation." % sname)
        rec["provenance"]["citation"] = spec["ref"]
        curate(rec, spec, kind)
        if not dry:
            json.dump(rec, open(path, "w"), ensure_ascii=False)
    print("curated media by kind:", dict(n))
    print("excluded (left as paper-verified):", dict(skipped))
    print("std canonical records created:", created)


if __name__ == "__main__":
    main()
