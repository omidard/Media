#!/usr/bin/env python3
"""USDA FoodData Central -> food media. Curated USDA-nutrient-name -> BiGG exchange table
(amino acids, sugars, named fatty acids, vitamins, minerals). One medium per food + mineral base."""
import zipfile, json, os, glob, re
REPO="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT=os.path.join(REPO,"data","media")
USDA="/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/usda"
DICT=json.load(open(os.path.join(REPO,"tools","bigg_metabolite_dict.json")))
def valid(b): return b in DICT and DICT[b]["in_biggr"]
def nm(b): return DICT.get(b,{}).get("name",b)
def xr(b): return DICT.get(b,{}).get("xrefs",{})

# curated USDA nutrient name -> BiGG metabolite id
NMAP_RAW={
 # amino acids
 "Tryptophan":"trp__L","Threonine":"thr__L","Isoleucine":"ile__L","Leucine":"leu__L","Lysine":"lys__L",
 "Methionine":"met__L","Cystine":"cys__L","Cysteine":"cys__L","Phenylalanine":"phe__L","Tyrosine":"tyr__L",
 "Valine":"val__L","Arginine":"arg__L","Histidine":"his__L","Alanine":"ala__L","Aspartic acid":"asp__L",
 "Glutamic acid":"glu__L","Glycine":"gly","Proline":"pro__L","Serine":"ser__L","Asparagine":"asn__L","Glutamine":"gln__L",
 # sugars
 "Glucose":"glc__D","Fructose":"fru","Sucrose":"sucr","Galactose":"gal","Maltose":"malt","Lactose":"lcts",
 # fatty acids (named by chain)
 "SFA 16:0":"hdca","SFA 18:0":"ocdca","SFA 14:0":"ttdca","SFA 12:0":"ddca","SFA 10:0":"dca","SFA 8:0":"octa","SFA 6:0":"hxa",
 "MUFA 18:1 c":"ocdcea","MUFA 18:1":"ocdcea","PUFA 18:2 n-6 c,c":"lnlc","PUFA 18:2 c":"lnlc",
 "PUFA 18:3 n-3 c,c,c (ALA)":"lnlnca","PUFA 18:3 c":"lnlnca","PUFA 20:4":"arachd","PUFA 20:4c":"arachd",
 # vitamins
 "Thiamin":"thm","Riboflavin":"ribflv","Niacin":"nac","Pantothenic acid":"pnto__R","Vitamin B-6":"pydxn",
 "Folate, total":"fol","Vitamin B-12":"cbl1","Vitamin C, total ascorbic acid":"ascb__L","Biotin":"btn",
 "Vitamin E (alpha-tocopherol)":"avite1","Choline, total":"chol","Retinol":"retinol",
}
NMAP={k:v for k,v in NMAP_RAW.items() if valid(v)}
# minerals -> ion exchange (bound -1000)
MINMAP={"Potassium, K":"k","Zinc, Zn":"zn2","Magnesium, Mg":"mg2","Phosphorus, P":"pi","Calcium, Ca":"ca2",
 "Copper, Cu":"cu2","Iron, Fe":"fe2","Manganese, Mn":"mn2","Sodium, Na":"na1","Molybdenum, Mo":"mobd","Selenium, Se":"slnt"}
MINMAP={k:v for k,v in MINMAP.items() if valid(v)}
print("USDA nutrient map (organic):",len(NMAP),"| mineral map:",len(MINMAP),"| dropped(not in reactome):",
      [v for k,v in NMAP_RAW.items() if not valid(v)])
MINBASE={f"EX_{i}_e":-1000 for i in ["pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","h2o","h","co2"]}

