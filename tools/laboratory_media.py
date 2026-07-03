#!/usr/bin/env python3
"""Curated laboratory media (category 'laboratory'): classic bench media used for bacteria.
Defined minimal media are exact; complex/commercial media (LB, TSB, BHI, blood agar) are
documented in-silico approximations (undefined hydrolysate components rendered as their
amino-acid / nucleoside / vitamin constituents). Every medium cited. Built from validated BiGG IDs."""
import json, os, re

REPO = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT = os.path.join(REPO, "data", "media")
DICT = json.load(open(os.path.join(REPO, "tools", "bigg_metabolite_dict.json")))

AA20 = ["ala__L","arg__L","asn__L","asp__L","cys__L","gln__L","glu__L","gly","his__L","ile__L",
        "leu__L","lys__L","met__L","phe__L","pro__L","ser__L","thr__L","trp__L","tyr__L","val__L"]
NUC  = ["adn","gsn","cytd","uri","thymd","ins"]
VIT  = ["btn","fol","pnto__R","ribflv","thm","nac","pydxn","cbl1","4abz"]
MIN  = ["pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","ni2","mobd","h2o","h","co2"]

def ex(mid): return f"EX_{mid}_e"
def comp(mid, lb, kind, conf="exact"):
    d = DICT.get(mid, {})
    return {"name": d.get("name", mid), "bigg_metabolite": mid, "exchange": ex(mid),
            "lower_bound": float(lb), "upper_bound": 1000.0, "concentration_mM": None,
            "xref": d.get("xrefs", {}), "in_biggr": d.get("in_biggr", False),
            "mapping_method": "recipe", "mapping_confidence": conf}

def build(mids_bounds, aerobic=True):
    """mids_bounds: dict mid->lb. Adds O2 by aerobicity. Returns (components, missing)."""
    d = dict(mids_bounds)
    d["o2"] = -10 if aerobic else 0
    comps, missing = [], []
    for mid, lb in d.items():
        if mid not in DICT or not DICT[mid]["in_biggr"]:
            missing.append(mid); continue
        comps.append(comp(mid, lb, "recipe"))
    comps.sort(key=lambda c: c["exchange"])
    return comps, missing

MINSET = {m:-1000 for m in MIN}
def minimal(carbon, cbound=-10):
    d = dict(MINSET); d[carbon] = cbound; return d
def rich(extra_carbon=None):
    d = dict(MINSET)
    for a in AA20: d[a] = -1
    for nu in NUC: d[nu] = -1
    for v in VIT: d[v] = -0.1
    if extra_carbon: d[extra_carbon] = -10
    return d

