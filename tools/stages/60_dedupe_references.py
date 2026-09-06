#!/usr/bin/env python3
"""
Stage 60 — hold each repeated string once, and refer to it by key.

FINDINGS: SIZE-01

WHAT THIS FIXES
---------------
GitHub Pages publishes this repository's root and refuses a published site over
1 GiB. assets/media.js fetches data/media/<id>.json at runtime, so the corpus
cannot be unpublished. After the remediation the tracked tree measured
1,597.8 MiB against origin/main's 522.0 MiB — over the limit and unpushable.

A byte census over all 13,515 records and 665,582 components (the model
reproduces the on-disk size to within 0.02%) attributed the growth to repetition,
not to information:

    247.2 MiB  components[].target_xref       2,287 distinct blobs, 291x repeated
    242.8 MiB  components[].xref              byte-identical to target_xref in
                                              665,582 of 665,582 components (100.00%)
     89.8 MiB  components[].target_xref_note  ONE sentence, on 654,067 components
     71.2 MiB  components[].mapping_note      113 distinct strings, on 621,274
     21.1 MiB  components[].quantity_basis    == quantity.basis, 665,582 of 665,582
     11.8 MiB  usda_amount / usda_unit        == quantity.value / .unit,
                                              268,697 of 268,697, type-exact

`amount_basis` is left alone on purpose. It equals quantity.basis on all 268,697
components too, but it labels `amount_mmol_per_100g`, a different measurement; the
agreement is a property of this corpus, not of the schema. See tools/refs.py.

NOTHING IS DELETED
------------------
Every distinct cross-reference block and every distinct sentence is written once
into data/refs.json and referred to by key. The four quantity copies are dropped
because the value they held is still on the same component, inside `quantity`.
tools/refs.py:resolve_component() reconstructs the pre-stage component exactly,
and this stage asserts that round trip on every component it touches — not on a
sample. If a single component failed to round-trip, the stage exits non-zero and
promotes nothing.

WHAT IT DOES NOT DO
-------------------
It does not touch a measurement, a bound, a concentration, an identity, a tier or
a licence. It rewrites no prose: the sentences in data/refs.json are the verbatim
strings it removed. It does not shorten `concentration_block_reason`,
`amount_source` or `provenance.transforms`, which the same census scores at
37.2 / 14.9 / 31.6 MiB — those are left legible, and named in the report as the
headroom that remains if the site ever needs it.

  python3 tools/stages/60_dedupe_references.py --in <corpus> --out <corpus>
      [--refs PATH]   where to write refs.json (default: <out>/../refs.json)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import refs as R                                    # noqa: E402
from stagelib import run_stage, stamp, read_record, corpus_ids   # noqa: E402

STAGE = "60_dedupe_references"
VERSION = "1.0.0"

CHANGES = [
    "components[].mapping_note -> mapping_note_id",
    "components[].quantity_basis -> quantity.basis",
    "components[].target_xref -> xref_id",
    "components[].target_xref_note -> xref_note_id",
    "components[].usda_amount -> quantity.value",
    "components[].usda_unit -> quantity.unit",
    "components[].xref (deprecated alias) -> xref_id",
]

#: fields the census scores next, left in place on purpose. Reported, not applied.
REMAINING_HEADROOM_MIB = {
    "components[].concentration_block_reason": 37.2,
    "provenance.transforms": 31.6,
    "components[].amount_source": 14.9,
}


def main(argv=None) -> int:
    # The full stage CLI, declared here rather than deferred to stagelib, because
    # tools/stages/run_stages.py reads a stage's --help to decide which flags it can
    # be driven with. A stage whose --help does not name --in/--out is DISABLED by
    # the runner, silently as far as the chain is concerned.
    ap = argparse.ArgumentParser(
        prog=STAGE, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="in_dir", required=True,
                    help="input corpus directory (read-only)")
    ap.add_argument("--out", dest="out_dir", required=True,
                    help="output corpus directory (must not be data/media)")
    ap.add_argument("--report", dest="report",
                    help="path for the JSON report (default: <out>/../report.json)")
    ap.add_argument("--limit", type=int, default=None,
                    help="process only the first N ids (sample runs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and report, write no corpus")
    ap.add_argument("--refs", dest="refs_path",
                    help="where to write the reference table "
                         "(default: <out>/../refs.json)")
    known = ap.parse_args(argv)

    in_dir = os.path.abspath(known.in_dir)
    out_dir = os.path.abspath(known.out_dir)
    refs_path = os.path.abspath(
        known.refs_path or os.path.join(os.path.dirname(out_dir), R.REFS_FILENAME))

    # Pass 1. The key for a cross-reference block depends on how many distinct
    # blocks the whole corpus holds for that BiGG id, so it cannot be decided
    # record by record without producing keys that depend on iteration order.
    # Streamed off disk: the 1.4 GB corpus is never held in memory at once.
    ids = corpus_ids(in_dir, known.limit)
    tables = R.build_tables(
        read_record(os.path.join(in_dir, m + ".json")) for m in ids)
    key_of = tables["_key_of"]

    # A corpus that has already been through this stage carries no inline block to
    # move, so the scan above finds nothing and the tables come back empty. Writing
    # that over a good data/refs.json would silently unresolve 665,582 components —
    # which is precisely the class of silent failure this pipeline was audited for.
    # Re-running the stage on its own output is therefore an explicit no-op, and it
    # says so instead of quietly producing an empty table.
    already = tables["n_xrefs"] == 0 and tables["n_notes"] == 0
    if already:
        n_keyed = sum(1 for m in ids
                      for c in (read_record(os.path.join(in_dir, m + ".json"))
                                .get("components") or [])
                      if "xref_id" in c or "mapping_note_id" in c)
        if n_keyed:
            print("%-28s input is already deduplicated (%d keyed components); "
                  "copy-through, and data/refs.json is NOT rewritten"
                  % (STAGE, n_keyed))

    state = {"components": 0, "roundtrip_ok": 0, "roundtrip_checked": 0,
             "roundtrip_bad": [], "already_deduped": 0,
             "bytes_before": 0, "bytes_after": 0}

    def transform(rec, rep):
        changed = False
        for c in rec.get("components") or []:
            state["components"] += 1
            before = dict(c)
            if "xref_id" in c:
                state["already_deduped"] += 1
            n0 = len(R.canonical(before))
            rewritten = R.dedupe_component(c, key_of)
            if rewritten:
                changed = True
            state["bytes_before"] += n0
            state["bytes_after"] += len(R.canonical(c))
            # The whole justification for this stage is that it loses nothing.
            # That claim is checked on EVERY component it rewrites, not sampled.
            # A component this call did not touch has nothing to prove, and on a
            # re-run the tables are empty by design, so checking it would fail on
            # a key this call never wrote.
            if not rewritten:
                continue
            state["roundtrip_checked"] += 1
            diff = R.roundtrip_diff(before, R.resolve_component(c, tables, flat=True))
            if not diff:
                state["roundtrip_ok"] += 1
            elif len(state["roundtrip_bad"]) < 20:
                state["roundtrip_bad"].append(
                    {"medium": rec.get("id"), "component": before.get("name"),
                     "fields": diff[:8]})
        if changed:
            stamp(rec, STAGE, VERSION, CHANGES)
        return changed

    def finalize(rep):
        n = state["components"]
        rep.count("components_seen", n, of=n)
        rep.count("components_already_deduped", state["already_deduped"], of=n)
        rep.count("xref_blocks_distinct", tables["n_xrefs"], of=n)
        rep.count("notes_distinct", tables["n_notes"], of=n)
        rep.assert_eq("every_rewritten_component_round_trips",
                      state["roundtrip_ok"], state["roundtrip_checked"])
        rep.assert_eq("no_round_trip_failures", len(state["roundtrip_bad"]), 0)
        if state["roundtrip_bad"]:
            for b in state["roundtrip_bad"]:
                rep.example("round_trip_failures", b, cap=20)
        rep.count("component_bytes_before", state["bytes_before"])
        rep.count("component_bytes_after", state["bytes_after"])
        rep.count("component_bytes_saved_minified",
                  state["bytes_before"] - state["bytes_after"])
        if already:
            rep.count("refs_json_bytes", 0)
            rep.example("refs_json", "not rewritten: the input was already keyed")
            return
        rep.count("refs_json_bytes", R.write_refs(tables, refs_path))
        rep.example("refs_path", os.path.relpath(refs_path, REPO))
        rep.example("remaining_headroom_mib", REMAINING_HEADROOM_MIB)
        rep.unresolved(
            "fields_left_repeated", len(REMAINING_HEADROOM_MIB), 3,
            "concentration_block_reason (37.2 MiB), provenance.transforms (31.6 MiB) "
            "and amount_source (14.9 MiB) are still written out per component or per "
            "record. They are legible English and the site fits without touching "
            "them; this is the headroom that remains if it stops fitting.")

    # --refs is this stage's own flag; the rest is the shared runner's contract.
    inner = ["--in", in_dir, "--out", out_dir]
    if known.report:
        inner += ["--report", known.report]
    if known.limit is not None:
        inner += ["--limit", str(known.limit)]
    if known.dry_run:
        inner += ["--dry-run"]
    rc = run_stage(STAGE, VERSION, transform, finalize=finalize,
                   inputs=["corpus"], argv=inner)
    if rc == 0 and not already:
        print("%-28s refs -> %s (%d xref blocks, %d notes, %.1f KB)"
              % (STAGE, os.path.relpath(refs_path, REPO), tables["n_xrefs"],
                 tables["n_notes"], os.path.getsize(refs_path) / 1024.0))
    if rc == 0:
        print("%-28s component payload %.1f -> %.1f MiB minified (-%.1f%%)"
              % (STAGE, state["bytes_before"] / 1048576.0,
                 state["bytes_after"] / 1048576.0,
                 100.0 * (state["bytes_before"] - state["bytes_after"])
                 / max(state["bytes_before"], 1)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
