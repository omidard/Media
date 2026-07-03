#!/usr/bin/env python3
"""Map MediaDive ingredients -> BiGG exchange(s). Organic compounds map 1:1;
salts are dissociated into their ion exchanges; hydrolysates/extracts are marked complex."""
import json, sys, re
sys.path.insert(0,"/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
from map_metabolite import Mapper
m=Mapper()
DICT=json.load(open("/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools/bigg_metabolite_dict.json"))
def valid(bid): return bid in DICT and DICT[bid]["in_biggr"]

ings=json.load(open("ingredients.json")); ings=ings.get("data",ings) if isinstance(ings,dict) else ings
COMPLEX=re.compile(r"(peptone|tryptone|extract|hydrolysate|hydrolysat|digest|infusion|bacto|lab-lemco|casein|casamino|casitone|proteose|beef|yeast|meat|liver|brain|heart|milk|whey|molasses|rumen|gelatin|soyt?one|blood|serum|agar|broth|water|tween|resazurin|indicator|buffer\b)",re.I)

CATION=[("ammonium|\\(nh4\\)|nh4","nh4"),("ferric|fe\\(iii\\)|iron\\(iii\\)","fe3"),
 ("ferrous|fe\\(ii\\)|iron\\(ii\\)","fe2"),("iron|ferrum|\\bfe\\b","fe2"),
 ("sodium|\\bna\\b|\\bna-|na2|disodium|monosodium","na1"),
 ("potassium|\\bk\\b|\\bk-|dipotassium|monopotassium|k2","k"),
 ("calcium|\\bca\\b","ca2"),("magnesium|\\bmg\\b","mg2"),("manganese|\\bmn\\b","mn2"),
 ("copper|cupric|\\bcu\\b","cu2"),("zinc|\\bzn\\b","zn2"),("cobalt|\\bco\\b","cobalt2"),
 ("nickel|\\bni\\b","ni2")]
ANION=[("chloride","cl"),("sulfate|sulphate","so4"),("phosphate","pi"),
 ("bicarbonate|hydrogen carbonate","hco3"),("carbonate","hco3"),("nitrate","no3"),
 ("molybdate","mobd"),("selenite","slnt"),("selenate","sel"),("tungstate","tungs"),
 ("thiosulfate","tsul"),("acetate","ac"),("citrate","cit"),("nitrite","no2"),("sulfide","h2s")]
# formula-fragment anion detection (case-sensitive), applied to name+formula
ANION_F=[("S2O3","tsul"),("HPO4|H2PO4|PO4|PO3","pi"),("SO4|SO3","so4"),("HCO3|CO3","hco3"),
 ("NO3","no3"),("NO2","no2"),("Mo7O24|MoO4","mobd"),("WO4","tungs"),("SeO3","slnt"),("SeO4","sel"),
 ("Cl(?![a-z])","cl")]
CATION_F=[("NH4","nh4"),("Na(?![a-z])","na1"),("Ca(?![a-z])","ca2"),("Mg(?![a-z])","mg2"),
 ("Mn(?![a-z])","mn2"),("Fe(?![a-z])","fe2"),("Cu(?![a-z])","cu2"),("Zn(?![a-z])","zn2"),
 ("Co(?![a-z])","cobalt2"),("Ni(?![a-z])","ni2"),("K(?![a-z])","k")]
# organic bases that appear as *-chloride / *-hydrochloride
ORG_BASE={"choline":"chol","betaine":"glyb","cysteine":"cys__L","methylamine":"mma",
 "thiamine":"thm","pyridoxine":"pydxn","hemin":"pheme","hematin":"pheme"}
# named organic ingredients the name-mapper misses (metal-containing cofactors etc.) -> direct BiGG
ORG_NAMED={"vitamin b12":"cbl1","cyanocobalamin":"cbl1","cobalamin":"cbl1","vitamin b1":"thm",
 "vitamin b2":"ribflv","vitamin b6":"pydxn","vitamin b3":"nac","nicotinic acid":"nac",
 "nicotinamide":"ncam","folic acid":"fol","pantothenate":"pnto__R","calcium pantothenate":"pnto__R",
 "p-aminobenzoic acid":"4abz","para-aminobenzoic acid":"4abz","lipoic acid":"lipoate","hemin":"pheme"}

def dissociate(name, formula=None):
    n=name.lower(); raw=name+" "+(formula or "")
    # named organic cofactors first (avoid mis-dissociating metal-containing organics)
    for k,bid in ORG_NAMED.items():
        if k in n and valid(bid): return {f"EX_{bid}_e"}
    exch=set(); anion_found=False
    for pat,ion in ANION:
        if re.search(pat,n) and valid(ion): exch.add(f"EX_{ion}_e"); anion_found=True
    for pat,ion in ANION_F:
        if re.search(pat,raw) and valid(ion): exch.add(f"EX_{ion}_e"); anion_found=True
    # cation via English name (reliable); via FORMULA only if an anion confirms it's a salt
    cat=None
    for pat,ion in CATION:
        if re.search(pat,n): cat=ion; break
    if cat is None and anion_found:
        for pat,ion in CATION_F:
            if re.search(pat,raw): cat=ion; break
    if cat and valid(cat): exch.add(f"EX_{cat}_e")
    # organic base + chloride/hydrochloride (choline chloride etc.)
    for base,bid in ORG_BASE.items():
        if base in n and valid(bid):
            exch.add(f"EX_{bid}_e")
            if "chloride" in n and valid("cl"): exch.add("EX_cl_e")
    return exch

imap={}; complx={}; n_def=0; n_salt=0
for ig in ings:
    iid=str(ig["id"]); name=ig.get("name","")
    if not name: continue
    if COMPLEX.search(name) and not ig.get("ChEBI"):
        complx[iid]={"name":name}; continue
    # 1) direct organic
    hit=m.map(name=name, chebi=ig.get("ChEBI"))
    if hit and hit["in_biggr"]:
        imap[iid]={"name":hit["name"],"exchanges":[hit["exchange"]],"kind":"defined",
                   "method":hit["mapping_method"],"conf":hit["mapping_confidence"],"mass":ig.get("mass")}
        n_def+=1; continue
    # 2) salt dissociation
    ex=dissociate(name, ig.get("formula"))
    if ex:
        imap[iid]={"name":name,"exchanges":sorted(ex),"kind":"salt","method":"dissociation","conf":"inferred","mass":ig.get("mass")}
        n_salt+=1; continue
    complx[iid]={"name":name,"reason":"unmapped"}
json.dump(imap,open("ingredient_to_bigg.json","w")); json.dump(complx,open("complex_ingredients.json","w"))
print(f"ingredients {len(ings)} | defined-organic {n_def} | salts-dissociated {n_salt} | complex/unmapped {len(complx)}")
tot_ex=set(e for v in imap.values() for e in v["exchanges"]); print("distinct exchanges reachable:",len(tot_ex))
import itertools
print("salt examples:")
for iid,v in itertools.islice(((i,v) for i,v in imap.items() if v["kind"]=="salt"),10):
    print(f"  {v['name'][:30]:30s} -> {v['exchanges']}")
EOF_GUARD=1
