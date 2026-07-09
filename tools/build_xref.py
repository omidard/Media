#!/usr/bin/env python3
"""Enrich every BiGG metabolite with full cross-references via the MetaNetX hub (chem_xref +
chem_prop): KEGG, ChEBI, SEED(ModelSEED), HMDB, MetaCyc, LipidMaps, InChIKey, InChI. Also emit a
ChEBI/KEGG -> MNXM -> SEED/KEGG fallback so substrates with no BiGG exchange still get a valid
exchange id (EX_cpd#####_e ModelSEED, or EX_C#####_kegg)."""
import json, os
from collections import defaultdict
MX="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/metanetx"
TOOLS="repo/tools"
SRC={"bigg.metabolite":"bigg","kegg.compound":"kegg","keggC":"kegg","chebi":"chebi","CHEBI":"chebi",
     "seed.compound":"seed","seedM":"seed","hmdb":"hmdb","metacyc.compound":"metacyc","metacycM":"metacyc",
     "lipidmaps":"lipidmaps","lipidmapsM":"lipidmaps","reactome":"reactome","reactomeM":"reactome","sabiork.compound":"sabiork"}
def norm_id(key,idv):
    if key=="chebi": return idv.replace("CHEBI:","")
    if key=="seed": return idv.replace("M_","")
    return idv
mnx2x=defaultdict(dict); bigg2mnx={}; chebi2mnx={}; kegg2mnx={}
n=0
for line in open(os.path.join(MX,"chem_xref.tsv")):
    if line[0]=="#": continue
    p=line.rstrip("\n").split("\t")
    if len(p)<2 or ":" not in p[0]: continue
    pre,idv=p[0].split(":",1); mnx=p[1]
    key=SRC.get(pre)
    if not key: continue
    idv=norm_id(key,idv); mnx2x[mnx].setdefault(key,idv)
    if key=="bigg": bigg2mnx.setdefault(idv,mnx)
    elif key=="chebi": chebi2mnx.setdefault(idv,mnx)
    elif key=="kegg": kegg2mnx.setdefault(idv,mnx)
    n+=1
print("chem_xref lines used:",n,"| MNXM with xrefs:",len(mnx2x),"| bigg->mnx:",len(bigg2mnx))
# InChIKey/InChI/formula from chem_prop
for line in open(os.path.join(MX,"chem_prop.tsv")):
    if line[0]=="#": continue
    p=line.rstrip("\n").split("\t")
    if len(p)<8: continue
    mnx=p[0]
    if mnx in mnx2x:
        if len(p)>7 and p[7]: mnx2x[mnx]["inchikey"]=p[7]
        if len(p)>6 and p[6] and p[6]!="InChI=": mnx2x[mnx]["inchi"]=p[6]
        if len(p)>3 and p[3]: mnx2x[mnx].setdefault("formula",p[3])
# enrich the dict
DICT=json.load(open(os.path.join(TOOLS,"bigg_metabolite_dict.json")))
filled=defaultdict(int)
for bid,rec in DICT.items():
    x=dict(rec.get("xrefs") or {})
    mnx=bigg2mnx.get(bid) or x.get("mnx")
    if mnx:
        x["mnx"]=mnx
        for k,v in mnx2x.get(mnx,{}).items():
            if k=="bigg": continue
            if not x.get(k): x[k]=v; filled[k]+=1
    rec["xrefs"]=x
json.dump(DICT,open(os.path.join(TOOLS,"bigg_metabolite_dict.json"),"w"))
print("newly filled xref keys:",dict(filled))
# fallback map for exchange-id formulation from ChEBI/KEGG
mnx2seed={m:x["seed"] for m,x in mnx2x.items() if x.get("seed")}
mnx2kegg={m:x["kegg"] for m,x in mnx2x.items() if x.get("kegg")}
json.dump({"chebi2mnx":chebi2mnx,"kegg2mnx":kegg2mnx,"mnx2seed":mnx2seed,"mnx2kegg":mnx2kegg},
          open(os.path.join(TOOLS,"xref_fallback.json"),"w"))
print("fallback: chebi2mnx",len(chebi2mnx),"kegg2mnx",len(kegg2mnx),"mnx2seed",len(mnx2seed))
# coverage report
from collections import Counter
cov=Counter()
for v in DICT.values():
    for k in (v.get("xrefs") or {}): cov[k]+=1
print("enriched dict xref coverage:",dict(cov))
