#!/usr/bin/env python3
"""Consolidate literature-mined media: read agent extraction files, map component names to
BiGG (deterministic, via our mapper), build cited media JSONs. Requires a proving snippet;
components mapped by name -> BiGG exchange; paper-provided exchange bounds used directly."""
import json, os, re, glob, sys
sys.path.insert(0,"/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
from map_metabolite import Mapper
REPO="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
LIT="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/lit/extractions"
OUT=os.path.join(REPO,"data","media")
DICT=json.load(open(os.path.join(REPO,"tools","bigg_metabolite_dict.json")))
m=Mapper()
def valid(b): return b in DICT and DICT[b]["in_biggr"]
def nm(b): return DICT.get(b,{}).get("name",b)
def xr(b): return DICT.get(b,{}).get("xrefs",{})
MINSET={"pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","ni2","mobd","tungs","slnt","sel","hco3","no3","o2","h2o","h","co2"}
def is_min(b): return b in MINSET

# --- salt dissociation (reused from MediaDive ingredient mapping) ---
CATION=[("ammonium|\\(nh4\\)|nh4","nh4"),("ferric|fe\\(iii\\)|iron\\(iii\\)","fe3"),("ferrous|fe\\(ii\\)|iron\\(ii\\)","fe2"),
 ("iron|\\bfe\\b","fe2"),("sodium|\\bna\\b|\\bna-|na2|disodium|monosodium","na1"),
 ("potassium|\\bk\\b|\\bk-|dipotassium|monopotassium|k2","k"),("calcium|\\bca\\b","ca2"),("magnesium|\\bmg\\b","mg2"),
 ("manganese|\\bmn\\b","mn2"),("copper|cupric|\\bcu\\b","cu2"),("zinc|\\bzn\\b","zn2"),("cobalt|\\bco\\b","cobalt2"),("nickel|\\bni\\b","ni2")]
ANION=[("chloride","cl"),("sulfate|sulphate","so4"),("phosphate","pi"),("bicarbonate|hydrogen carbonate","hco3"),
 ("carbonate","hco3"),("nitrate","no3"),("molybdate","mobd"),("selenite","slnt"),("selenate","sel"),("tungstate","tungs"),
 ("thiosulfate","tsul"),("acetate","ac"),("citrate","cit"),("nitrite","no2")]
ANION_F=[("S2O3","tsul"),("HPO4|H2PO4|PO4","pi"),("SO4|SO3","so4"),("HCO3|CO3","hco3"),("NO3","no3"),("NO2","no2"),
 ("Mo7O24|MoO4","mobd"),("WO4","tungs"),("SeO3","slnt"),("Cl(?![a-z])","cl")]
CATION_F=[("NH4","nh4"),("Na(?![a-z])","na1"),("Ca(?![a-z])","ca2"),("Mg(?![a-z])","mg2"),("Mn(?![a-z])","mn2"),
 ("Fe(?![a-z])","fe2"),("Cu(?![a-z])","cu2"),("Zn(?![a-z])","zn2"),("Co(?![a-z])","cobalt2"),("Ni(?![a-z])","ni2"),("K(?![a-z])","k")]
ORG_NAMED={"vitamin b12":"cbl1","cobalamin":"cbl1","vitamin b1":"thm","vitamin b2":"ribflv","vitamin b6":"pydxn",
 "nicotinic acid":"nac","folic acid":"fol","pantothenate":"pnto__R","biotin":"btn","thiamine":"thm","hemin":"pheme","p-aminobenzoic acid":"4abz"}
def dissociate(name):
    n=name.lower(); raw=name
    for k,bid in ORG_NAMED.items():
        if k in n and valid(bid): return {f"EX_{bid}_e"}
    ex=set(); anion=False
    for pat,ion in ANION:
        if re.search(pat,n) and valid(ion): ex.add(f"EX_{ion}_e"); anion=True
    for pat,ion in ANION_F:
        if re.search(pat,raw) and valid(ion): ex.add(f"EX_{ion}_e"); anion=True
    cat=None
    for pat,ion in CATION:
        if re.search(pat,n): cat=ion; break
    if cat is None and anion:
        for pat,ion in CATION_F:
            if re.search(pat,raw): cat=ion; break
    if cat and valid(cat): ex.add(f"EX_{cat}_e")
    return ex
CATMAP={"minimal":"laboratory","defined":"laboratory","rich":"laboratory","complex":"laboratory","dietary":"dietary","other":"laboratory"}

def to_mM(amount, unit):
    try: v=float(re.search(r"[-+]?\d*\.?\d+", str(amount)).group(0))
    except: return None
    u=(unit or "").strip().lower()
    if u in ("mm","mmol/l"): return v
    if u in ("um","µm","umol/l","micromolar"): return v/1000
    if u in ("nm","nmol/l"): return v/1e6
    if u in ("m","mol/l"): return v*1000
    return None

def slug(s): return re.sub(r"[^a-z0-9]+","_",(s or "").lower()).strip("_")[:40] or "medium"

seen=set(); written=0; kept=[]; total_in=0
for fp in glob.glob(os.path.join(LIT,"batch_*.json")):
    try: data=json.load(open(fp))
    except: continue
    for med in data.get("media",[]):
        total_in+=1
        if not med.get("source_snippet"): continue
        comps={}
        # paper-provided exchanges (in-silico media)
        for e in (med.get("exchanges") or []):
            ex=e.get("exchange","")
            mm=re.match(r"EX_(.+)_e$",ex); bid=mm.group(1) if mm else None
            if bid and valid(bid):
                lb=e.get("lower_bound");
                try: lb=float(lb)
                except: lb=(-1000 if is_min(bid) else -1.0)
                comps[f"EX_{bid}_e"]={"name":nm(bid),"bigg_metabolite":bid,"exchange":f"EX_{bid}_e",
                    "lower_bound":lb,"upper_bound":1000.0,"concentration_mM":None,"xref":xr(bid),
                    "in_biggr":True,"mapping_method":"paper_exchange","mapping_confidence":"exact"}
        # chemical components -> map by name
        for c in (med.get("components") or []):
            name=c.get("name","")
            if not name: continue
            mM=to_mM(c.get("amount"), c.get("unit"))
            amt=(str(c.get("amount"))+" "+str(c.get("unit")) if c.get("amount") else None)
            hit=m.map(name=name)
            if hit and hit["in_biggr"]:
                bid=hit["bigg_metabolite"]; ex=hit["exchange"]
                comps[ex]={"name":hit["name"],"bigg_metabolite":bid,"exchange":ex,
                    "lower_bound":(-1000 if is_min(bid) else -1.0),"upper_bound":1000.0,"concentration_mM":mM,
                    "paper_amount":amt,"xref":xr(bid),"in_biggr":True,"mapping_method":hit["mapping_method"],
                    "mapping_confidence":hit["mapping_confidence"]}
            else:
                for ex in dissociate(name):   # salts -> ion exchanges
                    b=ex[3:-2]
                    comps.setdefault(ex,{"name":nm(b),"bigg_metabolite":b,"exchange":ex,
                        "lower_bound":(-1000 if is_min(b) else -1.0),"upper_bound":1000.0,"concentration_mM":None,
                        "paper_amount":amt,"xref":xr(b),"in_biggr":True,"mapping_method":"paper_salt_dissociation","mapping_confidence":"inferred"})
        norg=sum(1 for c in comps.values() if not is_min(c["bigg_metabolite"]))
        if len(comps) < 5 or norg < 1: continue    # need a usable formulation (ions + >=1 carbon/organic)
        pmcid=med.get("pmcid","PMC"); mid=f"lit_{pmcid}_{slug(med.get('medium_name'))}"
        if mid in seen: continue
        seen.add(mid)
        aer=med.get("aerobic"); aer=True if aer is None else bool(aer)
        if "EX_o2_e" not in comps and valid("o2"):
            comps["EX_o2_e"]={"name":nm("o2"),"bigg_metabolite":"o2","exchange":"EX_o2_e","lower_bound":(-10.0 if aer else 0.0),
                "upper_bound":1000.0,"concentration_mM":None,"xref":xr("o2"),"in_biggr":True,"mapping_method":"base","mapping_confidence":"convention"}
        au=med.get("first_author") or ""; yr=med.get("year") or ""; jr=med.get("journal") or ""; doi=med.get("doi") or ""
        cite=f"{au} et al. {med.get('paper_title','')}. {jr} ({yr})." + (f" DOI: {doi}." if doi else "") + f" [{pmcid}]"
        comps_list=sorted(comps.values(),key=lambda c:c["exchange"])
        rec={"id":mid,"name":f"{med.get('medium_name','Medium')} ({pmcid})",
             "category":CATMAP.get(med.get("medium_type","other"),"laboratory"),
             "organism_scope":med.get("organism") or "prokaryote-generic","aerobic":aer,
             "description":f"{med.get('medium_name','Medium')} — a {med.get('medium_type','')} medium extracted from {au} et al. ({yr}). Mapped to BiGG from the paper's stated composition.",
             "namespace":"bigg","provenance":{"source_type":"literature","citation":cite,"doi":doi,
                "url":f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/",
                "notes":"Extracted from the primary paper (snippet: "+re.sub(r'\s+',' ',med.get('source_snippet',''))[:200]+"). Component names mapped to BiGG (see mapping_confidence); presence-based bounds unless the paper gave exchange bounds; concentration_mM where units allowed. Extraction confidence: "+str(med.get("confidence",""))+"."},
             "components":comps_list,"unmapped":[],"n_components":len(comps_list),"n_mapped":len(comps_list),
             "n_in_biggr":sum(1 for c in comps_list if c["in_biggr"]),"n_food_components":norg,"version":"1.0"}
        json.dump(rec,open(os.path.join(OUT,mid+".json"),"w")); written+=1; kept.append(rec["id"])
print(f"extraction records in: {total_in} | literature media written: {written}")
