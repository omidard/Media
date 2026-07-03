#!/usr/bin/env python3
"""Presence/absence matrix for the browser: all media x the most-variable compounds.
Each medium -> hex bitstring over the chosen compound columns + its category/food_group/source_db."""
import json, glob, re, os
from collections import Counter
REPO=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT=json.load(open(os.path.join(REPO,"tools","bigg_metabolite_dict.json")))
def nm(ex):
    b=re.match(r"EX_(.+)_e$",ex); bid=b.group(1) if b else ex
    return DICT.get(bid,{}).get("name",bid)
def sdb(idv,st):
    if idv.startswith('mediadive_'):return 'DSMZ MediaDive'
    if idv.startswith('usda_'):return 'USDA FDC'
    if idv.startswith('food_'):return 'FooDB'
    if idv.startswith('lit_'):return 'Literature'
    if idv.startswith('biospecimen_hmdb_'):return 'HMDB'
    if idv.startswith('biospecimen_bmdb_'):return 'BMDB'
    if idv.startswith('biospecimen_'):return 'Published'
    return st

media=[]; freq=Counter()
for fp in glob.glob(os.path.join(REPO,"data","media","*.json")):
    d=json.load(open(fp))
    exs=set(c["exchange"] for c in d["components"])
    for e in exs: freq[e]+=1
    media.append({"id":d["id"],"name":d["name"],"category":d["category"],
                  "food_group":d.get("food_group",""),"source_db":sdb(d["id"],d["provenance"]["source_type"]),
                  "exs":exs})
N=len(media)
# columns = most variable compounds (present in 5%..92% of media), top 150 by variance p(1-p)
cand=[(e,c/N) for e,c in freq.items() if 0.05<=c/N<=0.92]
cand.sort(key=lambda x:-(x[1]*(1-x[1])))
cols=[e for e,_ in cand[:150]]
colidx={e:i for i,e in enumerate(cols)}
K=len(cols); rowbytes=(K+7)//8
def bits(exs):
    ba=bytearray(rowbytes)
    for e in exs:
        j=colidx.get(e)
        if j is not None: ba[j>>3]|=(1<<(j&7))
    return ba.hex()
out={"n_media":N,"n_compounds":K,"rowbytes":rowbytes,
     "compounds":[{"exchange":e,"name":nm(e),"freq":round(freq[e]/N,3)} for e in cols],
     "media":[{"id":m["id"],"name":m["name"],"category":m["category"],"food_group":m["food_group"],
               "source_db":m["source_db"],"bits":bits(m["exs"])} for m in media]}
json.dump(out,open(os.path.join(REPO,"data","presence_matrix.json"),"w"),separators=(",",":"))
sz=os.path.getsize(os.path.join(REPO,"data","presence_matrix.json"))
print(f"presence_matrix.json: {N} media x {K} compounds, {round(sz/1e6,2)} MB")
print("sample columns:", [c["name"][:16] for c in out["compounds"][:12]])
