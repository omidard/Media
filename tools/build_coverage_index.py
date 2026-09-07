#!/usr/bin/env python3
"""build_coverage_index — project data/coverage.json from the corpus.

WHY THIS EXISTS
    data/coverage.json used to be a side effect of tools/enrich_coverage.py, which
    both COMPUTED the per-record coverage block and DUMPED an index of it. Stage
    39_recompute_coverage has since taken authorship of the coverage block, and
    enrich_coverage.py correctly refuses to run over a corpus carrying that stamp —
    which left the published coverage.json with no generator at all and no way back.
    That is exactly the orphan-artifact pattern the audit found on data/stats.json
    (no generator anywhere in tools/, shipped 442 media stale) and on two endpoints
    that were 1,128 media stale (STALE-01).

    So the dump is separated from the computation. This script only PROJECTS what
    the corpus already says. It computes no coverage of its own, and it never
    invents a value: a record without a coverage block yields null, not 100.

WHAT IT WRITES
    data/coverage.json
      media[id] = {category, n_compounds, n_covered, n_uncovered, pct_covered,
                   by_source,                      <- unchanged legacy shape
                   n_sourced, n_derived, pct_covered_source,
                   pct_covered_source_is_upper_bound,
                   pct_sourced_components_with_bigg_id}
      totals    = {exchange_sources, n_uncovered,  <- unchanged legacy shape
                   n_components, n_sourced_components, n_derived_components,
                   media_by_legacy_band, media_by_source_band, definitions}

    The legacy keys keep their names and their meanings. pct_covered is the metric
    that counts pipeline-derived components as covered; it is deprecated in place
    rather than redefined under its own name, because it is published.

    python3 tools/build_coverage_index.py [--media DIR] [--out FILE]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_bigg_exchange_ids import exchange_state   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFINITIONS = {
    "pct_covered": "DEPRECATED legacy metric: components / (components + unresolved "
                   "ingredients). Counts pipeline-derived components as covered.",
    "pct_covered_source": "source-stated components / (those + unresolved ingredients "
                          "+ ingredients replaced by derived components). An upper "
                          "bound where pct_covered_source_is_upper_bound is true.",
    "pct_sourced_components_with_bigg_id":
        "of the components the cited source states, the share that reached a BiGG "
        "metabolite id rather than a non-BiGG fallback or nothing. Its denominator "
        "is components, NOT the source's ingredient list, so it is 100.0 on 12,861 "
        "of 13,515 records and is not a coverage measure. The name "
        "pct_covered_observed resolves to this field; see field_renames in "
        "data/index.json.",
    "exchange_resolution":
        "where each component's exchange id landed, in four states: a reaction BiGG "
        "actually has, an id of the EX_<met>_e shape naming no BiGG reaction (no "
        "model has it, so the documented adoption path drops it silently), a "
        "ModelSEED/MetaNetX/KEGG fallback no BiGG model will accept, or nothing at "
        "all. The four partition n_components; the last three are all unusable to a "
        "model.",
    "null": "a null percentage means the denominator was zero. It does not mean 100.",
}


def band(p):
    if p is None:
        return "not_computed"
    return "high_ge_90" if p >= 90 else ("mid_60_90" if p >= 60 else "review_lt_60")


def build(media_dir: str, out_path: str) -> dict:
    files = sorted(glob.glob(os.path.join(media_dir, "*.json")))
    if not files:
        raise SystemExit(
            "FATAL: no media found in %s. coverage.json is a published endpoint; "
            "writing an empty one would silently destroy it." % media_dir)

    media = {}
    ex_sources = collections.Counter()
    legacy_band = collections.Counter()
    source_band = collections.Counter()
    tot_unc = tot_comp = tot_sourced = tot_derived = 0
    exch = collections.Counter()

    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        cov = d.get("coverage") or {}
        cs = d.get("coverage_source") or {}
        comps = d.get("components") or []
        by_source = collections.Counter()
        n_bigg = n_fallback = n_none = n_noreaction = 0
        for c in comps:
            src = c.get("exchange_source")
            if src:
                by_source[src] += 1
                ex_sources[src] += 1
            state = exchange_state(c)
            if state == "n_no_exchange":
                n_none += 1
            elif state == "n_nonbigg_fallback":
                n_fallback += 1
            elif state == "n_bigg_shaped_no_such_exchange":
                n_noreaction += 1
            else:
                n_bigg += 1
        exch["n_bigg_exchange"] += n_bigg
        exch["n_nonbigg_fallback"] += n_fallback
        exch["n_bigg_shaped_no_such_exchange"] += n_noreaction
        exch["n_no_exchange"] += n_none
        n_unc = cov.get("n_uncovered")
        tot_unc += n_unc or 0
        tot_comp += len(comps)
        tot_sourced += cs.get("n_sourced") or 0
        tot_derived += cs.get("n_derived") or 0
        legacy_band[band(cov.get("pct_covered"))] += 1
        source_band[band(cs.get("pct_covered_source"))] += 1
        media[d["id"]] = {
            "category": d.get("category"),
            "n_compounds": cov.get("n_compounds", len(comps)),
            "n_covered": cov.get("n_covered"),
            "n_uncovered": n_unc,
            "pct_covered": cov.get("pct_covered"),
            "by_source": dict(by_source),
            "n_sourced": cs.get("n_sourced"),
            "n_derived": cs.get("n_derived"),
            "pct_covered_source": cs.get("pct_covered_source"),
            "pct_covered_source_is_upper_bound":
                cs.get("pct_covered_source_is_upper_bound"),
            "pct_sourced_components_with_bigg_id":
                d.get("pct_sourced_components_with_bigg_id",
                      d.get("pct_covered_observed")),
            "n_bigg_exchange": n_bigg,
            "n_nonbigg_fallback": n_fallback,
            "n_no_exchange": n_none,
            "n_bigg_shaped_no_such_exchange": n_noreaction,
        }

    out = {
        "media": media,
        "totals": {
            "exchange_sources": dict(ex_sources),
            "exchange_resolution": dict(exch, of=tot_comp),
            "n_uncovered": tot_unc,
            "n_media": len(media),
            "n_components": tot_comp,
            "n_sourced_components": tot_sourced,
            "n_derived_components": tot_derived,
            "media_by_legacy_band": dict(legacy_band),
            "media_by_source_band": dict(source_band),
            "definitions": DEFINITIONS,
        },
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print("wrote %s (%d media)" % (os.path.relpath(out_path, REPO), len(media)))
    print("  components %d = sourced %d + derived %d"
          % (tot_comp, tot_sourced, tot_derived))
    print("  legacy bands %s" % dict(legacy_band))
    print("  source bands %s" % dict(source_band))
    print("  exchange resolution %s" % dict(exch))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--media", default=os.path.join(REPO, "data", "media"))
    ap.add_argument("--out", default=os.path.join(REPO, "data", "coverage.json"))
    a = ap.parse_args()
    build(os.path.abspath(a.media), os.path.abspath(a.out))
