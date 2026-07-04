import json, glob, os, re, sys
sys.path.insert(0,"repo/tools")
from map_metabolite import Mapper
# reuse salt dissociation from the lit-media builder
import importlib.util
spec=importlib.util.spec_from_file_location("blm","lit/build_lit_media.py")
m=Mapper()
DICT=json.load(open("repo/tools/bigg_metabolite_dict.json"))
def valid(b): return b in DICT and DICT[b]["in_biggr"]
def nm(b): return DICT.get(b,{}).get("name",b)
def xr(b): return DICT.get(b,{}).get("xrefs",{})
MINSET={"pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","ni2","mobd","tungs","slnt","sel","hco3","no3","o2","h2o","h","co2","bo"}
def is_min(b): return b in MINSET
# undefined mixtures -> keep unmapped
MIX=re.compile(r"agar|yeast extract|beef extract|meat extract|peptone|tryptone|casitone|casamino|hydrolysate|extract\b|broth|blood|serum|gelatin|casein|tween|resazurin|vitamin solution|trace element|mineral solution|rumen fluid|digest|infusion|bacto",re.I)
# salts / simple inorganics dissociation
CAT=[("koh|potassium","k"),("naoh|sodium","na1"),("nh4|ammoni","nh4"),("cacl|ca\\(|calcium","ca2"),("mgcl|mgso|magnesium","mg2"),
 ("fecl|feso|ferr|iron","fe2"),("mncl|mnso|mangan","mn2"),("zncl|znso|zinc","zn2"),("cucl|cuso|copper|cupric","cu2"),
 ("cocl|coso|cobalt","cobalt2"),("nicl|niso|nickel","ni2")]
ANF=[("h3bo3|boric|borate","bo"),("hcl|chloride","cl"),("h2so4|sulf|sulph","so4"),("hno3|nitrate","no3"),("h3po4|phosphate","pi"),("carbonate|hco3|co3","hco3")]
def try_map(name):
    n=name.lower().strip()
    if "water" in n or n in ("h2o","aqua"): return [("h2o","name_water","inferred")] if valid("h2o") else []
    hit=m.map(name=name)
    if hit and hit["in_biggr"]: return [(hit["bigg_metabolite"],hit["mapping_method"],hit["mapping_confidence"])]
    ex=[]
    for pat,ion in ANF:
        if re.search(pat,n) and valid(ion): ex.append((ion,"salt_dissociation","inferred"))
    for pat,ion in CAT:
        if re.search(pat,n) and valid(ion): ex.append((ion,"salt_dissociation","inferred"))
    return ex

moved=0; files=0
for f in glob.glob("repo/data/media/*.json"):
    d=json.load(open(f)); unm=d.get("unmapped") or []
    if not unm: continue
    have={c["exchange"] for c in d["components"]}; keep=[]; changed=False
    for item in unm:
        name=item.get("name") if isinstance(item,dict) else item
        if not name or MIX.search(name): keep.append(item); continue
        got=try_map(name)
        if got:
            for bid,meth,conf in got:
                exi=f"EX_{bid}_e"
                if exi not in have:
                    have.add(exi)
                    d["components"].append({"name":nm(bid),"bigg_metabolite":bid,"exchange":exi,
                        "lower_bound":(-1000 if is_min(bid) else -1.0),"upper_bound":1000.0,"concentration_mM":None,
                        "xref":xr(bid),"in_biggr":True,"mapping_method":"remap_"+meth,"mapping_confidence":conf})
                    moved+=1; changed=True
        else: keep.append(item)
    if changed:
        d["unmapped"]=keep; d["components"]=sorted(d["components"],key=lambda c:c["exchange"])
        d["n_components"]=len(d["components"]); d["n_mapped"]=len(d["components"]); d["n_in_biggr"]=sum(1 for c in d["components"] if c["in_biggr"])
        json.dump(d,open(f,"w")); files+=1
print(f"re-mapped Media unmapped: moved {moved} components into {files} media")
