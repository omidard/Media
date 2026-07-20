#!/usr/bin/env python3
"""Add every GrowthDB medium I formulated (medium.exchanges, no Media DB id yet) to the Media
DB as a first-class per-media file, and link the GrowthDB record to the new media_id.

Distinct media (same name + same exchange set) share one Media DB entry. Exchanges already
mapped to BiGG upstream; here we attach names/xrefs from the BiGG dict and write the file.
"""
import json, os, re, glob, hashlib, collections

MEDIA_REPO = "/data/media_curate"
GR = "/data/GrowthDB_work/data/growth_records.json"
DICT = json.load(open(os.path.join(MEDIA_REPO, "tools", "bigg_metabolite_dict.json")))
MINSET = {"pi", "so4", "cl", "na1", "k", "nh4", "mg2", "ca2", "fe2", "fe3", "mn2", "zn2", "cu2",
          "cobalt2", "mobd", "ni2", "h2o", "h", "hco3", "slnt", "tungs", "so3", "tsul", "oh1"}

def bname(b):
    return DICT.get(b, {}).get("name", b)

def bxref(b):
    return DICT.get(b, {}).get("xrefs", {})

def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:60] or "medium"

def sig(exch):
    return "|".join(sorted(e["exchange"] for e in exch))

def component(e):
    b = e["bigg"]
    return {"name": bname(b), "bigg_metabolite": b, "exchange": e["exchange"],
            "lower_bound": float(e.get("lb", -1000.0)), "upper_bound": float(e.get("ub", 1000.0)),
            "concentration_mM": None, "xref": bxref(b), "in_biggr": (b in DICT and DICT[b].get("in_biggr", True)),
            "exchange_source": "growthdb_formulation", "mapping_method": "growthdb_curation",
            "mapping_confidence": "curated"}

def main():
    gr = json.load(open(GR))
    # collect distinct formulated media: (name-slug, exchange-signature) -> {name, exch, pmc, records, fmt}
    groups = {}
    for r in gr:
        m = r.get("medium") or {}
        if m.get("media_id") or not m.get("exchanges"):
            continue
        name = (m.get("canonical_name") or m.get("description") or "medium").strip()
        exch = m["exchanges"]
        key = (slug(name), sig(exch))
        g = groups.setdefault(key, {"name": name, "exch": exch, "records": [], "fmt": m.get("formulation"),
                                    "src": m.get("formulated_from"), "pmc": None})
        g["records"].append(r)
        pm = re.search(r"(PMC\d+)", r.get("id", ""))
        if pm and not g["pmc"]:
            g["pmc"] = pm.group(1)
    made = 0
    for (sl, s), g in groups.items():
        pmc = g["pmc"]
        mid = ("growthlit_%s_%s" % (pmc, sl))[:90] if pmc else ("gdbfml_%s_%s" % (sl, hashlib.md5(s.encode()).hexdigest()[:6]))
        comps = [component(e) for e in g["exch"]]
        n_map = sum(1 for c in comps if c["in_biggr"])
        prov_url = ("https://www.ncbi.nlm.nih.gov/pmc/articles/%s/" % pmc) if pmc else ""
        doc = {
            "id": mid, "name": g["name"][:120], "category": "growth_medium", "organism_scope": "prokaryote",
            "aerobic": None, "namespace": "bigg",
            "description": "%s — formulated for GrowthDB (%s) and mapped to BiGG exchanges." % (g["name"][:80], g.get("src") or "curated"),
            "provenance": {"source_type": "literature", "citation": ("Medium from %s (GrowthDB)." % pmc) if pmc else "GrowthDB curated recipe.",
                           "doi": "", "url": prov_url,
                           "notes": "Formulation status: %s. Bounds presence-based (minerals unlimited, organic C -10). Added via GrowthDB curation." % (g.get("fmt") or "defined")},
            "components": comps, "n_components": len(comps), "n_mapped": n_map, "n_in_biggr": n_map,
            "version": 1,
            "coverage": {"n_compounds": len(comps), "n_covered": n_map, "n_uncovered": len(comps) - n_map,
                         "pct_covered": round(100.0 * n_map / max(1, len(comps)), 1), "by_source": {"biggr": n_map}},
            "uncovered": [], "oxygen": None, "curation": g.get("fmt"),
        }
        with open(os.path.join(MEDIA_REPO, "data", "media", mid + ".json"), "w") as fh:
            json.dump(doc, fh, indent=1)
        url = "https://omidard.github.io/Media/?medium=" + mid
        for r in g["records"]:
            m = r["medium"]
            m["media_id"] = mid
            m["media_url"] = url
            m.pop("exchanges", None)          # now lives in the Media DB entry
        made += 1
    json.dump(gr, open(GR, "w"), separators=(",", ":"))
    print("Media DB: created %d new media from GrowthDB formulations; linked their records to media_id" % made)

if __name__ == "__main__":
    main()
