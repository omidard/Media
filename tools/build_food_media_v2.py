#!/usr/bin/env python3
"""FooDB food media, v2 — completeness fix.

The v1 builder silently dropped every measured FooDB compound that did not map to
BiGG (`if not mp: continue`) and hard-coded `unmapped:[]`. This version:
  * loads Compound.csv (name + InChIKey) so unmapped compounds can be named/kept;
  * for each MEASURED compound (standard_content > 0):
      - if it maps (cmap or Mapper via InChIKey/name) -> a component;
      - otherwise it is recorded in `uncovered[]` with its name + InChIKey + content;
  * writes a coverage-ready record (enrich_coverage.py fills the coverage block).

Rebuild:  python3 build_food_media_v2.py
"""
import csv, json, os, re, sys
sys.path.insert(0, "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
from map_metabolite import Mapper

CSVD = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/foodb/foodb_2020_04_07_csv"
REPO = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT = os.path.join(REPO, "data", "media")
csv.field_size_limit(10**7)
DICT = json.load(open(os.path.join(REPO, "tools", "bigg_metabolite_dict.json")))
cmap = json.load(open(os.path.join(CSVD, "..", "compound_to_bigg.json")))
MAP = Mapper()
MIN_EXCH = 6
MAX_UNCOVERED = 250   # cap per food for file size; note truncation

BAD = re.compile(r"(coa$|_coa|trna|\[protein|acp\b|acyl-carrier|thioredoxin|ferredoxin|flavodoxin)", re.I)
# obvious non-nutrient / macromolecule names we won't count as uncovered nutrients
SKIP_UNC = re.compile(r"protein|peptide|dna|rna|chlorophyll|carotene\b|polymer|fiber|starch granule|lignin|cellulose|pectin", re.I)

MINERALS = {"EX_pi_e":-1000,"EX_so4_e":-1000,"EX_nh4_e":-1000,"EX_k_e":-1000,"EX_na1_e":-1000,
  "EX_cl_e":-1000,"EX_mg2_e":-1000,"EX_ca2_e":-1000,"EX_fe2_e":-1000,"EX_fe3_e":-1000,
  "EX_mn2_e":-1000,"EX_zn2_e":-1000,"EX_cu2_e":-1000,"EX_cobalt2_e":-1000,"EX_ni2_e":-1000,
  "EX_mobd_e":-1000,"EX_h2o_e":-1000,"EX_h_e":-1000,"EX_co2_e":-1000,"EX_o2_e":-10}

import glob as _g
for _f in _g.glob(os.path.join(OUT, "food_*.json")):
    os.remove(_f)

foods = {}
with open(os.path.join(CSVD, "Food.csv"), encoding="utf-8", errors="replace") as f:
    for row in csv.DictReader(f):
        foods[row["id"]] = {"name": row["name"], "group": row.get("food_group",""),
                            "subgroup": row.get("food_subgroup",""), "public_id": row.get("public_id",""),
                            "sci": row.get("name_scientific","")}

# compound id -> (name, inchi).  NOTE: in this FooDB dump the `moldb_inchikey`
# column actually contains the full InChI string (columns are shifted), so we
# keep it as an InChI external id, not an InChIKey.
compinfo = {}
with open(os.path.join(CSVD, "Compound.csv"), encoding="utf-8", errors="replace") as f:
    for row in csv.DictReader(f):
        inchi = row.get("moldb_inchikey", "") or ""
        if not inchi.startswith("InChI="):
            inchi = ""
        compinfo[row["id"]] = (row.get("name", "") or "", inchi)

def recover(cid):
    """Return ('map', component-fields) or ('unc', name, inchi) or None(skip)."""
    name, inchi = compinfo.get(cid, ("", ""))
    mp = cmap.get(cid)
    if mp and not (BAD.search(mp["name"]) or BAD.search(mp["bigg"])):
        return ("map", mp["bigg"], mp["exchange"], mp.get("name") or name, "foodb_inchikey_name", "exact")
    # try Mapper via name -> BiGG (InChI is not indexed; the cmap already used InChIKey)
    hit = MAP.map(name=name or None)
    if hit and not (BAD.search(hit["name"]) or BAD.search(hit["bigg_metabolite"])):
        return ("map", hit["bigg_metabolite"], hit["exchange"], hit["name"],
                hit["mapping_method"]+"_foodb", hit.get("mapping_confidence","inferred"))
    if not name or SKIP_UNC.search(name):
        return None
    return ("unc", name, inchi)

food_comp = {}   # fid -> {exchange:{content,unit,cite,bid,name,method,conf}}
food_unc = {}    # fid -> {inchikey_or_name: {name,inchikey,content,unit}}
food_cites = {}
with open(os.path.join(CSVD, "Content.csv"), encoding="utf-8", errors="replace") as f:
    for row in csv.DictReader(f):
        if row.get("source_type") != "Compound": continue
        try: cval = float(row.get("standard_content") or "")
        except: continue
        if cval <= 0: continue
        fid = row.get("food_id")
        if fid not in foods: continue
        rec = recover(row.get("source_id"))
        if rec is None: continue
        if rec[0] == "map":
            _, bid, ex, nm, method, conf = rec
            d = food_comp.setdefault(fid, {})
            cur = d.get(ex)
            if cur is None or cval > (cur.get("content") or 0):
                d[ex] = {"content": cval, "unit": row.get("orig_unit",""), "cite": row.get("citation",""),
                         "bid": bid, "name": nm, "method": method, "conf": conf}
        else:
            _, nm, inchi = rec
            key = inchi or nm.lower()
            u = food_unc.setdefault(fid, {})
            if key not in u:
                u[key] = {"name": nm, "inchi": inchi, "content": cval, "unit": row.get("orig_unit","")}
        cc = row.get("citation")
        if cc: food_cites.setdefault(fid, set()).add(cc)

def slug(s): return re.sub(r"[^a-z0-9]+","_", s.lower()).strip("_")[:48]

written = 0; tot_unc = 0
for fid, comps in food_comp.items():
    organic = [ex for ex in comps if ex not in MINERALS]
    if len(organic) < MIN_EXCH: continue
    fo = foods[fid]
    components = []
    for ex in sorted(set(list(comps.keys()) + list(MINERALS.keys()))):
        met = re.match(r"EX_(.+)_e$", ex); bid = met.group(1) if met else ex
        d = DICT.get(bid, {}); is_food = ex in comps and ex not in MINERALS
        fc = comps.get(ex, {})
        comp = {"name": fc.get("name") or d.get("name", bid), "bigg_metabolite": bid, "exchange": ex,
                "lower_bound": (-1.0 if is_food else MINERALS.get(ex, -1000)), "upper_bound": 1000.0,
                "concentration_mM": None, "xref": d.get("xrefs", {}), "in_biggr": d.get("in_biggr", False),
                "exchange_source": ("biggr" if d.get("in_biggr") else "bigg"),
                "mapping_method": (fc.get("method") if is_food else "mineral_base"),
                "mapping_confidence": (fc.get("conf") if is_food else "convention")}
        if is_food:
            comp["foodb_content"] = fc.get("content"); comp["foodb_unit"] = fc.get("unit")
        components.append(comp)
    # uncovered measured compounds (deduped), capped
    ulist = list(food_unc.get(fid, {}).values())
    ulist.sort(key=lambda u: -(u.get("content") or 0))
    truncated = len(ulist) > MAX_UNCOVERED
    uncovered = []
    for u in ulist[:MAX_UNCOVERED]:
        e = {"name": u["name"], "reason": "not_in_bigg", "curation": "needs_manual_curation",
             "xref": ({"inchi": u["inchi"]} if u["inchi"] else {}),
             "foodb_content": u["content"], "foodb_unit": u["unit"],
             "proposed_lower_bound": -1.0,
             "note": "measured FooDB compound with no BiGG/BiGGr exchange; kept for manual curation"}
        uncovered.append(e)
    tot_unc += len(uncovered)
    cites = sorted(food_cites.get(fid, []))[:8]
    rid = "food_" + (fo["public_id"] or slug(fo["name"]))
    rec = {"id": rid, "name": fo["name"] + " (food medium)", "category": "food",
           "organism_scope": "food microbiome / general", "aerobic": True,
           "description": f"Food-derived medium: metabolizable components of {fo['name']}"
                          + (f" ({fo['sci']})" if fo['sci'] else "") + f" [{fo['group']}] from FooDB, "
                          + "plus a standard M9 mineral base. Organic components use presence-based uptake bounds; FooDB content retained. "
                          + "Measured compounds with no BiGG exchange are listed under uncovered"
                          + (" (capped at %d)" % MAX_UNCOVERED if truncated else "") + ".",
           "namespace": "bigg",
           "provenance": {"source_type": "database",
             "citation": f"FooDB v2020-04-07 (Wishart DS et al., foodb.ca). Content sources: {', '.join(cites) if cites else 'FooDB'}.",
             "doi": "", "url": f"https://foodb.ca/foods/{fo['public_id']}",
             "notes": "Organic components mapped from FooDB compounds to BiGG via InChIKey/name. Mineral base added. Bounds presence-based; foodb_content retained. Unmapped measured compounds kept in uncovered (v2 completeness fix)."},
           "components": components, "uncovered": uncovered,
           "n_components": len(components),
           "n_mapped": sum(1 for c in components if c["bigg_metabolite"]),
           "n_in_biggr": sum(1 for c in components if c["in_biggr"]),
           "n_food_components": len(organic), "food_group": fo["group"], "version": "2.0"}
    json.dump(rec, open(os.path.join(OUT, rid+".json"), "w"), ensure_ascii=False)
    written += 1

print(f"food media written: {written}")
print(f"total uncovered compounds recorded: {tot_unc} (avg {tot_unc/max(1,written):.1f}/food)")
