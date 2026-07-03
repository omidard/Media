#!/usr/bin/env python3
"""Formulate one GEM-ready medium per FooDB food: mapped organic components (from
FooDB Content) + a documented M9 mineral base. Retains FooDB content values + per-food
content citations. Presence-based uptake bounds (physical content kept for custom scaling)."""
import csv, json, os, re, sys
sys.path.insert(0, "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
from map_metabolite import Mapper

CSVD = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/foodb/foodb_2020_04_07_csv"
REPO = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT = os.path.join(REPO, "data", "media")
csv.field_size_limit(10**7)
DICT = json.load(open(os.path.join(REPO, "tools", "bigg_metabolite_dict.json")))
cmap = json.load(open(os.path.join(CSVD, "..", "compound_to_bigg.json")))   # foodb compound id -> {bigg,exchange,name,method,conf}
MIN_EXCH = 6

# clear any stale food media from a previous run (measured-content fix)
import glob as _g
for _f in _g.glob(os.path.join(OUT, "food_*.json")):
    os.remove(_f)

# exclude non-dietary intracellular intermediates that slip through by name/xref
BAD = re.compile(r"(coa$|_coa|trna|\[protein|acp\b|acyl-carrier|thioredoxin|ferredoxin|flavodoxin)", re.I)

# M9 mineral base (inorganic scaffold so a food medium can support growth) — documented
MINERALS = {"EX_pi_e":-1000,"EX_so4_e":-1000,"EX_nh4_e":-1000,"EX_k_e":-1000,"EX_na1_e":-1000,
  "EX_cl_e":-1000,"EX_mg2_e":-1000,"EX_ca2_e":-1000,"EX_fe2_e":-1000,"EX_fe3_e":-1000,
  "EX_mn2_e":-1000,"EX_zn2_e":-1000,"EX_cu2_e":-1000,"EX_cobalt2_e":-1000,"EX_ni2_e":-1000,
  "EX_mobd_e":-1000,"EX_h2o_e":-1000,"EX_h_e":-1000,"EX_co2_e":-1000,"EX_o2_e":-10}

# foods
foods = {}
with open(os.path.join(CSVD, "Food.csv"), encoding="utf-8", errors="replace") as f:
    r = csv.DictReader(f)
    for row in r:
        foods[row["id"]] = {"name": row["name"], "group": row.get("food_group",""),
                            "subgroup": row.get("food_subgroup",""), "public_id": row.get("public_id",""),
                            "sci": row.get("name_scientific","")}

# stream Content: gather mapped organic components per food + citations
food_comp = {}   # food_id -> { exchange: {content, unit, cite} }
food_cites = {}  # food_id -> set(citation)
with open(os.path.join(CSVD, "Content.csv"), encoding="utf-8", errors="replace") as f:
    r = csv.DictReader(f)
    for row in r:
        if row.get("source_type") != "Compound": continue
        cid = row.get("source_id")
        mp = cmap.get(cid)
        if not mp: continue
        if BAD.search(mp["name"]) or BAD.search(mp["bigg"]): continue   # drop non-dietary intermediates
        # REQUIRE a real measured concentration (excludes FooDB predicted/expected rows)
        content = row.get("standard_content") or ""
        try: cval = float(content)
        except: continue
        if cval <= 0: continue
        fid = row.get("food_id")
        if fid not in foods: continue
        ex = mp["exchange"]
        d = food_comp.setdefault(fid, {})
        cur = d.get(ex)
        if (cur is None) or (cval > (cur.get("content") or 0)):
            d[ex] = {"content": cval, "unit": row.get("orig_unit",""), "cite": row.get("citation","")}
        cc = row.get("citation")
        if cc: food_cites.setdefault(fid, set()).add(cc)

def slug(s):
    return re.sub(r"[^a-z0-9]+","_", s.lower()).strip("_")[:48]

written=0; index_rows=[]
for fid, comps in food_comp.items():
    organic = [ex for ex in comps if ex not in MINERALS]
    if len(organic) < MIN_EXCH: continue
    fo = foods[fid]
    components=[]
    for ex in sorted(set(list(comps.keys()) + list(MINERALS.keys()))):
        met = re.match(r"EX_(.+)_e$", ex)
        bid = met.group(1) if met else ex
        d = DICT.get(bid, {})
        is_food = ex in comps and ex not in MINERALS
        fc = comps.get(ex, {})
        comp = {"name": d.get("name", bid), "bigg_metabolite": bid, "exchange": ex,
                "lower_bound": (-1.0 if is_food else MINERALS.get(ex, -1000)),
                "upper_bound": 1000.0, "concentration_mM": None,
                "xref": d.get("xrefs", {}), "in_biggr": d.get("in_biggr", False),
                "mapping_method": "foodb_inchikey_name" if is_food else "mineral_base",
                "mapping_confidence": "exact" if is_food else "convention"}
        if is_food:
            comp["foodb_content"] = fc.get("content"); comp["foodb_unit"] = fc.get("unit")
        components.append(comp)
    cites = sorted(food_cites.get(fid, []))[:8]
    rec = {"id": "food_"+ (fo["public_id"] or slug(fo["name"])),
           "name": fo["name"] + " (food medium)", "category": "food",
           "organism_scope": "food microbiome / general", "aerobic": True,
           "description": f"Food-derived medium: metabolizable components of {fo['name']}"
                          + (f" ({fo['sci']})" if fo['sci'] else "") + f" [{fo['group']}] from FooDB, "
                          + "plus a standard M9 mineral base. Organic components use presence-based uptake bounds; FooDB content values are retained per component for custom scaling.",
           "namespace": "bigg",
           "provenance": {"source_type": "database",
             "citation": f"FooDB v2020-04-07 (Wishart DS et al., foodb.ca). Content sources: {', '.join(cites) if cites else 'FooDB'}.",
             "doi": "", "url": f"https://foodb.ca/foods/{fo['public_id']}",
             "notes": "Organic components mapped from FooDB compounds to BiGG via InChIKey/name (see mapping_confidence). Mineral base added for growth capability. Bounds are presence-based; foodb_content/foodb_unit retained."},
           "components": components,
           "unmapped": [],
           "n_components": len(components),
           "n_mapped": sum(1 for c in components if c["bigg_metabolite"]),
           "n_in_biggr": sum(1 for c in components if c["in_biggr"]),
           "n_food_components": len(organic),
           "food_group": fo["group"], "version": "1.0"}
    json.dump(rec, open(os.path.join(OUT, rec["id"]+".json"), "w"))
    written += 1
    index_rows.append({"id":rec["id"],"name":rec["name"],"category":"food","organism_scope":rec["organism_scope"],
        "aerobic":True,"n_components":rec["n_components"],"n_mapped":rec["n_mapped"],"n_in_biggr":rec["n_in_biggr"],
        "namespace":"bigg","source_type":"database","citation":rec["provenance"]["citation"][:120],"doi":"","food_group":fo["group"]})

json.dump(index_rows, open(os.path.join(CSVD,"..","food_index_rows.json"),"w"))
print(f"food media written: {written} (foods with >= {MIN_EXCH} mapped organic components)")
from collections import Counter
grp = Counter(r["food_group"] for r in index_rows)
print("by food group (top 12):")
for g,c in grp.most_common(12): print(f"  {c:4d}  {g}")
import statistics
nfc=[r["n_components"] for r in index_rows]
print(f"components/medium: min {min(nfc)} median {int(statistics.median(nfc))} max {max(nfc)}")
