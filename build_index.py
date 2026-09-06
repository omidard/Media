#!/usr/bin/env python3
"""
Build the catalog (data/index.json) and the small counts file (data/stats.json)
from the per-medium records in data/media/.

Run it from anywhere:  python3 build_index.py [--media DIR] [--out DIR]

Audit fixes carried by this file
--------------------------------
* cwd-dependence (PIPE-02): the paths were bare relative strings, so running the
  script from the wrong directory wrote `count: 0` and exited 0. Paths are now
  derived from __file__, and an empty media directory is a hard error.
* fabricated defaults (SCHEMA-07): a record with no coverage block used to become
  `pct_covered: 100.0, n_uncovered: 0` — a perfect score invented for a medium
  that was never measured. Absent is now null, and the number of records missing
  a coverage block is printed with its denominator.
* citation truncation (SCHEMA-07): `citation[:140]` cut 157 citations, 11 of them
  mid-PMID, and the cut text propagated into media.parquet and media.sqlite.gz.
  The catalog now carries the full citation; the browser trims for display.
* `defined` coercion (SCHEMA-03): `d.get("defined","")` turned 9,798 unknowns into
  a falsy empty string. The tri-state true|false|null now survives into the catalog.
* key collision (SCHEMA-05): the trust tier is emitted as `curation_tier`;
  `curation` is kept as a deprecated alias so existing consumers keep working, and
  the record's own composition descriptor is emitted separately as
  `formulation_class`.
* data/stats.json had no generator at all and shipped 442 media stale. It is now
  written in the same pass as index.json, so the two cannot disagree.
"""
import argparse
import glob
import json
import os
from collections import Counter

REPO = os.path.dirname(os.path.abspath(__file__))


def source_db(idv, prov, food_group):
    # NOTE (NM-03 / PROV-06): this keys on the id prefix, which is provably wrong for
    # 1,248 MediaDive records that are JCM/CCAP rather than DSMZ, and for the bovine
    # BMDB records filed as HMDB-derived. Source identity is being resolved from
    # record evidence in the 20-range provenance stage (tools/stages/source_identity.py);
    # this function stays until that stage lands so the catalog keeps building.
    if idv.startswith('mediadive_'): return 'DSMZ MediaDive'
    if idv.startswith('usda_'): return 'USDA FoodData Central'
    if idv.startswith('food_'): return 'FooDB'
    if idv.startswith('lit_'): return 'Literature (GEM papers)'
    if idv.startswith('growthlit_'): return 'Literature (GrowthDB)'
    if idv.startswith('biospecimen_hmdb_'): return 'HMDB'
    if idv.startswith('biospecimen_'): return 'Published (HMDB-derived)'
    return prov.get('source_type', '')


# curation tier — lower = more trustworthy; drives the default table order so the
# most rigorously curated media lead ("the frontier of the collection").
#   0 curated   : std_ canonical reference collection (the flagship named media)
#   1 expert    : expert-curated canonical formulation applied to another record
#   2 verified  : paper-verified against the source publication
#   3 database  : sourced from a curated database (DSMZ/USDA/FooDB/HMDB/BMDB/seed)
#   4 auto      : auto-extracted from literature, not manually verified
CURATION = {0: "curated", 1: "expert", 2: "verified", 3: "database", 4: "auto"}


def curation_tier(idv, ver):
    ver = ver or ""
    if idv.startswith("std_"): return 0
    if ver.startswith("expert-curated"): return 1
    if ver.startswith("paper-verified"): return 2
    if idv.startswith(("lit_", "complexlit_", "growthlit_")): return 4
    return 3


def build(media_dir, out_dir):
    files = sorted(glob.glob(os.path.join(media_dir, "*.json")))
    if not files:
        raise SystemExit(
            "FATAL: no media found in %s.\n"
            "  The catalog is never legitimately empty (13,515 records are expected).\n"
            "  Writing an empty index.json would silently destroy the catalog, which is\n"
            "  what this script used to do with exit code 0." % media_dir)

    rows = []
    missing_coverage = 0
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        cov = d.get("coverage")
        if not cov:
            missing_coverage += 1
            cov = {}
        tier = curation_tier(d["id"], (d.get("provenance") or {}).get("verification"))
        prov = d["provenance"]
        rows.append(
            {k: d.get(k) for k in ("id", "name", "category", "organism_scope", "aerobic",
                                   "oxygen", "n_components", "n_mapped", "n_in_biggr",
                                   "namespace")}
            | {"source_type": prov["source_type"],
               "source_db": source_db(d["id"], prov, d.get("food_group", "")),
               # tri-state: True | False | None (absent is null, never "")
               "defined": d.get("defined"),
               # full text; the browser trims for display (SCHEMA-07)
               "citation": prov["citation"],
               "food_group": d.get("food_group"),
               "tier": tier,
               "curation_tier": CURATION[tier],
               # deprecated alias of curation_tier, kept so existing consumers of
               # data/index.json keep working; use curation_tier.
               "curation": CURATION[tier],
               # the record's own composition descriptor (443 records), which used
               # to be overwritten by the trust tier under the same key (SCHEMA-05)
               "formulation_class": d.get("formulation_class"),
               "n_nonbigg_fallback": d.get("n_nonbigg_fallback"),
               # absent measurement is null, never a fabricated 100% (SCHEMA-07)
               "n_uncovered": cov.get("n_uncovered"),
               "pct_covered": cov.get("pct_covered")})

    cat = Counter(r["category"] for r in rows)
    sdb = Counter(r["source_db"] for r in rows)
    cur = Counter(r["curation_tier"] for r in rows)
    ns = Counter(r["namespace"] for r in rows)
    index = {"count": len(rows), "by_category": dict(cat), "by_source_db": dict(sdb),
             "by_curation": dict(cur), "by_namespace": dict(ns),
             "n_missing_coverage": missing_coverage, "media": rows}

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=0)

    # data/stats.json — same pass, same numbers, so the two artifacts cannot drift
    # (it previously had no generator in the repo and shipped 442 media stale).
    stats = {
        "count": len(rows),
        "by_category": dict(cat),
        "by_source_db": dict(sdb),
        "by_curation": dict(cur),
        "by_namespace": dict(ns),
        "api": {"catalog": "data/index.json", "medium": "data/media/{id}.json",
                "stats": "data/stats.json"},
        "note": ("Small enough to fetch for a count without pulling the full catalog. "
                 "Written by build_index.py in the same pass as index.json."),
    }
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)

    print("index media:", len(rows), "| category:", dict(cat))
    print("by source_db:", dict(sdb))
    print("by curation tier:", dict(cur))
    print("by namespace:", dict(ns))
    print("records missing a coverage block: %d/%d (reported as null, never 100%%)"
          % (missing_coverage, len(rows)))
    return index


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--media", default=os.path.join(REPO, "data", "media"),
                    help="directory of per-medium JSON records")
    ap.add_argument("--out", default=os.path.join(REPO, "data"),
                    help="directory to write index.json and stats.json into")
    a = ap.parse_args()
    build(os.path.abspath(a.media), os.path.abspath(a.out))
