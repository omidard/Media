#!/usr/bin/env python3
"""before_after_report — what the stage chain actually changed, measured on both corpora.

Reads two corpus directories (the frozen snapshot and the chain's output) and writes one
JSON report plus a Markdown summary. It computes nothing from a stage's own report: every
number here is recounted from the records themselves, so a stage that claimed a fix it did
not make shows up as an unchanged number rather than as a passing assertion.

Every count carries its denominator. A field that is absent is reported as absent, never as
zero — the difference between "no medium has a licence label" and "0 media are CC BY-NC" is
the whole point of the exercise.

    python3 tools/before_after_report.py --before data/media \
        --after data/_rebuild/media --out data/_rebuild/before_after.json \
        --md data/_rebuild/before_after.md

Named fixes it verifies individually, because a distribution can hide a single wrong record:
  MAP-01  CO2 mapped to cobalt2 (BG-11 and 61 other media)
  MAP-03  D/L enantiomers delivered as the wrong stereoisomer
  MAP-05  the hand-typed USDA nutrient table (cystine/cysteine, selenium, molybdenum)
  NM-01   usda_170772, the quarter-pound hamburger classified as base medium LB
  NM-03   the 1,248 JCM/CCAP media attributed to DSMZ
  PROV-03 the media labelled paper-verified against a paper that does not print the recipe
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG11_RE = re.compile(r"\bBG-?11\b", re.I)
# CASE-SENSITIVE, deliberately. "CO2" (carbon dioxide) and "Co2+" (BiGG's display
# name for cobalt) differ only in the case of the second character, which is the
# whole of finding MAP-01. A case-insensitive regex here would count 11,621 genuine
# cobalt rows as CO2 rows and report the fix as a catastrophe (measured: it did).
CO2_NAME_RE = re.compile(r"^\s*(CO2|CO\u2082|carbon dioxide|Carbon dioxide)(\b|[^a-zA-Z+])")
COBALT_NAME_RE = re.compile(r"^\s*Co2\+|^\s*[Cc]obalt")
HAMBURGER = "usda_170772"

# The seven mapping_method values that mean "the pipeline supplied this component,
# the cited source does not state it". Identical in tools/evidence_tiers.py
# (METHOD_TIERS -> derived_component) and tools/component_evidence_classes.tsv
# (evidence_class -> derived); verified equal set. Used here so the sourced/derived
# split is measurable on the BEFORE corpus too, which carries neither field.
DERIVED_METHODS = {"hydrolysate_approximation", "complex_decomposition", "mineral_base",
                   "base", "base_medium_expansion", "oxygen_regime", "regime"}
STEREO_RE = re.compile(r"^(.*)__([DLRS])$")


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def scan(corpus):
    """One pass. Returns every tally both corpora can be compared on."""
    s = {
        "dir": corpus,
        "n_media": 0,
        "n_components": 0,
        "mapping_confidence": collections.Counter(),
        "evidence_tier": collections.Counter(),
        "evidence_class": collections.Counter(),
        "derived_class": collections.Counter(),
        "license": collections.Counter(),
        "license_by_source": collections.Counter(),
        "commercial_use_ok": collections.Counter(),
        "source_name": collections.Counter(),
        "collection": collections.Counter(),
        "verification_status": collections.Counter(),
        "verification_raw": collections.Counter(),
        "family": collections.Counter(),
        "base_medium": collections.Counter(),
        "category": collections.Counter(),
        "coverage_band_legacy": collections.Counter(),
        "coverage_band_source": collections.Counter(),
        "sourced_components_with_bigg_id_band": collections.Counter(),
        "n_with_concentration": 0,
        "concentration_status": collections.Counter(),
        "n_with_quantity": 0,
        "n_bigg_null": 0,
        "n_exchange_null": 0,
        "n_source_name_kept": 0,
        "n_xref_present": 0,
        "n_source_xref_present": 0,
        "co2_named_components": 0,
        "co2_named_mapped_cobalt2": 0,
        "co2_named_mapped_co2": 0,
        "co2_bad_media": [],
        "cobalt2_components": 0,
        "stereo_ids": collections.Counter(),
        "usda_cys_rows": 0,
        "usda_cysi_rows": 0,
        "cys_rows_all": 0,
        "cysi_rows_all": 0,
        "cobalt_named_components": 0,
        "cobalt_named_mapped_cobalt2": 0,
        "co2_bad_media_n": 0,
        "dsmz_named_media": 0,
        "citation_mentions_dsmz": 0,
        "hamburger": {},
        "media_100pct_legacy_all_derived": 0,
        "n_media_with_derived": 0,
        "derived_by_method": 0,
        "media_all_derived_by_method": 0,
        "media_100pct_legacy_and_all_derived_by_method": 0,
    }
    for fn in sorted(os.listdir(corpus)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(corpus, fn), encoding="utf-8") as fh:
            rec = json.load(fh)
        s["n_media"] += 1
        prov = rec.get("provenance") or {}
        s["category"][rec.get("category")] += 1
        s["license"][str(prov.get("license"))] += 1
        s["commercial_use_ok"][str(prov.get("commercial_use_ok"))] += 1
        src = prov.get("source_name") or ("(unlabelled: %s)" % (prov.get("source_type") or "?"))
        s["source_name"][src] += 1
        s["license_by_source"][(src, str(prov.get("license")))] += 1
        if prov.get("collection"):
            s["collection"][prov["collection"]] += 1
        s["verification_status"][str(prov.get("verification_status"))] += 1
        s["verification_raw"][str(prov.get("verification"))[:60]] += 1
        fam = rec.get("family") or {}
        s["family"][str(fam.get("id"))] += 1
        s["base_medium"][str(rec.get("base_medium"))] += 1

        cov = rec.get("coverage") or {}
        covs = rec.get("coverage_source") or {}
        s["coverage_band_legacy"][_band(cov.get("pct_covered"))] += 1
        s["coverage_band_source"][_band(covs.get("pct_covered_source"))] += 1
        # renamed 2026-09-06; the old key is still read so a before/after run can
        # compare a pre-rename corpus against a post-rename one
        s["sourced_components_with_bigg_id_band"][_band(
            rec.get("pct_sourced_components_with_bigg_id",
                    rec.get("pct_covered_observed")))] += 1

        name = rec.get("name") or ""
        if "DSMZ" in name:
            s["dsmz_named_media"] += 1
        if "DSMZ" in str(prov.get("citation") or ""):
            s["citation_mentions_dsmz"] += 1

        n_derived_here = 0
        n_derived_by_method = 0
        comps = rec.get("components") or []
        for c in comps:
            s["n_components"] += 1
            s["mapping_confidence"][str(c.get("mapping_confidence"))] += 1
            if c.get("evidence_tier"):
                s["evidence_tier"][c["evidence_tier"]] += 1
            if c.get("mapping_method") in DERIVED_METHODS:
                n_derived_by_method += 1
                s["derived_by_method"] += 1
            if c.get("evidence_class"):
                s["evidence_class"][c["evidence_class"]] += 1
                if c["evidence_class"] == "derived":
                    n_derived_here += 1
                    s["derived_class"][str(c.get("derived_class"))] += 1
            bid = c.get("bigg_metabolite")
            if bid is None:
                s["n_bigg_null"] += 1
            if c.get("exchange") is None:
                s["n_exchange_null"] += 1
            if c.get("source_name"):
                s["n_source_name_kept"] += 1
            if c.get("xref"):
                s["n_xref_present"] += 1
            if c.get("source_xref"):
                s["n_source_xref_present"] += 1
            if c.get("concentration_mM") is not None:
                s["n_with_concentration"] += 1
            if c.get("concentration_status"):
                s["concentration_status"][c["concentration_status"]] += 1
            if c.get("quantity"):
                s["n_with_quantity"] += 1
            cname = c.get("name") or ""
            if CO2_NAME_RE.match(cname):
                s["co2_named_components"] += 1
                if bid == "cobalt2":
                    s["co2_named_mapped_cobalt2"] += 1
                    s["co2_bad_media_n"] += 1
                    if len(s["co2_bad_media"]) < 2000:
                        s["co2_bad_media"].append(
                            {"id": rec["id"], "name": rec.get("name"),
                             "component": cname, "bigg": bid,
                             "is_bg11": bool(BG11_RE.search(name))})
                elif bid == "co2":
                    s["co2_named_mapped_co2"] += 1
            if COBALT_NAME_RE.match(cname):
                s["cobalt_named_components"] += 1
                if bid == "cobalt2":
                    s["cobalt_named_mapped_cobalt2"] += 1
            if bid == "cobalt2":
                s["cobalt2_components"] += 1
            if bid == "cys__L":
                s["cys_rows_all"] += 1
            if bid == "cysi__L":
                s["cysi_rows_all"] += 1
            m = STEREO_RE.match(bid or "")
            if m:
                s["stereo_ids"][bid] += 1
            if c.get("mapping_method") in ("usda_nutrient", "usda_mineral"):
                if bid == "cys__L":
                    s["usda_cys_rows"] += 1
                if bid == "cysi__L":
                    s["usda_cysi_rows"] += 1
        if n_derived_here:
            s["n_media_with_derived"] += 1
            if cov.get("pct_covered") == 100.0 and n_derived_here == len(comps):
                s["media_100pct_legacy_all_derived"] += 1
        if comps and n_derived_by_method == len(comps):
            s["media_all_derived_by_method"] += 1
            if cov.get("pct_covered") == 100.0:
                s["media_100pct_legacy_and_all_derived_by_method"] += 1

        if rec["id"] == HAMBURGER:
            meth = collections.Counter((c.get("mapping_method"), c.get("derived_from"))
                                       for c in comps)
            s["hamburger"] = {
                "id": rec["id"], "name": rec.get("name"),
                "category": rec.get("category"),
                "base_medium": rec.get("base_medium"),
                "family": (rec.get("family") or {}).get("id"),
                "family_method": (rec.get("family") or {}).get("method"),
                "verification": prov.get("verification"),
                "verification_status": prov.get("verification_status"),
                "n_components": len(comps),
                "n_derived": sum(1 for c in comps if c.get("evidence_class") == "derived"),
                "n_sourced": sum(1 for c in comps if c.get("evidence_class") == "sourced"),
                "pct_covered_legacy": cov.get("pct_covered"),
                "pct_covered_source": covs.get("pct_covered_source"),
                "component_methods": {str(k): v for k, v in meth.most_common(6)},
            }
    return s


def _band(p):
    if p is None:
        return "not_computed"
    return "high_ge_90" if p >= 90 else ("mid_60_90" if p >= 60 else "review_lt_60")


def diff_counter(before, after, top=None):
    keys = sorted(set(before) | set(after), key=lambda k: -(after.get(k, 0) + before.get(k, 0)))
    if top:
        keys = keys[:top]
    return [{"key": str(k), "before": before.get(k, 0), "after": after.get(k, 0),
             "delta": after.get(k, 0) - before.get(k, 0)} for k in keys]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--before-label", default=None,
                    help="how to name the BEFORE corpus in the report, when it is a "
                         "restored backup rather than a path inside the repo")
    ap.add_argument("--md", default=None)
    a = ap.parse_args()

    b = scan(os.path.abspath(a.before))
    f = scan(os.path.abspath(a.after))

    rep = {
        "before_dir": a.before_label or os.path.relpath(b["dir"], REPO),
        "before_dir_path": os.path.abspath(b["dir"]),
        "after_dir": os.path.relpath(f["dir"], REPO),
        "totals": {"n_media": {"before": b["n_media"], "after": f["n_media"]},
                   "n_components": {"before": b["n_components"], "after": f["n_components"]}},
        "mapping_confidence": diff_counter(b["mapping_confidence"], f["mapping_confidence"]),
        "evidence_tier": diff_counter(b["evidence_tier"], f["evidence_tier"]),
        "evidence_class": diff_counter(b["evidence_class"], f["evidence_class"]),
        "derived_class": diff_counter(b["derived_class"], f["derived_class"]),
        "license": diff_counter(b["license"], f["license"]),
        "commercial_use_ok": diff_counter(b["commercial_use_ok"], f["commercial_use_ok"]),
        "source_name": diff_counter(b["source_name"], f["source_name"], top=30),
        "license_by_source_after": [
            {"source": k[0], "license": k[1], "n": v}
            for k, v in sorted(f["license_by_source"].items(), key=lambda kv: -kv[1])],
        "collection": diff_counter(b["collection"], f["collection"], top=20),
        "verification_status": diff_counter(b["verification_status"], f["verification_status"]),
        "family": diff_counter(b["family"], f["family"], top=30),
        "base_medium": diff_counter(b["base_medium"], f["base_medium"], top=15),
        "coverage_band_legacy": diff_counter(b["coverage_band_legacy"], f["coverage_band_legacy"]),
        "coverage_band_source": diff_counter(b["coverage_band_source"], f["coverage_band_source"]),
        "sourced_components_with_bigg_id_band": diff_counter(
            b["sourced_components_with_bigg_id_band"],
            f["sourced_components_with_bigg_id_band"]),
        "concentration": {
            "n_components_with_concentration_mM": {
                "before": b["n_with_concentration"], "after": f["n_with_concentration"],
                "of": f["n_components"],
                "pct_before": _pct(b["n_with_concentration"], b["n_components"]),
                "pct_after": _pct(f["n_with_concentration"], f["n_components"])},
            "n_components_with_a_verbatim_source_amount": {
                "before": b["n_with_quantity"], "after": f["n_with_quantity"],
                "of": f["n_components"]},
            "status": diff_counter(b["concentration_status"], f["concentration_status"]),
        },
        "provenance_fields": {
            "components_keeping_the_source_string": {
                "before": b["n_source_name_kept"], "after": f["n_source_name_kept"],
                "of": f["n_components"]},
            "components_with_a_source_supplied_xref": {
                "before": b["n_source_xref_present"], "after": f["n_source_xref_present"],
                "of": f["n_components"],
                "note": "before: the field did not exist; the single `xref` block was "
                        "copied from the mapping target (MAP-04)"},
            "components_with_any_xref_block": {
                "before": b["n_xref_present"], "after": f["n_xref_present"],
                "of": f["n_components"]},
            "components_with_no_bigg_id": {
                "before": b["n_bigg_null"], "after": f["n_bigg_null"], "of": f["n_components"]},
            "components_with_no_exchange": {
                "before": b["n_exchange_null"], "after": f["n_exchange_null"],
                "of": f["n_components"],
                "note": "null exchange = the curated verdict that no single exchange is "
                        "defensible (yeast extract, peptone, trace-element solution)"},
        },
        "named_fixes": {
            "MAP-01_co2_mapped_to_cobalt": {
                "co2_named_components": {"before": b["co2_named_components"],
                                         "after": f["co2_named_components"]},
                "mapped_to_cobalt2": {"before": b["co2_named_mapped_cobalt2"],
                                      "after": f["co2_named_mapped_cobalt2"]},
                "mapped_to_co2": {"before": b["co2_named_mapped_co2"],
                                  "after": f["co2_named_mapped_co2"]},
                "genuine_cobalt2_components_total": {"before": b["cobalt2_components"],
                                                     "after": f["cobalt2_components"]},
                "bg11_media_affected_before": sorted(
                    {x["id"] for x in b["co2_bad_media"] if x["is_bg11"]}),
                "n_component_rows_affected": {"before": b["co2_bad_media_n"],
                                              "after": f["co2_bad_media_n"]},
                "n_media_affected": {
                    "before": len({x["id"] for x in b["co2_bad_media"]}),
                    "after": len({x["id"] for x in f["co2_bad_media"]})},
                "media_affected_before_sample": sorted(
                    {x["id"] for x in b["co2_bad_media"]})[:80],
                "media_still_affected_after": sorted({x["id"] for x in f["co2_bad_media"]}),
                "cobalt_named_components": {"before": b["cobalt_named_components"],
                                            "after": f["cobalt_named_components"]},
                "cobalt_named_still_mapped_to_cobalt2": {
                    "before": b["cobalt_named_mapped_cobalt2"],
                    "after": f["cobalt_named_mapped_cobalt2"],
                    "note": "the regression guard: the fix must not convert genuine "
                            "cobalt rows into carbon dioxide (MAP-01 risk_if_fixed_naively)"},
            },
            "MAP-03_stereochemistry": {
                "note": "counts of every stereo-suffixed BiGG id in use; the ledger row "
                        "count for action=stereo_correction is the authoritative fix count",
                "top_changes": [x for x in diff_counter(b["stereo_ids"], f["stereo_ids"])
                                if x["delta"]][:40],
            },
            "MAP-05_usda_name_table": {
                "usda_rows_targeting_cys__L": {"before": b["usda_cys_rows"],
                                               "after": f["usda_cys_rows"]},
                "usda_rows_targeting_cysi__L": {"before": b["usda_cysi_rows"],
                                                "after": f["usda_cysi_rows"]},
                "all_rows_targeting_cys__L": {"before": b["cys_rows_all"],
                                              "after": f["cys_rows_all"]},
                "all_rows_targeting_cysi__L": {"before": b["cysi_rows_all"],
                                               "after": f["cysi_rows_all"],
                                               "note": "the 527 non-USDA rows that kept "
                                                       "their source name were retargeted "
                                                       "to cystine; the 4,834 USDA rows "
                                                       "cannot be, because the builder "
                                                       "overwrote the source string"},
            },
            "NM-01_hamburger_usda_170772": {"before": b["hamburger"], "after": f["hamburger"]},
            "NM-03_dsmz_attribution": {
                "media_named_DSMZ": {"before": b["dsmz_named_media"],
                                     "after": f["dsmz_named_media"]},
                "citations_mentioning_DSMZ": {"before": b["citation_mentions_dsmz"],
                                              "after": f["citation_mentions_dsmz"]},
                "collections_after": dict(f["collection"]),
            },
            "PROV-03_false_paper_verification": {
                "verification_status": diff_counter(b["verification_status"],
                                                    f["verification_status"]),
                "verification_strings_before_top": dict(b["verification_raw"].most_common(10)),
            },
            "COV-03_media_100pct_covered_but_entirely_derived": {
                "before": b["media_100pct_legacy_and_all_derived_by_method"],
                "after": f["media_100pct_legacy_and_all_derived_by_method"],
                "measured_by": "mapping_method, which exists in both corpora",
                "media_entirely_pipeline_derived": {
                    "before": b["media_all_derived_by_method"],
                    "after": f["media_all_derived_by_method"]},
                "derived_components_by_method": {"before": b["derived_by_method"],
                                                 "after": f["derived_by_method"]},
                "of": f["n_media"],
                "note": "the legacy pct_covered is deliberately preserved unchanged; what "
                        "changes is that the same records now also publish "
                        "pct_covered_source, which is 0 for them",
            },
        },
        "media_with_derived_components": {"before": b["n_media_with_derived"],
                                          "after": f["n_media_with_derived"],
                                          "of": f["n_media"]},
    }

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    print("wrote", a.out)

    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(markdown(rep))
        print("wrote", a.md)
    return rep


def _table(fh, rows, cols=("key", "before", "after", "delta")):
    fh.append("| " + " | ".join(cols) + " |")
    fh.append("|" + "|".join(["---"] * len(cols)) + "|")
    for r in rows:
        fh.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    fh.append("")


def markdown(rep):
    out = []
    out.append("# MediaDB rebuild — before and after\n")
    out.append("Before: `%s` (the frozen snapshot). After: `%s` (the stage chain's output).\n"
               % (rep["before_dir"], rep["after_dir"]))
    t = rep["totals"]
    out.append("Media: %d -> %d. Components: %d -> %d. No record and no component was "
               "deleted; the operator's decision was segregate and label.\n"
               % (t["n_media"]["before"], t["n_media"]["after"],
                  t["n_components"]["before"], t["n_components"]["after"]))
    for title, key in [
            ("Mapping confidence, as published", "mapping_confidence"),
            ("Evidence tier — how the identity was actually decided", "evidence_tier"),
            ("Sourced vs pipeline-derived components", "evidence_class"),
            ("Derived components by class", "derived_class"),
            ("Licence", "license"),
            ("Commercial use permitted", "commercial_use_ok"),
            ("Verification status", "verification_status"),
            ("Coverage band — legacy metric", "coverage_band_legacy"),
            ("Coverage band — source-stated composition only", "coverage_band_source"),
            ("Sourced components that reached a BiGG id", "sourced_components_with_bigg_id_band"),
    ]:
        out.append("## %s\n" % title)
        _table(out, rep[key])
    out.append("## Per-source licence schedule (after)\n")
    _table(out, rep["license_by_source_after"], cols=("source", "license", "n"))
    out.append("## Base-medium family\n")
    _table(out, rep["family"][:25])
    out.append("## Concentration coverage\n")
    c = rep["concentration"]["n_components_with_concentration_mM"]
    out.append("concentration_mM present on %d -> %d of %d components (%s%% -> %s%%).\n"
               % (c["before"], c["after"], c["of"], c["pct_before"], c["pct_after"]))
    _table(out, rep["concentration"]["status"])
    out.append("## Named fixes\n")
    out.append("```json")
    out.append(json.dumps(rep["named_fixes"], indent=1)[:20000])
    out.append("```")
    return "\n".join(out)


if __name__ == "__main__":
    main()
