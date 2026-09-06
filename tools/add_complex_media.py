#!/usr/bin/env python3
"""Catalog EVERY paper medium that has a stated composition into Media — including complex/
peptone-based media that map to few BiGG exchanges. Mapped components become exchanges; the
biological extracts (peptone, yeast extract, casitone…) are kept in `unmapped` and the medium is
honestly labelled. Dedup by name+composition; merge backmap so GrowthDB links resolve."""
import json, os, re, sys

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from map_metabolite import Mapper  # noqa: E402
from mediapaths import REPO, OUT_ROOT, repo_file, source_path, out_media_dir  # noqa: E402
m=Mapper()
OUT = out_media_dir()   # staging tree ($MEDIA_OUT), never data/media -- see PIPE-01
DICT=json.load(open(repo_file("tools","bigg_metabolite_dict.json")))
def valid(b): return b in DICT and DICT[b]["in_biggr"]
def nm(b): return DICT.get(b,{}).get("name",b)
def xr(b): return DICT.get(b,{}).get("xrefs",{})
MINSET={"pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","ni2","mobd","tungs","slnt","sel","hco3","no3","o2","h2o","h","co2","bo"}
def is_min(b): return b in MINSET
def slug(s): return re.sub(r"[^a-z0-9]+","_",(s or "medium").lower()).strip("_")[:44] or "medium"
def nkey(s): return re.sub(r"[^a-z0-9]","",(s or "").lower())

INP=sys.argv[1]
# The GrowthDB back-map is a cross-session handoff that was deleted with its
# scratchpad; it is optional here, and its absence is recorded, not defaulted away.
_BM_IN = source_path("growthdb", "media_backmap.json")
_BM_OUT = os.path.join(OUT_ROOT, "growthdb", "media_backmap.json")
BMPATH = _BM_IN if os.path.exists(_BM_IN) else _BM_OUT
add=json.load(open(INP))["pending_media_for_media_repo"]
_bm=json.load(open(BMPATH)) if os.path.exists(BMPATH) else {}
backmap={tuple(k.split("|",1)):v for k,v in _bm.items() if "|" in k}
# existing composition-name signatures to dedup against
seen={}
import glob as _g
_dedup_unreadable=[]   # records we could not read, so could not dedup against
for _f in _g.glob(os.path.join(OUT,"growthlit_*.json"))+_g.glob(os.path.join(OUT,"complexlit_*.json")):
    try:
        _d=json.load(open(_f)); sig=nkey(_d["name"].split(" (")[0]); seen.setdefault(sig,_d["id"])
    except (ValueError, OSError, KeyError) as _exc:
        # A record we cannot read is a record we cannot dedup against, so it is
        # reported: silently skipping it produces duplicate media.
        _dedup_unreadable.append((os.path.basename(_f), type(_exc).__name__))
written=0
for item in add:
    name=item.get("medium_name") or "medium"; pmc=item.get("pmcid",""); comp=item.get("composition") or []
    if (pmc,name) in backmap: continue
    mapped={}; unmapped=[]
    for c in comp:
        cn=c.get("name","");
        if not cn: continue
        h=m.map(name=cn)
        if h and h["in_biggr"]:
            b=h["bigg_metabolite"]; ex=h["exchange"]
            mapped.setdefault(ex,{"name":h["name"],"bigg_metabolite":b,"exchange":ex,"lower_bound":(-1000 if is_min(b) else -1.0),
                "upper_bound":1000.0,"concentration_mM":None,"paper_amount":(str(c.get("amount"))+" "+str(c.get("unit")) if c.get("amount") else None),
                "xref":xr(b),"in_biggr":True,"mapping_method":h["mapping_method"],"mapping_confidence":h["mapping_confidence"]})
        else:
            unmapped.append({"name":cn,"reason":"undefined/complex (extract, hydrolysate or unmatched)"})
    if not comp: continue
    sig=nkey(name.split(" (")[0])
    if sig in seen: backmap[(pmc,name)]=seen[sig]; continue
    complex_flag=len(mapped)<3
    if complex_flag and "EX_o2_e" not in mapped and valid("o2"):
        mapped["EX_o2_e"]={"name":"O2","bigg_metabolite":"o2","exchange":"EX_o2_e","lower_bound":-10.0,"upper_bound":1000.0,"concentration_mM":None,"xref":xr("o2"),"in_biggr":True,"mapping_method":"base","mapping_confidence":"convention"}
    mid=("complexlit_" if complex_flag else "growthlit_")+f"{pmc}_{slug(name)}"
    seen[sig]=mid; backmap[(pmc,name)]=mid
    cl=sorted(mapped.values(),key=lambda c:c["exchange"])
    rec={"id":mid,"name":f"{name} ({pmc})","category":"laboratory","organism_scope":"prokaryote-generic","aerobic":True,
         "description":f"{name} — medium reported in {pmc}"+(" (complex/undefined base — extracts not BiGG-mappable)" if complex_flag else "")+".","namespace":"bigg",
         "provenance":{"source_type":"literature","citation":f"Medium composition from {pmc} (see GrowthDB record).","doi":"","url":f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/",
             "notes":("Complex medium: chemically-defined portion mapped to BiGG; biological extracts listed in `unmapped`. " if complex_flag else "Composition mapped to BiGG (mapper + salt dissociation). ")+"Added via GrowthDB curation."},
         "components":cl,"unmapped":unmapped,"n_components":len(cl),"n_mapped":len(cl),"n_in_biggr":sum(1 for c in cl if c["in_biggr"]),
         "complex":complex_flag,"version":"1.0"}
    json.dump(rec,open(os.path.join(OUT,mid+".json"),"w")); written+=1
os.makedirs(os.path.dirname(_BM_OUT), exist_ok=True)
json.dump({f"{k[0]}|{k[1]}":v for k,v in backmap.items()}, open(_BM_OUT,"w"))
print(f"cataloged media (incl. complex): {written} | backmap entries: {len(backmap)}")