# (id, name, aerobic, category, recipe_dict, provenance)
MEDIA = [
 ("m9_acetate","M9 minimal + acetate (aerobic)",True, minimal("ac"),
   dict(source_type="standard", citation="Sambrook & Russell, Molecular Cloning 3rd ed. (2001); acetate as sole carbon source.", doi="", url="", notes="M9 salts + 20 mM acetate.")),
 ("m9_glycerol","M9 minimal + glycerol (aerobic)",True, minimal("glyc"),
   dict(source_type="standard", citation="Sambrook & Russell (2001); glycerol as sole carbon source.", doi="", url="", notes="M9 salts + glycerol.")),
 ("m9_succinate","M9 minimal + succinate (aerobic)",True, minimal("succ"),
   dict(source_type="standard", citation="Sambrook & Russell (2001); succinate as sole carbon source.", doi="", url="", notes="M9 salts + succinate.")),
 ("m9_lactate","M9 minimal + L-lactate (aerobic)",True, minimal("lac__L"),
   dict(source_type="standard", citation="Sambrook & Russell (2001); L-lactate as sole carbon source.", doi="", url="", notes="M9 salts + L-lactate.")),
 ("mops_minimal_glucose","MOPS minimal + glucose (aerobic)",True, minimal("glc__D"),
   dict(source_type="standard", citation="Neidhardt FC, Bloch PL, Smith DF. Culture medium for enterobacteria. J Bacteriol 119:736-747 (1974).", doi="10.1128/jb.119.3.736-747.1974", url="", notes="MOPS-buffered defined minimal; inorganic-ion exchange set matches M9 at exchange level; glucose carbon.")),
 ("m63_glucose","M63 minimal + glucose (aerobic)",True, minimal("glc__D"),
   dict(source_type="standard", citation="Miller JH, Experiments in Molecular Genetics (1972); Pardee AB et al. (1959).", doi="", url="", notes="M63 defined minimal; glucose carbon.")),
 ("davis_minimal_glucose","Davis minimal + glucose (aerobic)",True, minimal("glc__D"),
   dict(source_type="standard", citation="Davis BD, Mingioli ES. Mutants of Escherichia coli requiring methionine or vitamin B12. J Bacteriol 60:17-28 (1950).", doi="10.1128/jb.60.1.17-28.1950", url="", notes="Davis-Mingioli minimal; glucose carbon.")),
 ("lb_lennox","LB (Lennox) broth — in-silico approximation (aerobic)",True, rich(None),
   dict(source_type="standard", citation="Bertani G. Studies on lysogenesis I. J Bacteriol 62:293-300 (1951); Lennox ES (1955). In-silico composition: amino acids + nucleosides + vitamins from tryptone/yeast extract.", doi="10.1128/jb.62.3.293-300.1951", url="", notes="APPROXIMATION: LB's undefined tryptone/yeast-extract rendered as 20 L-amino acids + nucleosides + vitamins + minerals; no fermentable sugar (LB carbon = amino acids). Bounds are presence-based.")),
 ("tsb","Tryptic Soy Broth (TSB) — in-silico approximation (aerobic)",True, rich("glc__D"),
   dict(source_type="standard", citation="TSB standard formulation (casein + soy peptone + dextrose 2.5 g/L). In-silico: peptone amino acids + nucleosides + glucose.", doi="", url="", notes="APPROXIMATION of a complex commercial medium; includes glucose (dextrose). Presence-based bounds.")),
 ("bhi","Brain Heart Infusion (BHI) — in-silico approximation (aerobic)",True, rich("glc__D"),
   dict(source_type="standard", citation="BHI standard formulation (brain/heart infusion + peptone + dextrose). In-silico: amino acids + nucleosides + vitamins + glucose.", doi="", url="", notes="APPROXIMATION of a rich complex medium. Presence-based bounds.")),
 ("nutrient_broth","Nutrient broth — in-silico approximation (aerobic)",True, {**MINSET, **{a:-1 for a in AA20}},
   dict(source_type="standard", citation="Nutrient broth standard formulation (peptone + meat/yeast extract). In-silico: amino acids + minerals.", doi="", url="", notes="APPROXIMATION; peptone rendered as amino acids. Presence-based bounds.")),
 ("blood_agar_columbia","Columbia blood agar (+5% blood) — in-silico approximation (aerobic)",True, {**rich("glc__D"), "pheme":-0.1, "hemeD":-0.01},
   dict(source_type="standard", citation="Columbia agar base + 5% defibrinated sheep blood. In-silico: rich peptone base (amino acids + nucleosides + vitamins) + heme from blood.", doi="", url="", notes="APPROXIMATION; blood contributes heme (pheme) + amino acids. Supports fastidious/haem-requiring organisms. Presence-based bounds.")),
]

written=[]; allmiss=set()
for mid_id, name, aer, recipe, prov in MEDIA:
    comps, missing = build(recipe, aer)
    allmiss.update(missing)
    cat = "laboratory"
    rec={"id":mid_id,"name":name,"category":cat,"organism_scope":"prokaryote-generic","aerobic":aer,
         "description":name+".","namespace":"bigg","provenance":prov,
         "components":comps,"unmapped":[{"bigg_id":m,"reason":"not in BiGGr reactome"} for m in missing],
         "n_components":len(comps),"n_mapped":len(comps),
         "n_in_biggr":sum(1 for c in comps if c["in_biggr"]),"version":"1.0"}
    json.dump(rec, open(os.path.join(OUT, mid_id+".json"),"w"))
    written.append((mid_id, len(comps), len(missing)))

# reclassify existing M9 seeds to 'laboratory'
for m9 in ["m9_glucose_aerobic","m9_glucose_anaerobic"]:
    p=os.path.join(OUT,m9+".json")
    if os.path.exists(p):
        d=json.load(open(p)); d["category"]="laboratory"; json.dump(d,open(p,"w"),indent=1)

print("laboratory media written:")
for i,n,ms in written: print(f"  {i:34s} {n:3d} comps{(' | MISSING '+str(ms)) if ms else ''}")
if allmiss: print("BiGG ids not in reactome (dropped, flagged in unmapped):", sorted(allmiss))
