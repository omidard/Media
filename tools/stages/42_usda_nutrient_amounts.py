#!/usr/bin/env python3
"""Both USDA measurements are published, and the chosen one is chosen by chemistry.

FINDINGS: USDA-01

THE DEFECT
----------
tools/build_usda_media_v2.py assigns `comps[ex] = {...}` keyed on the exchange
while looping over a food's nutrients, and five BiGG ids in its NMAP_RAW are
reachable from two distinct USDA nutrient names (arachd, cys__L, lnlc, lnlnca,
ocdcea). When a food reports both, the second one encountered overwrites the
first. No detection, no accumulation, no record of the loser.

2,025 collisions across 1,918 foods; 1,930 reach a shipped record and 1,434 of
those disagree by more than 1%, up to a factor of 17.8 (usda_172353, EX_ocdcea_e:
"MUFA 18:1 c" 0.01 g against "MUFA 18:1" 0.178 g). Replaying both source zips
confirms last-wins exactly: of the 1,930 shipped values, 1,930 equal the LAST
nutrient in the source array and 0 equal a discarded one.

The surviving value is the broad class on 962 of them and the cis subset on 968,
so the amount column is not comparable between two USDA records, and the discarded
measurement exists nowhere in the shipped data.

WHAT THIS STAGE DOES
--------------------
Reads tools/usda_nutrient_collisions.json -- every measurement the source reports,
recovered from the source zips by tools/build_usda_nutrient_collisions.py -- and
for each colliding component:

  * sets `usda_amount` / `usda_unit` to the measurement chosen by CHEMISTRY
    rather than by array order. The two names are not two measurements of one
    quantity: "MUFA 18:1" is total C18:1 including trans, "MUFA 18:1 c" is the cis
    subset, and the BiGG target ocdcea IS cis-9-octadecenoate. The preference
    table and its reasons are committed beside the data.
  * records `usda_amount_chose_by` (the named rule) and `usda_amount_why`;
  * records `usda_amount_alternatives`: every discarded measurement with its own
    nutrient name, value and unit, so nothing is lost and no reader has to take
    the choice on trust.

It runs BEFORE 50_load_concentrations, which is what projects `usda_amount` into
the reader-facing `quantity` block and derives `amount_mmol_per_100g` from it. So
the correction lands once, at the amount, and every number downstream of it is
recomputed rather than patched. 50_load_concentrations carries the three new
fields into `quantity` so a reader and the parquet see the alternatives beside the
value they qualify.

`source_name` keeps both names ("MUFA 18:1 c|MUFA 18:1"): it honestly records that
two nutrients were collapsed, and rewriting it would hide the collision that this
stage exists to expose.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

from stagelib import StageError, main_guard, stamp                # noqa: E402

STAGE, VERSION = "42_usda_nutrient_amounts", "1.0.0"

TABLE = os.path.join(TOOLS, "usda_nutrient_collisions.json")
_COLLISIONS = None


def collisions():
    global _COLLISIONS
    if _COLLISIONS is None:
        if not os.path.exists(TABLE):
            raise StageError(
                "tools/usda_nutrient_collisions.json is missing. It holds both "
                "measurements for every USDA nutrient pair that collapses onto one "
                "exchange; without it this stage would silently correct nothing. "
                "Build it: python3 tools/build_usda_nutrient_collisions.py")
        with open(TABLE, encoding="utf-8") as fh:
            payload = json.load(fh)
        _COLLISIONS = payload["collisions"]
    return _COLLISIONS


def transform(rec: dict, rep) -> bool:
    per_medium = collisions().get(rec.get("id"))
    if not per_medium:
        return False
    changed = []
    for comp in rec.get("components") or []:
        entry = per_medium.get(comp.get("exchange"))
        if not entry:
            continue
        if comp.get("usda_amount") is None:
            rep.count("colliding_component_carries_no_usda_amount")
            continue
        rows = entry["measurements"]
        chosen = next((r for r in rows if r["source_name"] == entry["chosen"]), None)
        if chosen is None:
            raise StageError("%s/%s: the chosen name %r is not among the recorded "
                             "measurements" % (rec["id"], comp["exchange"],
                                               entry["chosen"]))
        before = comp["usda_amount"]
        others = [r for r in rows if r is not chosen]
        alternatives = [
            {"source_name": r["source_name"], "value": r["value"], "unit": r["unit"],
             "applied": False} for r in others]
        # Idempotent by comparison, not by assignment: a stage that rewrites the
        # same bytes still reports a change, and the runner's re-run check would
        # fail on it.
        if (before == chosen["value"]
                and comp.get("usda_amount_alternatives") == alternatives
                and comp.get("usda_amount_chose_by") == entry["chose_by"]):
            continue
        comp["usda_amount"] = chosen["value"]
        if chosen.get("unit"):
            comp["usda_unit"] = chosen["unit"]
        comp["usda_amount_chose_by"] = entry["chose_by"]
        comp["usda_amount_why"] = entry["why"]
        comp["usda_amount_alternatives"] = alternatives
        rep.count("colliding_amount_resolved")
        if before != chosen["value"]:
            rep.count("published_amount_changed")
            if before and abs(chosen["value"] - before) > 0.01 * abs(before):
                rep.count("published_amount_changed_by_more_than_one_percent")
        changed.append("components[].usda_amount_alternatives")
    if not changed:
        return False
    stamp(rec, STAGE, VERSION, changed)
    return True


def finalize(rep):
    c = rep.counters

    def got(name):
        return c.get(name, {"n": 0})["n"]

    rep.assert_eq("every_colliding_component_carries_a_usda_amount",
                  got("colliding_component_carries_no_usda_amount"), 0)
    rep.count("records_seen", 0, rep.n_in)
    rep.unresolved(
        "cystine_is_still_mapped_to_the_monomer", 0, rep.n_in,
        "Cystine is the disulfide dimer (cysi__L) and the map points it at cys__L, "
        "the monomer. No USDA food reports both Cystine and Cysteine, so the pair "
        "never collided and no amount was ever discarded there; the mis-target is a "
        "separate defect and this stage does not touch it.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize, inputs=[TABLE])
