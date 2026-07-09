#!/usr/bin/env python3
"""Formulate missing base+carbon media (M9/MOPS/M63 + a carbon source) from the standard recipe
template, cite them, add to Media, so GrowthDB base-medium records link exactly."""
import json, os, sys
sys.path.insert(0,"repo/tools"); from map_metabolite import Mapper
m=Mapper(); MED="repo/data/media"
IDX={x["id"] for x in json.load(open("repo/data/index.json"))["media"]}
# carbon labels aligned with curate.py's carbon_of()
CARBON=[("glucose|dextrose","glucose"),("glycerol","glycerol"),("acetate|acetic","acetate"),("succinate|succinic","succinate"),
 ("lactate|lactic","lactate"),("pyruvate","pyruvate"),("fructose","fructose"),("xylose","xylose"),("galactose","galactose"),
 ("mannitol","mannitol"),("sucrose","sucrose"),("citrate","citrate"),("gluconate","gluconate"),("ethanol","ethanol"),
 ("methanol","methanol"),("arabinose","arabinose"),("maltose","maltose"),("mannose","mannose"),("sorbitol","sorbitol"),
 ("benzoate|benzoic","benzoate"),("ribose","ribose"),("trehalose","trehalose"),("cellobiose","cellobiose"),("xylan",None),
 ("glutamate","L-glutamate"),("casamino","casamino acids"),("propionate|propionic","propionate"),("butyrate|butyric","butyrate")]
import re
def carbon_of(nl):
    for pat,lab in CARBON:
        if lab and re.search(pat,nl): return lab
    return None
TEMPL={"m9":("m9_glucose_aerobic","EX_glc__D_e","M9 minimal salts (Sambrook & Russell, Molecular Cloning 3rd ed., CSHL 2001)"),
       "mops":("mops_minimal_glucose","EX_glc__D_e","MOPS minimal medium (Neidhardt et al., J Bacteriol 119:736, 1974)")}
def base_of(nl):
    if re.search(r"\bm9\b",nl): return "m9"
    if re.search(r"\bmops\b",nl): return "mops"
    return None
tmpl_cache={}
def get_base_comps(base):
    if base in tmpl_cache: return tmpl_cache[base]
    tid,cex,cite=TEMPL[base]
    t=json.load(open(f"{MED}/{tid}.json"))
    comps=[dict(c) for c in t["components"] if c["exchange"]!=cex]
    tmpl_cache[base]=(comps,cite); return tmpl_cache[base]

recs=json.load(open("../growthdb_work/repo/data/growth_records.json"))
made=0; backmap={}
for r in recs:
    if not r["id"].startswith(("lit_","flux_")): continue
    med=r["medium"]; name=med.get("description") or ""; nl=name.lower()
    if med.get("media_id"): continue
    base=base_of(nl)
    if not base: continue
    carb=carbon_of(nl)
    if not carb: continue
    h=m.map(name=carb)
    if not h: continue
    cid=h["bigg_metabolite"]; cex=h["exchange"]
    mid=f"{base}_{re.sub(r'[^a-z0-9]','',carb.lower())}"
    if mid not in IDX and mid not in backmap.values():
        comps,cite=get_base_comps(base); comps=[dict(c) for c in comps]
        if cex not in {c["exchange"] for c in comps}:
            comps.append({"name":h["name"],"bigg_metabolite":cid,"exchange":cex,"lower_bound":-10.0,"upper_bound":1000.0,
                "concentration_mM":None,"xref":h.get("xref",{}),"in_biggr":h.get("in_biggr",False),"mapping_method":"carbon_source","mapping_confidence":"exact"})
        cl=sorted(comps,key=lambda c:c["exchange"])
        rec={"id":mid,"name":f"{base.upper()} minimal medium ({carb})","category":"laboratory","organism_scope":"prokaryote-generic","aerobic":True,
             "description":f"{base.upper()} minimal salts with {carb} as the carbon source.","namespace":"bigg",
             "provenance":{"source_type":"standard","citation":f"{cite}; carbon source ({carb}) per the GrowthDB growth record.","doi":"","url":"","notes":f"{base.upper()} salts base + carbon source, formulated from the standard recipe."},
             "components":cl,"unmapped":[],"n_components":len(cl),"n_mapped":len(cl),"n_in_biggr":sum(1 for c in cl if c["in_biggr"]),"version":"1.0"}
        json.dump(rec,open(f"{MED}/{mid}.json","w")); IDX.add(mid); made+=1
    backmap[(r.get("provenance",{}).get("pmcid",""),name)]=mid
# merge backmap so curate links
BM="../growthdb_work/lit/media_backmap.json"
ex=json.load(open(BM)) if os.path.exists(BM) else {}
for (p,n),v in backmap.items(): ex[f"{p}|{n}"]=v
json.dump(ex,open(BM,"w"))
print(f"formulated base+carbon media: {made} | linked backmap entries: {len(backmap)}")
