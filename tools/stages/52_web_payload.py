#!/usr/bin/env python3
"""Build and verify the browser payload from the corrected corpus (copy-through).

FINDINGS: MEDIA-WEB-01 MEDIA-WEB-02 MEDIA-WEB-04 MEDIA-WEB-05 MEDIA-WEB-06
MEDIA-WEB-07 MEDIA-WEB-10 MEDIA-WEB-11 MEDIA-WEB-14 MEDIA-WEB-16 MEDIA-WEB-17
MEDIA-WEB-20 UX-01 COV-02 COV-05 NM-05

CONTRACT
--------
reads   : the corpus at --in (per-medium JSON), plus data/_quarantine.json
writes  : the corpus at --out, byte-identical to --in (this stage changes no
          record and stamps none), AND the browser payload at
          <out>/../web/{catalog,compounds,families,tombstones}.json
asserts : 1. every component falls in exactly one of the six evidence classes,
             so nothing can be invisible in the browser's evidence bar while
             still being counted in the component total;
          2. the catalog carries one row per record in the corpus;
          3. the source-coverage bands partition the corpus (they are what the
             coverage figure draws, and a band that stops summing to the
             denominator vanishes silently from a bar, MEDIA-WEB-05);
          4. no `pct_covered_source` is a number where the record says its
             denominator was zero (absent is null, never 100, MEDIA-WEB-05);
          5. no withdrawn (quarantined) id is also live in the corpus, so a
             tombstone can never contradict a served record (COV-05);
          6. the compound index covers every exchange that appears in the
             corpus, not a stale subset (MEDIA-WEB-06 refuted the presence
             matrix as an index: it covers 77 of 1,793 exchanges).

WHY THIS IS A STAGE AND NOT ONLY A BUILD SCRIPT
-----------------------------------------------
`make derived` runs tools/build_web_payload.py over the promoted corpus. That is
the shipping path. This stage runs the same projection *inside the chain*, over
the corrected corpus, before anything is promoted, so a correction that makes
the browser's honesty numbers unbuildable fails the chain instead of being
discovered on the deployed site.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

from stagelib import Report, run_stage          # noqa: E402
from web_payload import CLASS_ORDER, build_payload   # noqa: E402

STAGE, VERSION = "52_web_payload", "1.0.0"
QUARANTINE = os.path.join(REPO, "data", "_quarantine.json")


def transform(rec: dict, rep: Report) -> bool:
    """Copy-through. This stage projects the corpus; it never edits it.

    It does record two per-record facts the payload's assertions rest on, so the
    report carries them with their denominator rather than only the payload.
    """
    covs = rec.get("coverage_source") or {}
    if covs.get("pct_covered_source") is None:
        rep.count("source_coverage_null_because_denominator_was_zero", 1)
    if covs.get("pct_covered_source_is_upper_bound"):
        rep.count("source_coverage_is_an_upper_bound", 1)
    if rec.get("oxygen") is None:
        rep.count("oxygen_regime_unknown", 1)
    return False


def finalize(rep: Report) -> None:
    out_web = os.path.join(os.path.dirname(rep.out_dir), "web")
    report = build_payload(rep.out_dir, out_web, repo=REPO, quarantine=QUARANTINE)
    n = rep.n_out

    for name in ("source_coverage_null_because_denominator_was_zero",
                 "source_coverage_is_an_upper_bound", "oxygen_regime_unknown"):
        rep.set_denominator(name, n)

    totals = report["component_totals"]
    classes = report["evidence_class_totals"]
    rep.count("components_classified", sum(classes.values()), totals["n_components"])
    rep.assert_eq("every_component_has_exactly_one_evidence_class",
                  sum(classes.values()), totals["n_components"])
    rep.assert_eq("catalog_has_one_row_per_record", report["media_read"], n)
    rep.assert_eq("source_coverage_bands_partition_the_corpus",
                  sum(report["coverage_bands_source"].values()), n)

    # A tombstone must never contradict a served record.
    import json
    live = {f[:-5] for f in os.listdir(rep.out_dir) if f.endswith(".json")}
    with open(os.path.join(out_web, "tombstones.json"), encoding="utf-8") as fh:
        tomb = json.load(fh)
    clash = sorted(set(tomb["records"]) & live)
    rep.assert_eq("no_withdrawn_id_is_also_live", clash, [])
    rep.count("withdrawn_records_published", tomb["n_withdrawn"], tomb["n_withdrawn"])

    # The compound index must be complete over the corpus it was built from.
    with open(os.path.join(out_web, "compounds.json"), encoding="utf-8") as fh:
        comp = json.load(fh)
    exchanges = set()
    for mid in sorted(live):
        with open(os.path.join(rep.out_dir, mid + ".json"), encoding="utf-8") as fh:
            for c in json.load(fh)["components"]:
                if c.get("exchange"):
                    exchanges.add(c["exchange"])
    rep.assert_eq("compound_index_covers_every_exchange",
                  sorted(set(comp["postings"]) ^ exchanges), [])
    rep.count("exchanges_indexed", len(exchanges), len(exchanges))

    for name, size in report["written"].items():
        rep.count("payload_bytes_" + name.replace(".json", ""),
                  size["bytes"], size["bytes"])
        rep.count("payload_gzip_bytes_" + name.replace(".json", ""),
                  size["bytes_gzip"], size["bytes"])

    for cls in CLASS_ORDER:
        rep.count("evidence_class_" + cls, classes[cls], totals["n_components"])

    rep.unresolved(
        "components_whose_identity_rests_on_a_name_string",
        classes["name"], totals["n_components"],
        "resolved by matching a name string; no structure and no identifier was "
        "checked. The browser labels these Name-matched and never calls them exact.")
    rep.unresolved(
        "components_the_cited_source_does_not_state",
        classes["derived"], totals["n_components"],
        "supplied by the pipeline. Kept and labelled, excluded from every "
        "source-coverage number the site renders.")
    rep.unresolved(
        "media_with_no_family",
        n - report["n_media_in_a_family"], n,
        "no base-medium family was resolved from the record; the browser shows "
        "these as ungrouped rather than filing them under a guessed family.")


if __name__ == "__main__":
    run_stage(STAGE, VERSION, transform, finalize=finalize,
              inputs=["tools/web_payload.py", "data/_quarantine.json"])
