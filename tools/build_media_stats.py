import json, glob
from collections import Counter
cat=Counter(); src=Counter(); grp=Counter(); exch=Counter(); ncomp=[]
media=glob.glob("data/media/*.json")
for fp in media:
    d=json.load(open(fp))
    cat[d["category"]]+=1
    src[d["provenance"]["source_type"]]+=1
    if d.get("food_group"): grp[d["food_group"]]+=1
    ncomp.append(d["n_components"])
    for c in d["components"]:
        if c.get("mapping_method")!="mineral_base":
            exch[c["exchange"]]+=1
top=exch.most_common(40)
# attach names
dic=json.load(open("tools/bigg_metabolite_dict.json"))
import re
def nm(ex):
    m=re.match(r"EX_(.+)_e$",ex); b=m.group(1) if m else ex
    return dic.get(b,{}).get("name",b)
json.dump({"total":len(media),"by_category":dict(cat),"by_source":dict(src),
    "by_food_group":dict(grp.most_common()),
    "top_exchanges":[{"exchange":e,"name":nm(e),"n_media":c} for e,c in top],
    "ncomp_min":min(ncomp),"ncomp_median":int(sorted(ncomp)[len(ncomp)//2]),"ncomp_max":max(ncomp)},
    open("data/media_stats.json","w"),indent=0)
print("stats:",len(media),"media | cats",dict(cat),"| sources",dict(src))
print("top exchanges:", [(e['name'],e['n_media']) for e in json.load(open('data/media_stats.json'))['top_exchanges'][:10]])
