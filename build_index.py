import json, glob, os
from collections import Counter
def source_db(idv, prov, food_group):
    if idv.startswith('mediadive_'): return 'DSMZ MediaDive'
    if idv.startswith('usda_'): return 'USDA FoodData Central'
    if idv.startswith('food_'): return 'FooDB'
    if idv.startswith('lit_'): return 'Literature (GEM papers)'
    if idv.startswith('growthlit_'): return 'Literature (GrowthDB)'
    if idv.startswith('biospecimen_hmdb_'): return 'HMDB'
    if idv.startswith('biospecimen_'): return 'Published (HMDB-derived)'
    return prov.get('source_type','')
# curation tier — lower = more trustworthy; drives the default table order so the
# most rigorously curated media lead ("the frontier of the collection").
#   0 curated   : std_ canonical reference collection (the flagship named media)
#   1 expert    : expert-curated canonical formulation applied to another record
#   2 verified  : paper-verified against the source publication
#   3 database  : sourced from a curated database (DSMZ/USDA/FooDB/HMDB/BMDB/seed)
#   4 auto      : auto-extracted from literature, not manually verified
CURATION = {0:"curated", 1:"expert", 2:"verified", 3:"database", 4:"auto"}
def curation_tier(idv, ver):
    ver = ver or ""
    if idv.startswith("std_"): return 0
    if ver.startswith("expert-curated"): return 1
    if ver.startswith("paper-verified"): return 2
    if idv.startswith(("lit_","complexlit_","growthlit_")): return 4
    return 3
rows=[]
for fp in sorted(glob.glob("data/media/*.json")):
    d=json.load(open(fp))
    cov=d.get("coverage") or {}
    tier=curation_tier(d["id"], (d.get("provenance") or {}).get("verification"))
    rows.append({k:d.get(k) for k in ("id","name","category","organism_scope","aerobic","oxygen",
        "n_components","n_mapped","n_in_biggr","namespace")}
        | {"source_type":d["provenance"]["source_type"],
           "source_db":source_db(d["id"],d["provenance"],d.get("food_group","")),
           "defined":d.get("defined",""),
           "citation":d["provenance"]["citation"][:140],
           "food_group":d.get("food_group",""),
           "tier":tier,"curation":CURATION[tier],
           "n_uncovered":cov.get("n_uncovered",0),
           "pct_covered":cov.get("pct_covered",100.0)})
cat=Counter(r["category"] for r in rows); sdb=Counter(r["source_db"] for r in rows)
cur=Counter(r["curation"] for r in rows)
json.dump({"count":len(rows),"by_category":dict(cat),"by_source_db":dict(sdb),
           "by_curation":dict(cur),"media":rows}, open("data/index.json","w"), indent=0)
print("index media:", len(rows), "| category:", dict(cat)); print("by source_db:", dict(sdb))
print("by curation:", dict(cur))
