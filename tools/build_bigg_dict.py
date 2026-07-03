#!/usr/bin/env python3
"""Build the metabolite mapping backbone for the Media repo.
Parses BiGG's namespace file into a universal-metabolite dictionary with xrefs,
flags which are present in the local BiGGr universal reactome, and builds reverse
indexes (by normalized name and by each xref) for mapping external sources -> EX_<id>_e."""
import json, re, os
from collections import defaultdict

WORK = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work"

# ---- BiGGr universal (our reactome) metabolite ids ----
bg = json.load(open("/data/biggr/raw/universal_metabolites.json"))
biggr_ids = set()
biggr_name = {}
for row in bg["data"]:
    bid = row.get("universalcomponent__bigg_id")
    if bid:
        biggr_ids.add(bid)
        biggr_name[bid] = row.get("universalcomponent__name", "")
print("BiGGr universal metabolites:", len(biggr_ids))

# ---- parse BiGG namespace ----
DBMAP = {
    "MetaNetX (MNX) Chemical": "mnx", "CHEBI": "chebi", "KEGG Compound": "kegg",
    "KEGG Drug": "kegg_drug", "KEGG Glycan": "kegg_glycan",
    "Human Metabolome Database": "hmdb", "InChI Key": "inchikey",
    "SEED Compound": "seed", "MetaCyc": "metacyc", "BioCyc": "biocyc",
    "Reactome Compound": "reactome", "LipidMaps": "lipidmaps",
}
def parse_links(s):
    xr = {}
    if not s: return xr
    for part in s.split(";"):
        part = part.strip()
        if ":" not in part: continue
        # split on first ": " that separates dbname from url
        m = re.match(r"(.+?):\s*(https?://\S+)", part)
        if not m: continue
        dbname, url = m.group(1).strip(), m.group(2).strip()
        key = DBMAP.get(dbname)
        if not key: continue
        val = url.rstrip("/").split("/")[-1]
        xr.setdefault(key, val)
    return xr

univ = {}  # univ_id -> {name, synonyms:set, xrefs:{}}
with open(os.path.join(WORK, "bigg_models_metabolites.txt")) as f:
    header = f.readline()
    for line in f:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 6: continue
        bigg_id, uid, name, model_list, dblinks, old = cols[0], cols[1], cols[2], cols[3], cols[4], cols[5]
        if not uid: continue
        rec = univ.setdefault(uid, {"name": name, "synonyms": set(), "xrefs": {}})
        if name: rec["synonyms"].add(name)
        for o in old.split(";"):
            o = o.strip().strip("_")
            o = re.sub(r"[\[_]?[cepmxrnghlfuvwси]\]?$", "", o)  # strip compartment suffix noise
        for x, v in parse_links(dblinks).items():
            rec["xrefs"].setdefault(x, v)

# finalize + mark biggr membership
out = {}
for uid, rec in univ.items():
    out[uid] = {
        "name": rec["name"],
        "synonyms": sorted(s for s in rec["synonyms"] if s),
        "xrefs": rec["xrefs"],
        "in_biggr": uid in biggr_ids,
    }
# add biggr-only metabolites not in BiGG namespace (rare) so we know they exist
for bid in biggr_ids:
    if bid not in out:
        out[bid] = {"name": biggr_name.get(bid, ""), "synonyms": [], "xrefs": {}, "in_biggr": True}

print("BiGG universal metabolites:", len(out), "| in BiGGr:", sum(1 for v in out.values() if v["in_biggr"]))

# ---- reverse indexes ----
def norm(s):
    s = s.lower().strip()
    s = re.sub(r"^(l|d|dl)-", "", s)          # drop leading stereo for a looser key too
    s = re.sub(r"[^a-z0-9]", "", s)
    return s
def norm_xref(key, val):
    v = str(val).strip()
    if key == "inchikey": return v.upper()
    if key == "chebi": return re.sub(r"\D", "", v).lstrip("0") or "0"   # numeric, no CHEBI: prefix, no lead zeros
    if key == "hmdb": return re.sub(r"\D", "", v).lstrip("0") or "0"    # HMDB00122 / HMDB0000122 -> 122
    return v

name_idx = defaultdict(list); name_idx_strict = defaultdict(list)
xref_idx = {k: {} for k in ["inchikey", "chebi", "kegg", "hmdb", "mnx", "seed"]}
for uid, rec in out.items():
    for nm in [rec["name"]] + rec["synonyms"]:
        if not nm: continue
        name_idx[norm(nm)].append(uid)
        name_idx_strict[re.sub(r"[^a-z0-9]", "", nm.lower())].append(uid)
    for k, idx in xref_idx.items():
        v = rec["xrefs"].get(k)
        if v: idx.setdefault(norm_xref(k, v), uid)

json.dump(out, open(os.path.join(WORK, "bigg_metabolite_dict.json"), "w"))
json.dump({"name": {k: v for k, v in name_idx.items()},
           "name_strict": {k: v for k, v in name_idx_strict.items()},
           "xref": xref_idx},
          open(os.path.join(WORK, "bigg_reverse_index.json"), "w"))

# quick self-test
tests = ["D-Glucose", "L-Alanine", "Acetate", "Sucrose", "Riboflavin", "L-Tryptophan", "Cobalamin", "Oxygen O2"]
ri = json.load(open(os.path.join(WORK, "bigg_reverse_index.json")))
print("\n=== mapping self-test (by name) ===")
for t in tests:
    hits = ri["name"].get(norm(t)) or ri["name_strict"].get(re.sub(r"[^a-z0-9]", "", t.lower())) or []
    hits = [h for h in hits if out[h]["in_biggr"]] or hits
    print(f"  {t:16s} -> {hits[:3]}  ({'in BiGGr' if hits and out[hits[0]]['in_biggr'] else 'not/uncertain'})")
# xref coverage
for k, idx in ri["xref"].items():
    print(f"  xref {k}: {len(idx)} ids")
