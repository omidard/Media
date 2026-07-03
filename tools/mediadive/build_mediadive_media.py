#!/usr/bin/env python3
"""Build one medium per MediaDive/DSMZ recipe. Defined compounds mapped exactly (g/L->mM via
molar mass); salts dissociated to ion exchanges; undefined hydrolysates/extracts rendered as a
labeled in-silico approximation (AA + nucleosides + vitamins). Each cited to DSMZ MediaDive."""
import json, os, re, glob
REPO="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
MD="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/mediadive"
OUT=os.path.join(REPO,"data","media")
DICT=json.load(open(os.path.join(REPO,"tools","bigg_metabolite_dict.json")))
imap=json.load(open(os.path.join(MD,"ingredient_to_bigg.json")))
complx=json.load(open(os.path.join(MD,"complex_ingredients.json")))
medialist={str(x["id"]):x for x in (json.load(open(os.path.join(MD,"mdive.json"))).get("data"))}

AA20=["ala__L","arg__L","asn__L","asp__L","cys__L","gln__L","glu__L","gly","his__L","ile__L","leu__L","lys__L","met__L","phe__L","pro__L","ser__L","thr__L","trp__L","tyr__L","val__L"]
NUC=["adn","gsn","cytd","uri","thymd","ins"]; VIT=["btn","fol","pnto__R","ribflv","thm","nac","pydxn","cbl1","4abz"]
IGNORE_EX={"EX_h2o_e"}  # water handled as base
BASEO2={"aerobic":-10,"anaerobic":0}
def nm(bid): return DICT.get(bid,{}).get("name",bid)
def xr(bid): return DICT.get(bid,{}).get("xrefs",{})

def comp(ex, lb, method, conf, gl=None, mM=None):
    b=re.match(r"EX_(.+)_e$",ex); bid=b.group(1) if b else ex
    c={"name":nm(bid),"bigg_metabolite":bid,"exchange":ex,"lower_bound":float(lb),"upper_bound":1000.0,
       "concentration_mM":mM,"xref":xr(bid),"in_biggr":DICT.get(bid,{}).get("in_biggr",False),
       "mapping_method":method,"mapping_confidence":conf}
    if gl is not None: c["recipe_g_l"]=gl
    return c

written=0; index_rows=[]
for fp in glob.glob(os.path.join(MD,"details","*.json")):
    mid=os.path.basename(fp)[:-5]
    try: det=json.load(open(fp))
    except: continue
    data=det.get("data") or {}
    med=data.get("medium") or medialist.get(mid,{})
    if not med: continue
    name=med.get("name") or f"DSMZ medium {mid}"
    complex_medium = str(med.get("complex_medium","")).lower() in ("yes","1")
    anaer = bool(re.search(r"anaerob", (name+" "+str(med.get("description") or "")), re.I))
    comps={}   # exchange -> component (dedupe, keep max concentration)
    undefined=[]
    for sol in (data.get("solutions") or []):
        for r in (sol.get("recipe") or []):
            cid=str(r.get("compound_id")); gl=r.get("g_l"); cname=r.get("compound","")
            if cid in imap:
                v=imap[cid]
                if v["kind"]=="defined" and v.get("mass") and gl:
                    try: mM=round(float(gl)/float(v["mass"])*1000.0,4)
                    except: mM=None
                else: mM=None
                for ex in v["exchanges"]:
                    if ex in IGNORE_EX: continue
                    is_min = ex.strip("EX_e").strip("_") in ("pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","ni2","mobd","tungs","slnt","sel","hco3","no3")
                    lb = -1000 if (v["kind"]=="salt" or is_min) else -1.0
                    if ex not in comps or (mM and (comps[ex].get("concentration_mM") or 0)<mM):
                        comps[ex]=comp(ex, lb, "mediadive_"+v["kind"], v["conf"], gl=gl, mM=mM)
            elif cid in complx or (cname and re.search(r"(peptone|tryptone|extract|hydrolysate|digest|infusion|casein|yeast|beef|meat|blood|serum|casitone|proteose|casamino)",cname,re.I)):
                undefined.append(cname)
    if not comps and not undefined: continue
    # add mineral base essentials if missing (so medium can support growth)
    for ex in ["EX_h2o_e","EX_h_e","EX_co2_e"]:
        comps.setdefault(ex, comp(ex,-1000,"base","convention"))
    comps["EX_o2_e"]=comp("EX_o2_e", BASEO2["anaerobic"] if anaer else BASEO2["aerobic"], "base","convention")
    # complex approximation
    if undefined:
        for bid in AA20+NUC+VIT:
            ex=f"EX_{bid}_e"
            if DICT.get(bid,{}).get("in_biggr") and ex not in comps:
                comps[ex]=comp(ex, -1.0, "hydrolysate_approximation","convention")
    n_defined_real = sum(1 for c in comps.values() if c["mapping_method"].startswith("mediadive"))
    components=sorted(comps.values(), key=lambda c:c["exchange"])
    ref=med.get("reference"); link=med.get("link")
    cite=f"DSMZ MediaDive (Koblitz J et al., Nucleic Acids Res 2023); DSMZ Medium {mid}: {name}."
    if ref: cite+=f" Ref: {ref}."
    rec={"id":f"mediadive_{mid}","name":f"{name} (DSMZ {mid})","category":"laboratory",
         "organism_scope":"prokaryote-generic","aerobic":not anaer,
         "description":f"DSMZ culture medium {mid} ({'complex' if complex_medium else 'defined'}). "
             +("Contains undefined components ("+", ".join(sorted(set(undefined))[:6])+") rendered as a labeled in-silico hydrolysate approximation. " if undefined else "")
             +"Defined compounds mapped to BiGG (g/L->mM via molar mass); salts dissociated to ion exchanges.",
         "namespace":"bigg","defined":not complex_medium,
         "provenance":{"source_type":"database","citation":cite,"doi":"10.1093/nar/gkac803",
            "url":link or f"https://mediadive.dsmz.de/medium/{mid}",
            "notes":"Presence-based uptake bounds; recipe_g_l + concentration_mM retained. "+("Undefined hydrolysates approximated as amino acids + nucleosides + vitamins (labeled)." if undefined else "Fully defined.")},
         "components":components,
         "unmapped":[{"name":u,"reason":"undefined (hydrolysate/extract)"} for u in sorted(set(undefined))],
         "n_components":len(components),"n_mapped":len(components),
         "n_in_biggr":sum(1 for c in components if c["in_biggr"]),
         "n_defined_components":n_defined_real,"complex_medium":complex_medium,"version":"1.0"}
    json.dump(rec, open(os.path.join(OUT, rec["id"]+".json"),"w"))
    written+=1
    index_rows.append({"id":rec["id"],"defined":rec["defined"],"n_components":rec["n_components"],"n_defined":n_defined_real})
json.dump(index_rows, open(os.path.join(MD,"md_index.json"),"w"))
print(f"MediaDive media written: {written}")
dfn=sum(1 for r in index_rows if r["defined"]); print(f"  defined: {dfn} | complex: {written-dfn}")
import statistics
nd=[r["n_defined"] for r in index_rows]
print(f"  defined-components/medium: min {min(nd)} median {int(statistics.median(nd))} max {max(nd)}")
