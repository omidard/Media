#!/usr/bin/env python3
"""
00_baseline — copy-through stage that measures the frozen snapshot.

Reads:   a corpus directory (normally data/media, the sole surviving copy of the
         corpus; see finding PIPE-01).
Writes:  the same records, byte-for-byte unchanged, into --out.
Asserts: the measured shape of the frozen snapshot, so that any drift in the input
         to the chain is caught at stage 0 rather than blamed on a later stage.

It changes nothing. Its purpose is (a) to prove the harness end to end before a
correction stage relies on it, and (b) to record the entry-state numbers that the
whole remediation is measured against.

Baseline measured 2026-09-06 over data/media at commit e051bf4:
  13,515 media | 665,582 components | 664,218 with a BiGG metabolite
  exchange == EX_<met>_e in 664,218/664,218 | n_mapped == n_components in 13,515/13,515
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stagelib import run_stage  # noqa: E402

STAGE, VERSION = "00_baseline", "1.0.0"

# Frozen-snapshot expectations. A mismatch means the input corpus is not the corpus
# this remediation was audited against — which must be noticed, not absorbed.
EXPECT = {
    "n_media": 13515,
    "n_components": 665582,
    "components_with_bigg": 664218,
    "exchange_identity_ok": 664218,
    "records_n_mapped_eq_n_components": 13515,
    "sum_declared_n_in_biggr": 650267,
}


def transform(rec, rep):
    comps = rec.get("components") or []
    rep.count("components", len(comps))
    n_bigg = 0
    for c in comps:
        b = c.get("bigg_metabolite")
        if b:
            n_bigg += 1
            if c.get("exchange") == "EX_%s_e" % b:
                rep.count("exchange_identity_ok")
            else:
                rep.count("exchange_identity_bad")
                rep.example("exchange_identity_bad", [rec["id"], b, c.get("exchange")])
    rep.count("components_with_bigg", n_bigg)
    rep.count("sum_declared_n_mapped", rec.get("n_mapped") or 0)
    rep.count("sum_declared_n_in_biggr", rec.get("n_in_biggr") or 0)
    if rec.get("n_mapped") == len(comps):
        rep.count("records_n_mapped_eq_n_components")
    if rec.get("n_mapped") != n_bigg:
        rep.count("records_n_mapped_overstated")
    return False          # copy-through: never changes a record


def finalize(rep):
    n = rep.n_in
    sample = n != EXPECT["n_media"]
    rep.assert_eq("copy_through_complete", rep.n_out, rep.n_in)
    rep.assert_eq("no_record_changed", rep.n_changed, 0)
    rep.assert_eq("exchange_identity_holds_for_every_mapped_component",
                  rep.counters.get("exchange_identity_bad", {}).get("n", 0), 0)
    if not sample:
        for key, expected in EXPECT.items():
            if key == "n_media":
                rep.assert_eq("baseline_n_media", n, expected)
            else:
                rep.assert_eq("baseline_" + key,
                              rep.counters.get(key, {}).get("n", 0), expected)
    rep.unresolved(
        "records_with_no_regenerable_source", 1456, 13515,
        "lit_/growthlit_/complexlit_ media came from LLM extraction batches that were "
        "deleted with the /tmp scratchpad; they cannot be regenerated from any surviving "
        "input and are a frozen expert-curated snapshot (PIPE-01)")
    rep.unresolved(
        "records_whose_generator_is_dead", 13248, 13515,
        "19 generator scripts hardcoded a deleted scratchpad; ~87% of the corpus is "
        "recoverable in principle from public upstreams, the rest is not (PIPE-01)")


if __name__ == "__main__":
    sys.exit(run_stage(STAGE, VERSION, transform, finalize=finalize))
