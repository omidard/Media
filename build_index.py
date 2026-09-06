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
import sys
from collections import Counter

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "tools"))

from model_input import Degeneracy   # noqa: E402
from web_payload import FIELD_RENAMES   # noqa: E402


def source_identity(d):
    """(source_db, source_id, evidence) — the record's own verified identity first.

    The 20-range provenance stage resolves source identity from record evidence and
    writes provenance.source_name / source_id / source_identity_evidence. Where it has
    run, the catalog uses it. The id-prefix heuristic below is the fallback for a record
    that stage never saw, and it labels itself as a heuristic so the catalog never
    presents a guess and a determination in the same field without saying which is which
    (NM-03 / PROV-06: the heuristic is wrong for the 1,248 MediaDive records that are
    JCM or CCAP rather than DSMZ).
    """
    prov = d.get("provenance") or {}
    name = prov.get("source_name")
    if name:
        return (name, prov.get("source_id"),
                prov.get("source_identity_evidence") or "20_stamp_provenance")
    return (source_db_by_prefix(d["id"], prov, d.get("food_group", "")),
            None, "id_prefix_heuristic")


def source_db_by_prefix(idv, prov, food_group):
    # Legacy fallback only — see source_identity().
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
    missing_coverage_source = 0
    prefix_sourced = 0
    tier_totals = Counter()
    comp_totals = Counter()
    # Where every component's exchange id landed, counted from the components
    # rather than trusted from the record's counters, then asserted against them.
    exch = Counter()
    xrefs = Counter()
    n_components_seen = 0
    degeneracy = Degeneracy()
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        cov = d.get("coverage")
        if not cov:
            missing_coverage += 1
            cov = {}
        covs = d.get("coverage_source")
        if not covs:
            missing_coverage_source += 1
            covs = {}
        tier = curation_tier(d["id"], (d.get("provenance") or {}).get("verification"))
        prov = d["provenance"]
        sdb, sid, sev = source_identity(d)
        if sev == "id_prefix_heuristic":
            prefix_sourced += 1
        fam = d.get("family") or {}
        quant = d.get("quantitation") or {}
        for t, n in (d.get("tier_counts") or {}).items():
            tier_totals[t] += n
        comp_totals["n_components"] += d.get("n_components") or 0
        comp_totals["n_observed"] += d.get("n_observed") or 0
        comp_totals["n_derived"] += d.get("n_derived") or 0
        comp_totals["n_sourced"] += covs.get("n_sourced") or 0
        comp_totals["n_with_concentration_mM"] += quant.get("n_with_concentration_mM") or 0
        n_bigg = n_fallback = n_none = 0
        n_components_seen += len(d.get("components") or [])
        for c in d.get("components") or []:
            # xref_id is the reference-table form of the same fact (stage 60);
            # an absent id means no cross-references at all.
            if (c.get("xref") or c.get("target_xref") or c.get("source_xref")
                    or c.get("xref_id")):
                xrefs["n_components_with_a_cross_reference"] += 1
            else:
                xrefs["n_components_with_none"] += 1
            if not c.get("exchange"):
                n_none += 1
            elif c.get("evidence_tier") == "non_bigg_fallback":
                n_fallback += 1
            else:
                n_bigg += 1
        exch["n_bigg_exchange"] += n_bigg
        exch["n_nonbigg_fallback"] += n_fallback
        exch["n_no_exchange"] += n_none
        degeneracy.add(d)
        rows.append(
            {k: d.get(k) for k in ("id", "name", "category", "organism_scope", "aerobic",
                                   "oxygen", "n_components", "n_mapped", "n_in_biggr",
                                   "namespace")}
            | {"source_type": prov["source_type"],
               "source_db": sdb,
               "source_id": sid,
               "source_identity_evidence": sev,
               # --- licence, per source (operator decision: segregate and label) ---
               "license": prov.get("license"),
               "commercial_use_ok": prov.get("commercial_use_ok"),
               "attribution_required": prov.get("attribution_required"),
               # --- how the record's composition was verified, honestly ----------
               "verification_status": prov.get("verification_status"),
               "collection": prov.get("collection"),
               # --- sourced vs pipeline-derived composition ----------------------
               "n_observed": d.get("n_observed"),
               "n_derived": d.get("n_derived"),
               "n_unmappable": d.get("n_unmappable"),
               # Renamed from pct_covered_observed: the old name read as coverage
               # of the medium and was 100.0 on 12,861 of 13,515 records, because
               # its denominator is the components the record already carries.
               # See index["field_renames"]. The read falls back to the old key so
               # the catalog builds against a corpus written before the rename.
               "pct_sourced_components_with_bigg_id":
                   d.get("pct_sourced_components_with_bigg_id",
                         d.get("pct_covered_observed")),
               "n_sourced": covs.get("n_sourced"),
               "pct_covered_source": covs.get("pct_covered_source"),
               "pct_covered_source_is_upper_bound":
                   covs.get("pct_covered_source_is_upper_bound"),
               # --- naming / grouping --------------------------------------------
               "name_display": d.get("name_display"),
               "family": fam.get("id"),
               "family_label": fam.get("label"),
               # --- quantitation --------------------------------------------------
               "n_with_concentration_mM": quant.get("n_with_concentration_mM"),
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
               "n_nonbigg_fallback": n_fallback,
               # the third state: no exchange reaction at all. Published rather
               # than left to be derived, because the claim it corrects ("every
               # component mapped to a BiGG exchange") was the site's headline.
               "n_no_exchange": n_none,
               # which OTHER records hand a model the identical constraint set;
               # filled after the whole corpus is read (see below)
               "model_input_signature": None,
               "n_media_with_identical_model_input": None,
               # absent measurement is null, never a fabricated 100% (SCHEMA-07)
               "n_uncovered": cov.get("n_uncovered"),
               "pct_covered": cov.get("pct_covered")})

    # Model-input degeneracy is a corpus-wide fact, so it is filled once every
    # record has been read. A one-pass answer would report a prefix's degeneracy
    # as the library's.
    degen = degeneracy.report()
    for r in rows:
        r["model_input_signature"] = degeneracy.signature_of(r["id"])
        r["n_media_with_identical_model_input"] = degeneracy.n_twins(r["id"])

    # Asserted against the components actually walked, never against a declared
    # counter: the three states must partition them or the catalog would state a
    # mapping claim it cannot support.
    if sum(exch.values()) != n_components_seen or sum(xrefs.values()) != n_components_seen:
        raise SystemExit(
            "FATAL: exchange resolution accounts for %d and cross-references for "
            "%d of the %d components walked."
            % (sum(exch.values()), sum(xrefs.values()), n_components_seen))

    cat = Counter(r["category"] for r in rows)
    sdb = Counter(r["source_db"] for r in rows)
    cur = Counter(r["curation_tier"] for r in rows)
    ns = Counter(r["namespace"] for r in rows)
    lic = Counter(r["license"] for r in rows)
    com = Counter(r["commercial_use_ok"] for r in rows)
    ver = Counter(r["verification_status"] for r in rows)
    fam = Counter(r["family"] for r in rows if r["family"])
    col = Counter(r["collection"] for r in rows if r["collection"])

    def band(p):
        if p is None:
            return "not_computed"
        return "high_ge_90" if p >= 90 else ("mid_60_90" if p >= 60 else "review_lt_60")

    bands_legacy = Counter(band(r["pct_covered"]) for r in rows)
    bands_source = Counter(band(r["pct_covered_source"]) for r in rows)

    index = {
        "count": len(rows),
        # ONE authoritative total, computed from the corpus on disk, carried by every
        # artifact this pass writes (COV-02 / PROV-11 / NM-20). tools/verify_counts.py
        # fails the build if any shipped artifact disagrees with it.
        "count_authority": "data/media/*.json on disk, counted by build_index.py",
        "by_category": dict(cat), "by_source_db": dict(sdb),
        "by_curation": dict(cur), "by_namespace": dict(ns),
        "by_license": {str(k): v for k, v in lic.items()},
        "by_commercial_use_ok": {str(k): v for k, v in com.items()},
        "by_verification_status": {str(k): v for k, v in ver.items()},
        "by_collection": dict(col),
        "by_family": dict(fam),
        "coverage_bands_legacy": dict(bands_legacy),
        "coverage_bands_source": dict(bands_source),
        "component_totals": dict(comp_totals),
        "exchange_resolution": dict(
            exch, of=n_components_seen,
            definition=(
                "Where each component's exchange id landed, over the whole "
                "library. n_bigg_exchange is a real BiGG EX_<met>_e reaction; "
                "n_nonbigg_fallback is a ModelSEED/MetaNetX/KEGG id in exchange "
                "position that no BiGG model will accept (the component's own "
                "mapping_note says so); n_no_exchange has none at all. The three "
                "partition n_components.")),
        "cross_references": dict(
            xrefs, of=n_components_seen,
            definition=(
                "A component counts as carrying a cross-reference when it has any of "
                "xref, target_xref or source_xref. The README claimed every component "
                "carried one; 8,957 of 665,582 carry none.")),
        "model_input_degeneracy": degen,
        "field_renames": FIELD_RENAMES,
        "component_evidence_tiers": dict(tier_totals),
        "n_missing_coverage": missing_coverage,
        "n_missing_coverage_source": missing_coverage_source,
        "n_source_db_from_id_prefix_heuristic": prefix_sourced,
        "definitions": {
            "pct_covered": "DEPRECATED legacy metric: components / (components + "
                           "unresolved ingredients). Counts pipeline-derived components "
                           "as covered. Kept because it is a published column.",
            "pct_covered_source": "source-stated components / (those + unresolved "
                                  "ingredients + ingredients replaced by derived "
                                  "components). An upper bound where the flag says so. "
                                  "null means the denominator was zero, NOT 100.",
            "pct_sourced_components_with_bigg_id":
                "of the components the cited source states, the share that reached a "
                "BiGG metabolite id rather than a non-BiGG fallback or nothing. Its "
                "denominator is components, not the source's ingredient list, so it is "
                "100.0 on 12,861 of 13,515 records and is NOT a coverage measure. It "
                "was named pct_covered_observed until 2026-09-06; see field_renames.",
            "n_no_exchange": "components with no exchange reaction at all: identity was "
                             "never established, or the ingredient is an undefined "
                             "mixture. 218 of 665,582 components library-wide.",
            "n_nonbigg_fallback": "components whose exchange id is a ModelSEED/MetaNetX/"
                                  "KEGG fallback rather than a BiGG id; no BiGG model "
                                  "will accept it. 1,364 of 665,582 library-wide.",
            "n_media_with_identical_model_input":
                "how many OTHER media hand a genome-scale model the identical set of "
                "(exchange, lower bound, upper bound) triples. 0 means this record's "
                "model input is unique in the library. See model_input_degeneracy.",
            "n_derived": "components the pipeline supplied that the cited source does not "
                         "state (hydrolysate approximations, complex decompositions, "
                         "injected mineral/oxygen bases, expanded base media). Kept and "
                         "labelled, never deleted.",
            "commercial_use_ok": "false for records whose upstream licence forbids "
                                 "commercial use (FooDB CC BY-NC, MediaDB-ISB all rights "
                                 "reserved, HMDB-derived). They ship, labelled.",
            "source_identity_evidence": "how source_db was decided: 20_stamp_provenance "
                                        "(from record evidence) or id_prefix_heuristic.",
            "component_evidence_tiers": "how each component's identity was actually "
                                        "decided; see tools/evidence_tiers.py. A name "
                                        "match is a fallback tier, not 'exact'.",
        },
        "media": rows,
    }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=0)

    # data/stats.json — same pass, same numbers, so the two artifacts cannot drift
    # (it previously had no generator in the repo and shipped 442 media stale).
    stats = {
        "count": len(rows),
        "count_authority": index["count_authority"],
        "by_category": dict(cat),
        "by_source_db": dict(sdb),
        "by_curation": dict(cur),
        "by_namespace": dict(ns),
        "by_license": index["by_license"],
        "by_commercial_use_ok": index["by_commercial_use_ok"],
        "by_verification_status": index["by_verification_status"],
        "coverage_bands_legacy": index["coverage_bands_legacy"],
        "coverage_bands_source": index["coverage_bands_source"],
        "component_totals": index["component_totals"],
        "exchange_resolution": index["exchange_resolution"],
        "cross_references": index["cross_references"],
        "model_input_degeneracy": index["model_input_degeneracy"],
        "field_renames": index["field_renames"],
        "component_evidence_tiers": index["component_evidence_tiers"],
        "definitions": index["definitions"],
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
    print("records missing coverage_source: %d/%d | source_db from the id-prefix "
          "heuristic: %d/%d" % (missing_coverage_source, len(rows),
                                prefix_sourced, len(rows)))
    print("by licence:", dict(lic))
    print("component totals:", dict(comp_totals))
    print("exchange resolution: %d BiGG + %d non-BiGG fallback + %d no exchange "
          "= %d components" % (exch["n_bigg_exchange"], exch["n_nonbigg_fallback"],
                               exch["n_no_exchange"], comp_totals["n_components"]))
    print("model-input degeneracy: %d of %d media share their model input with "
          "another record (%d groups, largest %d)"
          % (degen["n_media_sharing_a_model_input"], len(rows),
             degen["n_groups"], degen["largest_group"]))
    print("component evidence tiers:", dict(tier_totals))
    print("coverage bands  legacy:", dict(bands_legacy))
    print("coverage bands  source:", dict(bands_source))
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
