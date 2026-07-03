#!/usr/bin/env python3
"""Map FooDB compounds -> BiGG metabolites (via InChIKey, then name).
Robust to FooDB's shifted Compound.csv columns: id/public_id/name are the first 3
fields; InChIKey is found by regex anywhere in the row."""
import csv, re, json, sys, os
sys.path.insert(0, "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
from map_metabolite import Mapper

CSV = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/foodb/foodb_2020_04_07_csv"
m = Mapper()
IK = re.compile(r"\b[A-Z]{14}-[A-Z]{10}-[A-Z]\b")

compound_map = {}   # foodb compound id -> {bigg, exchange, name, method, conf, in_biggr}
n=0; mapped=0; by_ik=0; by_name=0
csv.field_size_limit(10**7)
with open(os.path.join(CSV, "Compound.csv"), encoding="utf-8", errors="replace") as f:
    r = csv.reader(f); h = next(r)
    for row in r:
        if len(row) < 3: continue
        n += 1
        cid, name = row[0], row[2]
        raw = ",".join(row)
        ikm = IK.search(raw)
        ik = ikm.group(0) if ikm else None
        hit = m.map(name=name, inchikey=ik)
        if hit and hit["in_biggr"]:            # only keep metabolites our reactome has an exchange for
            compound_map[cid] = {"bigg": hit["bigg_metabolite"], "exchange": hit["exchange"],
                                 "name": hit["name"], "method": hit["mapping_method"],
                                 "conf": hit["mapping_confidence"]}
            mapped += 1
            if hit["mapping_method"] == "inchikey": by_ik += 1
            elif hit["mapping_method"] == "name": by_name += 1

json.dump(compound_map, open(os.path.join(CSV, "..", "compound_to_bigg.json"), "w"))
print(f"FooDB compounds: {n}")
print(f"mapped to BiGGr exchanges: {mapped} (unique BiGG mets: {len(set(v['bigg'] for v in compound_map.values()))})")
print(f"  by InChIKey (exact): {by_ik} | by name (inferred): {by_name}")
# show a sample of what maps
import itertools
print("sample maps:")
for cid, v in itertools.islice(compound_map.items(), 12):
    print(f"  FooDB {cid}: {v['name']:22s} -> {v['exchange']:16s} ({v['method']})")
