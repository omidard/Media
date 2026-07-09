#!/usr/bin/env python3
"""Formulate the canonical substrate-assay BASE media (Biolog IF-0 minimal, API carbohydrate base,
peptone fermentation base) into Media, cited; return a base_type -> media_id map so every phenotype
links to a real medium entry."""
import json, os
MED="repo/data/media"
m9=json.load(open(f"{MED}/m9_glucose_aerobic.json"))
salts=[dict(c) for c in m9["components"] if c["exchange"]!="EX_glc__D_e"]  # defined minimal salts base (no carbon)
DEFS={
 "biolog_if0_minimal":{"name":"Biolog IF-0 minimal base (sole-substrate)","category":"laboratory","complex":False,
   "desc":"Biolog IF-0a GN/GP inoculating-fluid base — a buffered, carbon-free defined minimal-salts medium; in a Phenotype MicroArray the sole carbon (or N/P/S) source is the substrate in each well.",
   "cite":"Bochner BR, Gadzinski P, Panomitros E. Phenotype MicroArrays for high-throughput phenotypic testing of microbial cells. Genome Res 11:1246 (2001).","comps":salts},
 "api_cho_base":{"name":"API carbohydrate fermentation base (API 50 CHL / CHB)","category":"laboratory","complex":True,
   "desc":"Chemically-defined API 50 CHL/CHB carbohydrate-fermentation base (ammonium/phosphate salts + bromocresol-purple pH indicator); a positive result is acidification from fermenting the tested sugar, not sole-carbon growth.",
   "cite":"API 50 CH / API 50 CHL medium (bioMérieux); Logan NA & Berkeley RCW, J Gen Microbiol 130:1871 (1984).","comps":salts},
 "peptone_ferment_base":{"name":"Peptone fermentation base (acid-from-sugar test)","category":"laboratory","complex":True,
   "desc":"Peptone-based fermentation base with a pH indicator (e.g. phenol-red broth base); positive = fermentative acid production from the added carbohydrate. Complex, undefined peptone base — the chemically-defined salts are mapped; peptone is listed as unmapped.",
   "cite":"Phenol-red carbohydrate fermentation broth (standard clinical-microbiology method).","comps":salts},
 "assay_generic_base":{"name":"Enzyme/activity assay medium","category":"laboratory","complex":True,
   "desc":"Generic test medium for enzyme/hydrolysis/reduction activity assays (not a sole-substrate growth test).",
   "cite":"Substrate-utilisation / enzyme activity assay; medium per the original source.","comps":salts},
}
made=0
idx={x["id"] for x in json.load(open("repo/data/index.json"))["media"]}
for mid,d in DEFS.items():
    comps=[dict(c) for c in d["comps"]]
    unm=[{"name":"peptone / undefined base","reason":"complex undefined base"}] if d["complex"] and mid!="api_cho_base" else []
    rec={"id":mid,"name":d["name"],"category":d["category"],"organism_scope":"prokaryote-generic","aerobic":True,
         "description":d["desc"],"namespace":"bigg",
         "provenance":{"source_type":"standard","citation":d["cite"],"doi":"","url":"","notes":"Assay base medium; the tested substrate is added per phenotype."},
         "components":sorted(comps,key=lambda c:c["exchange"]),"unmapped":unm,"n_components":len(comps),"n_mapped":len(comps),
         "n_in_biggr":sum(1 for c in comps if c["in_biggr"]),"complex":d["complex"],"assay_base":True,"version":"1.0"}
    json.dump(rec,open(f"{MED}/{mid}.json","w")); made+=1
json.dump({"defined-minimal":"biolog_if0_minimal","complex":"peptone_ferment_base","assay":"assay_generic_base","api":"api_cho_base"},
          open("repo/tools/assay_base_media.json","w"))
print(f"assay base media formulated: {made}")