def slug(s): return re.sub(r"[^a-z0-9]+","_",s.lower()).strip("_")[:48]
def process(foods, dataset):
    written=0; rows=[]
    for f in foods:
        desc=f.get("description","food"); fdcid=f.get("fdcId")
        comps={}
        for x in f.get("foodNutrients",[]):
            amt=x.get("amount");
            if not amt or amt<=0: continue
            name=x["nutrient"]["name"]; unit=x["nutrient"].get("unitName","")
            if name in NMAP:
                b=NMAP[name]; ex=f"EX_{b}_e"
                comps[ex]={"name":nm(b),"bigg_metabolite":b,"exchange":ex,"lower_bound":-1.0,"upper_bound":1000.0,
                    "concentration_mM":None,"usda_amount":amt,"usda_unit":unit,"xref":xr(b),"in_biggr":True,
                    "mapping_method":"usda_nutrient","mapping_confidence":"exact"}
            elif name in MINMAP:
                b=MINMAP[name]; ex=f"EX_{b}_e"
                comps[ex]={"name":nm(b),"bigg_metabolite":b,"exchange":ex,"lower_bound":-1000.0,"upper_bound":1000.0,
                    "concentration_mM":None,"usda_amount":amt,"usda_unit":unit,"xref":xr(b),"in_biggr":True,
                    "mapping_method":"usda_mineral","mapping_confidence":"exact"}
        norg=sum(1 for c in comps.values() if c["mapping_method"]=="usda_nutrient")
        if norg<5: continue
        for ex,lb in MINBASE.items():
            b=ex[3:-2]
            comps.setdefault(ex,{"name":nm(b),"bigg_metabolite":b,"exchange":ex,"lower_bound":lb,"upper_bound":1000.0,
                "concentration_mM":None,"xref":xr(b),"in_biggr":valid(b),"mapping_method":"mineral_base","mapping_confidence":"convention"})
        comps["EX_o2_e"]={"name":nm("o2"),"bigg_metabolite":"o2","exchange":"EX_o2_e","lower_bound":-10.0,"upper_bound":1000.0,
            "concentration_mM":None,"xref":xr("o2"),"in_biggr":valid("o2"),"mapping_method":"mineral_base","mapping_confidence":"convention"}
        components=sorted(comps.values(),key=lambda c:c["exchange"])
        rec={"id":f"usda_{fdcid}","name":f"{desc} (USDA food medium)","category":"food",
             "organism_scope":"food microbiome / general","aerobic":True,
             "description":f"Food-derived medium from USDA FoodData Central ({dataset}): measured amino acids, sugars, fatty acids, vitamins and minerals of {desc}, plus a mineral base.",
             "namespace":"bigg","provenance":{"source_type":"database",
                "citation":f"U.S. Department of Agriculture, FoodData Central ({dataset}), fdc.nal.usda.gov (FDC ID {fdcid}).","doi":"",
                "url":f"https://fdc.nal.usda.gov/food-details/{fdcid}/nutrients",
                "notes":"USDA measured nutrients mapped to BiGG via a curated nutrient->exchange table; amounts (per 100 g) in usda_amount/usda_unit. Presence-based uptake bounds; mineral base added."},
             "components":components,"unmapped":[],"n_components":len(components),
             "n_mapped":len(components),"n_in_biggr":sum(1 for c in components if c["in_biggr"]),
             "n_food_components":norg,"food_group":f.get("foodCategory",{}).get("description","") if isinstance(f.get("foodCategory"),dict) else (f.get("foodCategory","") or ""),"version":"1.0"}
        json.dump(rec,open(os.path.join(OUT,rec["id"]+".json"),"w")); written+=1
    print(f"  {dataset}: {written} media")
    return written

total=0
# Foundation Foods
z=zipfile.ZipFile(os.path.join(USDA,"ff.zip")); n=[x for x in z.namelist() if x.endswith('.json')][0]
d=json.load(z.open(n)); total+=process(d.get("FoundationFoods",d),"Foundation Foods 2024-04-18")
# SR Legacy (if present)
for srzip in glob.glob(os.path.join(USDA,"sr_legacy*.zip")):
    z=zipfile.ZipFile(srzip); n=[x for x in z.namelist() if x.endswith('.json')][0]
    d=json.load(z.open(n)); total+=process(d.get("SRLegacyFoods",d),"SR Legacy")
print("USDA media total:",total)
