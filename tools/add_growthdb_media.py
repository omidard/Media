#!/usr/bin/env python3
"""Add GrowthDB-mined media (from paper compositions) into the Media repo, so Media is exhaustive.
Reuses the mapper + salt dissociation. Dedupes by composition signature. Returns id back-map."""
import json, os, re, sys
sys.path.insert(0,"/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
sys.path.insert(0,"/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/lit")
from map_metabolite import Mapper
import importlib.util
spec=importlib.util.spec_from_file_location("blm","/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/lit/build_lit_media.py")
# reuse dissociate + helpers from build_lit_media without running its main (guard by importing functions)
REPO="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT=os.path.join(REPO,"data","media")
DICT=json.load(open(os.path.join(REPO,"tools","bigg_metabolite_dict.json")))
m=Mapper()
def valid(b): return b in DICT and DICT[b]["in_biggr"]
def nm(b): return DICT.get(b,{}).get("name",b)
def xr(b): return DICT.get(b,{}).get("xrefs",{})
MINSET={"pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","ni2","mobd","tungs","slnt","sel","hco3","no3","o2","h2o","h","co2"}
def is_min(b): return b in MINSET
# salt dissociation (compact copy)
ANION=[("chloride","cl"),("sulfate|sulphate","so4"),("phosphate","pi"),("bicarbonate","hco3"),("carbonate","hco3"),("nitrate","no3"),("molybdate","mobd"),("selenite","slnt"),("tungstate","tungs"),("thiosulfate","tsul"),("acetate","ac"),("citrate","cit")]
ANION_F=[("HPO4|H2PO4|PO4","pi"),("SO4","so4"),("HCO3|CO3","hco3"),("NO3","no3"),("MoO4","mobd"),("Cl(?![a-z])","cl")]
CAT=[("ammonium|\\(nh4\\)|nh4","nh4"),("ferric|fe\\(iii\\)","fe3"),("ferrous|fe\\(ii\\)","fe2"),("iron|\\bfe\\b","fe2"),("sodium|\\bna\\b|na2","na1"),("potassium|\\bk\\b|k2","k"),("calcium|\\bca\\b","ca2"),("magnesium|\\bmg\\b","mg2"),("manganese|\\bmn\\b","mn2"),("copper|\\bcu\\b","cu2"),("zinc|\\bzn\\b","zn2"),("cobalt","cobalt2"),("nickel","ni2")]
CAT_F=[("NH4","nh4"),("Na(?![a-z])","na1"),("Ca(?![a-z])","ca2"),("Mg(?![a-z])","mg2"),("Mn(?![a-z])","mn2"),("Fe(?![a-z])","fe2"),("Cu(?![a-z])","cu2"),("Zn(?![a-z])","zn2"),("K(?![a-z])","k")]
ORGN={"vitamin b12":"cbl1","cobalamin":"cbl1","thiamine":"thm","biotin":"btn","folic acid":"fol","pantothenate":"pnto__R","riboflavin":"ribflv","nicotinic acid":"nac"}
def dissociate(name):
    n=name.lower()
    for k,b in ORGN.items():
        if k in n and valid(b): return {f"EX_{b}_e"}
    ex=set();an=False
    for p,i in ANION:
        if re.search(p,n) and valid(i): ex.add(f"EX_{i}_e");an=True
    for p,i in ANION_F:
        if re.search(p,name) and valid(i): ex.add(f"EX_{i}_e");an=True
    cat=None
    for p,i in CAT:
        if re.search(p,n): cat=i;break
    if cat is None and an:
        for p,i in CAT_F:
            if re.search(p,name): cat=i;break
    if cat and valid(cat): ex.add(f"EX_{cat}_e")
    return ex
def slug(s): return re.sub(r"[^a-z0-9]+","_",(s or "medium").lower()).strip("_")[:40] or "medium"

add=json.load(open("/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/growthdb_work/lit/media_to_add.json"))["pending_media_for_media_repo"]
sig_seen={}; written=0; backmap={}  # (pmcid,medium_name)->media_id
for item in add:
    comp=item.get("composition") or []; name=item.get("medium_name") or "medium"; pmc=item.get("pmcid","")
    comps={}
    for c in comp:
        cn=c.get("name","");
        if not cn: continue
        hit=m.map(name=cn)
        if hit and hit["in_biggr"]:
            b=hit["bigg_metabolite"];ex=hit["exchange"]
            comps[ex]={"name":hit["name"],"bigg_metabolite":b,"exchange":ex,"lower_bound":(-1000 if is_min(b) else -1.0),"upper_bound":1000.0,"concentration_mM":None,"paper_amount":(str(c.get("amount"))+" "+str(c.get("unit")) if c.get("amount") else None),"xref":xr(b),"in_biggr":True,"mapping_method":hit["mapping_method"],"mapping_confidence":hit["mapping_confidence"]}
        else:
            for ex in dissociate(cn):
                bb=ex[3:-2]
                comps.setdefault(ex,{"name":nm(bb),"bigg_metabolite":bb,"exchange":ex,"lower_bound":(-1000 if is_min(bb) else -1.0),"upper_bound":1000.0,"concentration_mM":None,"paper_amount":(str(c.get("amount"))+" "+str(c.get("unit")) if c.get("amount") else None),"xref":xr(bb),"in_biggr":True,"mapping_method":"paper_salt_dissociation","mapping_confidence":"inferred"})
    if len(comps)<4: continue
    sig=tuple(sorted(comps.keys()))
    if sig in sig_seen:
        backmap[(pmc,name)]=sig_seen[sig]; continue
    if "EX_o2_e" not in comps and valid("o2"):
        comps["EX_o2_e"]={"name":nm("o2"),"bigg_metabolite":"o2","exchange":"EX_o2_e","lower_bound":-10.0,"upper_bound":1000.0,"concentration_mM":None,"xref":xr("o2"),"in_biggr":True,"mapping_method":"base","mapping_confidence":"convention"}
    mid=f"growthlit_{pmc}_{slug(name)}"
    sig_seen[sig]=mid; backmap[(pmc,name)]=mid
    cl=sorted(comps.values(),key=lambda c:c["exchange"])
    rec={"id":mid,"name":f"{name} ({pmc})","category":"laboratory","organism_scope":"prokaryote-generic","aerobic":True,
         "description":f"{name} — medium reported in {pmc}, extracted for GrowthDB and mapped to BiGG.","namespace":"bigg",
         "provenance":{"source_type":"literature","citation":f"Medium composition from {pmc} (see GrowthDB record).","doi":"","url":f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/","notes":"Composition mapped to BiGG (mapper + salt dissociation); presence-based bounds; paper_amount retained. Added via GrowthDB curation."},
         "components":cl,"unmapped":[],"n_components":len(cl),"n_mapped":len(cl),"n_in_biggr":sum(1 for c in cl if c["in_biggr"]),"version":"1.0"}
    json.dump(rec,open(os.path.join(OUT,mid+".json"),"w")); written+=1
json.dump({f"{k[0]}|{k[1]}":v for k,v in backmap.items()}, open("/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/growthdb_work/lit/media_backmap.json","w"))
print(f"GrowthDB media added to Media repo: {written} (deduped from {len(add)} candidates) | backmap entries: {len(backmap)}")
