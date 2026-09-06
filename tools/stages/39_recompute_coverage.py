#!/usr/bin/env python3
"""Stage 39 — coverage recomputed with its denominator, and derived composition excluded.

READS  a corpus that has already been through stage 20 (every component carries
       `evidence_class`). Raises rather than guessing if it has not.
WRITES the same corpus with a `coverage_source` block on every record.

CLOSES the coverage half of COV-03, PROV-07 and MEDIA-WEB-02. The other half of COV-02 /
       PROV-11 / COV-06 — one authoritative total instead of four — is enforced by
       tools/verify_counts.py, which computes the count from the corpus and fails when any
       shipped artifact disagrees.

ORDER  Runs last in the 30-39 range, after any component-labelling stage: a coverage number
       computed before every component is classified would be a coverage number computed on
       a guess. Declared `after: ["20_stamp_provenance"]`.

WHY THE SHIPPED NUMBER IS WRONG
       tools/enrich_coverage.py:456-459 computes pct_covered as len(components) /
       (len(components) + len(uncovered)). `components` is the FINAL list, so every
       pipeline-invented component counts as covered — and the numerator counts COMPONENTS
       while the denominator counts unresolved source INGREDIENTS. Decomposing one
       unmappable ingredient into 35 metabolites therefore removes a failure from the
       denominator and adds 35 successes to the numerator at once. The metric rises fastest
       exactly where the source data is weakest: "Nutrient Agar (DSMZ 1)" ships 49 components
       of which 0 come from the recipe, and displays "Coverage 98%".

WHAT IS EMITTED
       pct_covered_all      the legacy formula, recomputed and asserted equal to the shipped
                            value for every record, so the change is auditable.
       pct_covered_source   source-stated components over those plus every ingredient the
                            pipeline failed to resolve, INCLUDING the ingredients it replaced
                            with derived components instead of leaving unresolved.
       pct_sourced_of_components   the share of shipped components the source states.

       Both are published. The honest number does not replace the legacy one: a complex
       medium whose beef extract is decomposed from a cited Handbook of Microbiological Media
       entry is not worthless, and ranking the library by source coverage alone would bury
       the media the resource exists to serve. Colour by the honest number; print both.

       The legacy `coverage` block is left untouched. `pct_covered` is a published column in
       media.parquet, media.sqlite.gz and openapi.yaml — it is deprecated in place, never
       redefined under its own name.

CEILINGS ARE DECLARED
       Restoring a replaced ingredient to the denominator needs to know WHICH ingredient was
       replaced, and the corpus cannot always say: hydrolysate_approximation carries no
       derived_from at all (0 of 100,619), and complex_decomposition collapses several recipe
       lines onto one name (all 40 invented BHI components say "beef extract" though the
       recipe also lists brain infusion, heart infusion and peptone). The replaced count is
       therefore a floor and the ratio built on it a ceiling, and every affected record says
       so. An unknown is labelled, not rounded to the flattering end.

NULL IS NULL
       A zero denominator yields null, never 100. build_index.py:41, index.html:292 and
       assets/media.js:234 each turn a missing coverage into a green 100% badge; this stage
       refuses to feed them a fabricated default. Fixing those three belongs to the index and
       browser workstreams.

ASSERTS
       the corpus is stamped; the recomputed legacy value reproduces the shipped one for
       every record; pct_covered_source never exceeds pct_covered_all; no percentage is
       emitted from a zero denominator.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from stagelib import Report, StageError, main_guard, stamp  # noqa: E402

STAGE, VERSION = "39_recompute_coverage", "1.0.0"

DERIVED_INFERRED = "inferred_from_listed_ingredient"
DERIVED_INJECTED = "injected_convention"
DERIVED_BASE = "canonical_base_expansion"

# The two methods that consume a source ingredient and put invented components in its place.
# Both are "derived", but only these removed an ingredient that would otherwise have been
# counted as unresolved — which is why only these are restored to the denominator.
REPLACING_METHODS = {"complex_decomposition", "hydrolysate_approximation"}

DEFINITION = (
    "pct_covered_all = components / (components + unresolved ingredients) — the legacy "
    "metric, which counts pipeline-derived components as covered. pct_covered_source = "
    "source-stated components / (those + unresolved ingredients + ingredients replaced by "
    "derived components). Component classes come from tools/component_evidence_classes.tsv. "
    "A null value means the denominator was zero; it does not mean 100."
)


def _pct(num, den):
    """A percentage, or null. Never a default, never a guess."""
    return round(100.0 * num / den, 1) if den else None


def coverage_for(rec):
    """The coverage_source block for one stamped record."""
    comps = rec.get("components") or []
    uncovered = rec.get("uncovered") or []

    n_sourced = n_inf = n_inj = n_base = 0
    replaced_named = set()
    names_unavailable = False
    for c in comps:
        ec = c.get("evidence_class")
        if ec is None:
            raise StageError(
                "%s: a component has no evidence_class. Run 20_stamp_provenance first — this "
                "stage computes coverage from the sourced/derived split and will not guess it."
                % rec.get("id"))
        if ec == "sourced":
            n_sourced += 1
        else:
            dc = c.get("derived_class")
            if dc == DERIVED_INFERRED:
                n_inf += 1
            elif dc == DERIVED_INJECTED:
                n_inj += 1
            elif dc == DERIVED_BASE:
                n_base += 1
            else:
                raise StageError("%s: derived component with unknown derived_class %r"
                                 % (rec.get("id"), dc))
        if c.get("mapping_method") in REPLACING_METHODS:
            df = c.get("derived_from")
            if df:
                replaced_named.add(str(df).strip().lower())
            elif c.get("mapping_method") == "hydrolysate_approximation":
                names_unavailable = True

    n_components = len(comps)
    n_derived = n_inf + n_inj + n_base
    n_uncovered = len(uncovered)
    n_replaced = len(replaced_named) + (1 if names_unavailable else 0)

    den_all = n_components + n_uncovered
    den_source = n_sourced + n_uncovered + n_replaced

    return {
        "n_components": n_components,
        "n_sourced": n_sourced,
        "n_derived": n_derived,
        "n_derived_inferred_from_listed_ingredient": n_inf,
        "n_derived_injected_convention": n_inj,
        "n_derived_canonical_base_expansion": n_base,
        "n_uncovered_ingredients": n_uncovered,
        "n_source_ingredients_replaced_by_derived_components": n_replaced,
        "replaced_ingredient_count_is_lower_bound": n_replaced > 0,
        "replaced_ingredient_names_unavailable": names_unavailable,
        "pct_covered_all": _pct(n_components, den_all),
        "pct_covered_all_denominator": den_all or None,
        "pct_covered_source": _pct(n_sourced, den_source),
        "pct_covered_source_denominator": den_source or None,
        "pct_covered_source_is_upper_bound": n_replaced > 0,
        "pct_sourced_of_components": _pct(n_sourced, n_components),
        "definition": DEFINITION,
    }


def _band(p):
    if p is None:
        return "not_computed"
    return "high_ge_90" if p >= 90 else ("mid_60_90" if p >= 60 else "review_lt_60")


def transform(rec, rep):
    block = coverage_for(rec)

    # Counting happens on EVERY record, not only the ones this run changes. A report that
    # only described the diff would go blank on a re-run and take its own assertions with it,
    # which is the silent-pass failure this pipeline exists to eliminate. The report describes
    # the corpus; the return value describes the diff.
    shipped = (rec.get("coverage") or {}).get("pct_covered")
    if shipped is not None and block["pct_covered_all"] is not None:
        if abs(shipped - block["pct_covered_all"]) > 0.11:
            rep.count("legacy_pct_covered_did_not_reproduce", 1, rep.n_in)
            rep.example("legacy_pct_covered_did_not_reproduce",
                        {"id": rec.get("id"), "shipped": shipped,
                         "recomputed": block["pct_covered_all"]})
        else:
            rep.count("legacy_pct_covered_reproduced", 1, rep.n_in)

    a, b = shipped, block["pct_covered_source"]
    rep.count("legacy_band_%s" % _band(a), 1, rep.n_in)
    rep.count("source_band_%s" % _band(b), 1, rep.n_in)
    if b is None:
        rep.count("pct_covered_source_null_zero_denominator", 1, rep.n_in)
    else:
        if b == 0.0:
            rep.count("media_at_zero_source_coverage", 1, rep.n_in)
            rep.example("media_at_zero_source_coverage",
                        {"id": rec.get("id"), "legacy_pct_covered": a,
                         "n_components": block["n_components"]})
        if a is not None:
            if b > a + 0.11:
                rep.count("source_coverage_exceeded_legacy", 1, rep.n_in)
            if a >= 90 and b < 60:
                rep.count("media_leaving_the_green_band", 1, rep.n_in)
    if block["pct_covered_source_is_upper_bound"]:
        rep.count("pct_covered_source_is_a_ceiling", 1, rep.n_in)
    if block["n_derived"]:
        rep.count("media_with_derived_components", 1, rep.n_in)

    if rec.get("coverage_source") == block:
        return False
    rec["coverage_source"] = block
    stamp(rec, STAGE, VERSION, ["coverage_source"])
    return True


def finalize(rep):
    n = rep.n_in
    c = rep.counters

    def got(name):
        return c.get(name, {"n": 0})["n"]

    rep.assert_eq("legacy_pct_covered_reproduces_for_every_record",
                  got("legacy_pct_covered_did_not_reproduce"), 0)
    rep.assert_eq("source_coverage_never_flatters_legacy_coverage",
                  got("source_coverage_exceeded_legacy"), 0)
    rep.assert_eq("coverage_bands_partition_the_corpus",
                  sum(v["n"] for k, v in c.items() if k.startswith("source_band_")), n)

    green_legacy = got("legacy_band_high_ge_90")
    green_source = got("source_band_high_ge_90")
    rep.count("headline_high_confidence_legacy_pct", 0, n)
    rep.counters["headline_high_confidence_legacy_pct"]["n"] = green_legacy
    rep.count("headline_high_confidence_source_pct", 0, n)
    rep.counters["headline_high_confidence_source_pct"]["n"] = green_source
    rep.assert_le("honest_headline_is_not_larger_than_the_advertised_one",
                  green_source, green_legacy)

    rep.unresolved(
        "pct_covered_source_is_a_ceiling", got("pct_covered_source_is_a_ceiling"), n,
        "the count of source ingredients replaced by derived components is a floor — "
        "hydrolysate_approximation records no derived_from (0 of 100,619 components) and "
        "complex_decomposition collapses several recipe lines onto one name — so the ratio "
        "built on it is a ceiling. Recorded per record rather than presented as the value.")
    rep.unresolved(
        "media_at_zero_source_coverage", got("media_at_zero_source_coverage"), n,
        "not one component of these media is stated by the source they cite; their "
        "composition is entirely this pipeline's. They are labelled, not removed.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize, inputs=[])
