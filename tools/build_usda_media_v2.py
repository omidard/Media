#!/usr/bin/env python3
"""USDA FoodData Central -> food media, v2 (completeness).

v1 hard-coded unmapped:[]. v2 records unmapped MEASURED nutrients that are real
metabolites in uncovered[] (skipping non-metabolite aggregates: energy, water,
protein, total fat, ash, carbohydrate-by-difference, fibre, total-sugars, total
fatty-acid classes). Mapped nutrients still become components (curated table).
Reruns overwrite usda_*.json; run the curation pipeline afterwards.
"""
import zipfile, json, os, glob, re
REPO = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT = os.path.join(REPO, "data", "media")
USDA = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/usda"
DICT = json.load(open(os.path.join(REPO, "tools", "bigg_metabolite_dict.json")))
def valid(b): return b in DICT and DICT[b]["in_biggr"]
def nm(b): return DICT.get(b, {}).get("name", b)
def xr(b): return DICT.get(b, {}).get("xrefs", {})

NMAP_RAW = {
 "Tryptophan":"trp__L","Threonine":"thr__L","Isoleucine":"ile__L","Leucine":"leu__L","Lysine":"lys__L",
 "Methionine":"met__L","Cystine":"cys__L","Cysteine":"cys__L","Phenylalanine":"phe__L","Tyrosine":"tyr__L",
 "Valine":"val__L","Arginine":"arg__L","Histidine":"his__L","Alanine":"ala__L","Aspartic acid":"asp__L",
 "Glutamic acid":"glu__L","Glycine":"gly","Proline":"pro__L","Serine":"ser__L","Asparagine":"asn__L","Glutamine":"gln__L",
 "Glucose":"glc__D","Fructose":"fru","Sucrose":"sucr","Galactose":"gal","Maltose":"malt","Lactose":"lcts",
 "SFA 16:0":"hdca","SFA 18:0":"ocdca","SFA 14:0":"ttdca","SFA 12:0":"ddca","SFA 10:0":"dca","SFA 8:0":"octa","SFA 6:0":"hxa",
 "MUFA 18:1 c":"ocdcea","MUFA 18:1":"ocdcea","PUFA 18:2 n-6 c,c":"lnlc","PUFA 18:2 c":"lnlc",
 "PUFA 18:3 n-3 c,c,c (ALA)":"lnlnca","PUFA 18:3 c":"lnlnca","PUFA 20:4":"arachd","PUFA 20:4c":"arachd",
 "Thiamin":"thm","Riboflavin":"ribflv","Niacin":"nac","Pantothenic acid":"pnto__R","Vitamin B-6":"pydxn",
 "Folate, total":"fol","Vitamin B-12":"cbl1","Vitamin C, total ascorbic acid":"ascb__L","Biotin":"btn",
 "Vitamin E (alpha-tocopherol)":"avite1","Choline, total":"chol","Retinol":"retinol",
}
NMAP = {k: v for k, v in NMAP_RAW.items() if valid(v)}
MINMAP = {"Potassium, K":"k","Zinc, Zn":"zn2","Magnesium, Mg":"mg2","Phosphorus, P":"pi","Calcium, Ca":"ca2",
 "Copper, Cu":"cu2","Iron, Fe":"fe2","Manganese, Mn":"mn2","Sodium, Na":"na1","Molybdenum, Mo":"mobd","Selenium, Se":"slnt"}
MINMAP = {k: v for k, v in MINMAP.items() if valid(v)}
MINBASE = {f"EX_{i}_e": -1000 for i in ["pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","h2o","h","co2"]}

# non-metabolite aggregate nutrient names -> NOT recorded as uncovered compounds
AGG = re.compile(
    r"^energy|^water$|^protein$|nitrogen|^ash$|total lipid|carbohydrate|fiber|fibre|"
    r"^sugars|fatty acids, total|by difference|,\s*added$|^total\b|adjusted|"
    r"specific gravity|refuse|^solids", re.I)

