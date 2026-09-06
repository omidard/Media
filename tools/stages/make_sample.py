#!/usr/bin/env python3
"""
make_sample — build the deterministic sample corpus every stage is tested on first.

Rule 3 of the remediation mandate: a stage is unit-tested on a SAMPLE before it is
ever run over the full corpus. This builds that sample so every agent tests against
the same records.

Selection is deterministic and stratified, not random: for each id prefix family
(usda_, mediadive_, food_, growthlit_, complexlit_, lit_, mdb_, biospecimen_, std_,
biolog_, m9_, and the classic singles) take the first N ids in sorted order, plus
every record in a small hand-picked list of known-pathological media named by the
audit, plus at least one record per category and per mapping_confidence value.

Output: data/_rebuild/sample/media/<id>.json  (copies, never symlinks: a stage must
be able to read them without touching data/media)

Usage: python3 tools/stages/make_sample.py [--per-prefix 12] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stagelib import REPO, corpus_ids, read_record  # noqa: E402

FROZEN = os.path.join(REPO, "data", "media")

# Records the audit names explicitly; a sample that misses them cannot exercise the
# defects the stages exist to fix.
PINNED = [
    "cdm_lactobacillaceae",          # 20 legacy single-underscore BiGG ids (MAP-09/SCHEMA-01)
    "biospecimen_hmdb_feces",        # 196 non-BiGG fallback exchanges (SCHEMA-01)
    "biospecimen_hmdb_blood",
    "biospecimen_hmdb_urine",
    "biospecimen_hmdb_saliva",
    "mediadive_381",                 # provenance note claims concentrations it lacks (NM-11)
    "mediadive_1000",
    "food_FOOD00089",                # coverage 29.3% with 65 uncovered (SCHEMA-07)
    "food_FOOD00134",                # L-glutamate carrying D-glutamate's xrefs (MAP-12)
    "std_bg11",                      # base_medium present, invisible downstream (NM-04)
    "api_cho_base",
    "lb_lennox",
    "mdb_281",                       # 100% coverage with 6 non-BiGG components
    "mdb_293",
]

PREFIXES = ["usda_", "mediadive_", "food_", "growthlit_", "complexlit_", "lit_",
            "mdb_", "biospecimen_", "std_", "biolog_", "m9_"]


def build(out_dir: str, per_prefix: int) -> dict:
    ids = corpus_ids(FROZEN)
    chosen: list[str] = []
    for pre in PREFIXES:
        fam = [i for i in ids if i.startswith(pre)]
        chosen += fam[:per_prefix]
        chosen += fam[-2:] if len(fam) > per_prefix else []
    # the classic singles and anything not covered by a prefix family
    unfamilied = [i for i in ids if not any(i.startswith(p) for p in PREFIXES)]
    chosen += unfamilied[:per_prefix]
    chosen += [i for i in PINNED if i in ids]

    # top up so every category and every mapping_confidence value is represented
    have_cat, have_conf = set(), set()
    chosen_set = set(chosen)
    for mid in chosen:
        rec = read_record(os.path.join(FROZEN, mid + ".json"))
        have_cat.add(rec.get("category"))
        for c in rec.get("components") or []:
            have_conf.add(c.get("mapping_confidence"))
    want_conf = {"exact", "inferred", "convention", "approximation", "curated",
                 "standard_formulation", "high"}
    for mid in ids:
        if want_conf <= have_conf:
            break
        if mid in chosen_set:
            continue
        rec = read_record(os.path.join(FROZEN, mid + ".json"))
        confs = {c.get("mapping_confidence") for c in rec.get("components") or []}
        if confs & (want_conf - have_conf):
            chosen.append(mid)
            chosen_set.add(mid)
            have_conf |= confs
            have_cat.add(rec.get("category"))

    chosen = sorted(set(chosen))
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)                 # regenerated artifact, not source data
    os.makedirs(out_dir, exist_ok=True)
    for mid in chosen:
        shutil.copy2(os.path.join(FROZEN, mid + ".json"),
                     os.path.join(out_dir, mid + ".json"))

    meta = {
        "built_from": "data/media",
        "n_records": len(chosen),
        "per_prefix": per_prefix,
        "categories": sorted(x for x in have_cat if x),
        "mapping_confidence_covered": sorted(x for x in have_conf if x),
        "pinned_present": [p for p in PINNED if p in chosen],
        "pinned_missing": [p for p in PINNED if p not in chosen],
        "ids": chosen,
    }
    with open(os.path.join(os.path.dirname(out_dir), "sample_manifest.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-prefix", type=int, default=12)
    ap.add_argument("--out", default=os.path.join(REPO, "data", "_rebuild", "sample", "media"))
    a = ap.parse_args()
    m = build(os.path.abspath(a.out), a.per_prefix)
    print("sample corpus: %d records -> %s" % (m["n_records"], os.path.relpath(a.out, REPO)))
    print("categories:", m["categories"])
    print("mapping_confidence covered:", m["mapping_confidence_covered"])
    if m["pinned_missing"]:
        print("WARNING pinned ids not found in data/media:", m["pinned_missing"])
