import json, glob, os
from collections import Counter
rows=[]
for fp in sorted(glob.glob("data/media/*.json")):
    d=json.load(open(fp))
    rows.append({k:d.get(k) for k in ("id","name","category","organism_scope","aerobic",
        "n_components","n_mapped","n_in_biggr","namespace")}
        | {"source_type":d["provenance"]["source_type"],
           "citation":d["provenance"]["citation"][:140],
           "doi":d["provenance"].get("doi",""),
           "food_group":d.get("food_group","")})
cat=Counter(r["category"] for r in rows)
json.dump({"count":len(rows),"by_category":dict(cat),"media":rows}, open("data/index.json","w"), indent=0)
print("index media:", len(rows), "| by category:", dict(cat))
