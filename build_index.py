import json, glob, os
from collections import Counter
def source_db(idv, prov, food_group):
    if idv.startswith('mediadive_'): return 'DSMZ MediaDive'
    if idv.startswith('usda_'): return 'USDA FoodData Central'
    if idv.startswith('food_'): return 'FooDB'
    if idv.startswith('biospecimen_hmdb_'): return 'HMDB'
    if idv.startswith('biospecimen_'): return 'Published (HMDB-derived)'
    return prov.get('source_type','')
rows=[]
for fp in sorted(glob.glob("data/media/*.json")):
    d=json.load(open(fp))
    rows.append({k:d.get(k) for k in ("id","name","category","organism_scope","aerobic",
        "n_components","n_mapped","n_in_biggr","namespace")}
        | {"source_type":d["provenance"]["source_type"],
           "source_db":source_db(d["id"],d["provenance"],d.get("food_group","")),
           "defined":d.get("defined",""),
           "citation":d["provenance"]["citation"][:140],
           "food_group":d.get("food_group","")})
cat=Counter(r["category"] for r in rows); sdb=Counter(r["source_db"] for r in rows)
json.dump({"count":len(rows),"by_category":dict(cat),"by_source_db":dict(sdb),"media":rows}, open("data/index.json","w"), indent=0)
print("index media:", len(rows), "| category:", dict(cat)); print("by source_db:", dict(sdb))