def process(foods, dataset):
    written = 0; tot_unc = 0
    for f in foods:
        desc = f.get("description", "food"); fdcid = f.get("fdcId")
        comps = {}; uncovered = []
        for x in f.get("foodNutrients", []):
            amt = x.get("amount")
            if not amt or amt <= 0: continue
            name = x["nutrient"]["name"]; unit = x["nutrient"].get("unitName", "")
            if name in NMAP:
                b = NMAP[name]; ex = f"EX_{b}_e"
                comps[ex] = {"name":nm(b),"bigg_metabolite":b,"exchange":ex,"lower_bound":-1.0,"upper_bound":1000.0,
                    "concentration_mM":None,"usda_amount":amt,"usda_unit":unit,"xref":xr(b),"in_biggr":True,
                    "mapping_method":"usda_nutrient","mapping_confidence":"exact"}
            elif name in MINMAP:
                b = MINMAP[name]; ex = f"EX_{b}_e"
                comps[ex] = {"name":nm(b),"bigg_metabolite":b,"exchange":ex,"lower_bound":-1000.0,"upper_bound":1000.0,
                    "concentration_mM":None,"usda_amount":amt,"usda_unit":unit,"xref":xr(b),"in_biggr":True,
                    "mapping_method":"usda_mineral","mapping_confidence":"exact"}
            elif not AGG.search(name):
                uncovered.append({"name":name,"reason":"not_in_bigg","curation":"needs_manual_curation",
                    "xref":{},"usda_amount":amt,"usda_unit":unit,"proposed_lower_bound":-1.0,
                    "note":"measured USDA nutrient with no curated BiGG exchange; kept for manual curation"})
        norg = sum(1 for c in comps.values() if c["mapping_method"] == "usda_nutrient")
        if norg < 5: continue
        # dedupe uncovered by name
        seen = set(); uncovered = [u for u in uncovered if not (u["name"] in seen or seen.add(u["name"]))]
        for ex, lb in MINBASE.items():
            b = ex[3:-2]
            comps.setdefault(ex, {"name":nm(b),"bigg_metabolite":b,"exchange":ex,"lower_bound":lb,"upper_bound":1000.0,
                "concentration_mM":None,"xref":xr(b),"in_biggr":valid(b),"mapping_method":"mineral_base","mapping_confidence":"convention"})
        comps["EX_o2_e"] = {"name":nm("o2"),"bigg_metabolite":"o2","exchange":"EX_o2_e","lower_bound":-10.0,"upper_bound":1000.0,
            "concentration_mM":None,"xref":xr("o2"),"in_biggr":valid("o2"),"mapping_method":"mineral_base","mapping_confidence":"convention"}
        components = sorted(comps.values(), key=lambda c: c["exchange"])
        tot_unc += len(uncovered)
        fg = f.get("foodCategory", {}).get("description", "") if isinstance(f.get("foodCategory"), dict) else (f.get("foodCategory", "") or "")
        rec = {"id":f"usda_{fdcid}","name":f"{desc} (USDA food medium)","category":"food",
             "organism_scope":"food microbiome / general","aerobic":True,
             "description":f"Food-derived medium from USDA FoodData Central ({dataset}): measured amino acids, sugars, fatty acids, vitamins and minerals of {desc}, plus a mineral base. Measured nutrients with no curated BiGG exchange are listed under uncovered; non-metabolite aggregates (energy, protein, total fat/fibre) are excluded by design.",
             "namespace":"bigg","provenance":{"source_type":"database",
                "citation":f"U.S. Department of Agriculture, FoodData Central ({dataset}), fdc.nal.usda.gov (FDC ID {fdcid}).","doi":"",
                "url":f"https://fdc.nal.usda.gov/food-details/{fdcid}/nutrients",
                "notes":"USDA measured nutrients mapped to BiGG via a curated nutrient->exchange table; amounts (per 100 g) in usda_amount/usda_unit. Unmapped measured metabolites kept in uncovered (v2). Aggregates excluded."},
             "components":components,"uncovered":uncovered,"n_components":len(components),
             "n_mapped":len(components),"n_in_biggr":sum(1 for c in components if c["in_biggr"]),
             "n_food_components":norg,"food_group":fg,"version":"2.0"}
        json.dump(rec, open(os.path.join(OUT, rec["id"]+".json"), "w"), ensure_ascii=False); written += 1
    print(f"  {dataset}: {written} media, {tot_unc} uncovered recorded")
    return written

# clear stale usda media
for _f in glob.glob(os.path.join(OUT, "usda_*.json")):
    os.remove(_f)
total = 0
z = zipfile.ZipFile(os.path.join(USDA, "ff.zip")); n = [x for x in z.namelist() if x.endswith('.json')][0]
d = json.load(z.open(n)); total += process(d.get("FoundationFoods", d), "Foundation Foods 2024-04-18")
for srzip in glob.glob(os.path.join(USDA, "sr_legacy*.zip")):
    z = zipfile.ZipFile(srzip); n = [x for x in z.namelist() if x.endswith('.json')][0]
    d = json.load(z.open(n)); total += process(d.get("SRLegacyFoods", d), "SR Legacy")
print("USDA media total:", total)
