#!/usr/bin/env python3
"""Presence/absence matrix for the browser: all media x the most-variable compounds.
Each medium -> hex bitstring over the chosen compound columns + its category/food_group/source_db.

STALE-01: this builder had no caller in any workflow or doc, so the shipped matrix
was never regenerated (12,387 media against 13,515 on disk; 1,261 missing, 133
ghosts). It is now part of `make derived` and of CI.

COLUMN INSTABILITY -- read before consuming `bits`: the column set is chosen from
the data (compounds present in MIN_PREV..MAX_PREV of media, ranked by p(1-p)), so
regenerating against a different corpus silently re-indexes every bitstring. The
payload therefore carries `schema`, `built_at` and the selection thresholds, and a
consumer MUST read the `compounds` array from the same file it read `bits` from.
"""
import json, glob, re, os, datetime as dt
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
_files=sorted(glob.glob(os.path.join(REPO,"data","media","*.json")))
if not _files:
    raise SystemExit("FATAL: no media found under %s -- refusing to write an empty "
                     "presence_matrix.json over a published endpoint."
                     % os.path.join(REPO,"data","media"))
for fp in _files:
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
out={"schema":"mediadb-presence-matrix/2",
     "built_at":dt.date.today().isoformat(),
     "column_selection":{"min_prevalence":0.05,"max_prevalence":0.92,"max_columns":150,
                         "rank":"p*(1-p)",
                         "note":"data-dependent: bit positions are only valid against "
                                "the `compounds` array in this same file"},
     "n_media":N,"n_compounds":K,"rowbytes":rowbytes,
     "compounds":[{"exchange":e,"name":nm(e),"freq":round(freq[e]/N,3)} for e in cols],
     "media":[{"id":m["id"],"name":m["name"],"category":m["category"],"food_group":m["food_group"],
               "source_db":m["source_db"],"bits":bits(m["exs"])} for m in media]}
json.dump(out,open(os.path.join(REPO,"data","presence_matrix.json"),"w"),separators=(",",":"))
sz=os.path.getsize(os.path.join(REPO,"data","presence_matrix.json"))
print(f"presence_matrix.json: {N} media x {K} compounds, {round(sz/1e6,2)} MB")
print("sample columns:", [c["name"][:16] for c in out["compounds"][:12]])
