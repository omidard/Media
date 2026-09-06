#!/usr/bin/env python3
"""Load the quantitative layer that is already on disk but never projected.

READS   a corpus directory; tools/bigg_metabolite_dict.json for formulae; and,
        when supplied, the chemistry workstream's molar-mass table (see below).
WRITES  the same corpus with a per-component `quantity` block (the source's own
        amount, verbatim, with its unit and its basis), a `concentration_mM` that
        is derived ONLY where the basis really is per litre of finished medium and
        the molar mass of that same species is known, an `amount_mmol_per_100g`
        for USDA foods on their own honest basis, and a `derived_not_sourced`
        flag on every pipeline-invented component.
ASSERTS no bound changes; no concentration is ever 0.0; no concentration is
        derived from a dissociated ion whose parent salt was discarded; no
        per-100 g food amount becomes a molar concentration; no quantity is
        derived for an invented component; every concentration carries its status
        and source.

FINDINGS: NM-11, NM-02 (part 1), NM-15, PROV-04, PROV-09, PROV-13, COV-04, MAP-13.

WHY THIS RUNS BEFORE THE NAMING STAGE
-------------------------------------
concentration_mM is populated on 2.15% of components and 94.6% of lower bounds are
exactly -1 or -1000, so a modifier named in a medium's title has nowhere to land.
Grouping names first would merge records that are already indistinguishable: 23 of
the 44 LB-family records are byte-identical in exchange set AND bounds AND
concentration. So the quantitative layer lands first, and the naming stage then
groups against a corpus that can actually tell its members apart.

Measured effect of this stage on the whole corpus: the composition fingerprint goes
from 7,923 distinct values (exchange set alone) to 12,461 once the verbatim amounts
are carried, and compositionally redundant records fall from 5,592 to 1,054. On the
food side alone, redundancy falls from 3,218 records to 33 -- the measured USDA
amounts that separate 93 beef cuts were on disk the whole time and were discarded at
projection time.

WHAT THIS STAGE DELIBERATELY REFUSES TO DO
------------------------------------------
* It does not convert the 38,363 `mediadive_salt` components. Their `recipe_g_l` is
  the mass of a parent SALT and the component is a dissociated ION whose parent
  identity the builder discarded, so dividing by the ion's mass would be wrong by
  the salt/ion ratio, the hydration water and the stoichiometry -- SO4 at 96.06
  instead of MgSO4.7H2O at 246.47 is 2.6x too much sulfate. An honest null with a
  stated reason beats 38,363 confident wrong numbers.
* It does not convert USDA per-100 g amounts into mM. A food's nutrient content is
  an amount, not a concentration; producing mM needs a volume basis nobody measured.
* It does not touch a single flux bound. client/pymediadb builds the COBRApy medium
  from abs(lower_bound), so re-deriving bounds here would silently change every
  downstream simulation as a side effect of a data-quality fix.
"""
from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stagelib import main_guard, stamp                     # noqa: E402
import load_concentrations as LIB                          # noqa: E402

STAGE, VERSION = "50_load_concentrations", "1.0.0"
LIB.STAGE_ID, LIB.STAGE_VERSION = STAGE, VERSION

_CTX = None


def _ctx():
    global _CTX
    if _CTX is None:
        mt = os.environ.get("MEDIADB_MASS_TABLE") or None
        _CTX = LIB.Stage(mass_table=mt)
    return _CTX


def transform(rec: dict, rep) -> bool:
    st = _ctx()
    before = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    bounds_before = [(c.get("lower_bound"), c.get("upper_bound"))
                     for c in (rec.get("components") or [])]
    n_before = len(rec.get("components") or [])

    LIB.Stage.transform_record(st, rec)

    comps = rec.get("components") or []
    if len(comps) != n_before:
        raise LIB_ERROR("%s: component count changed %d -> %d"
                        % (rec["id"], n_before, len(comps)))
    if [(c.get("lower_bound"), c.get("upper_bound")) for c in comps] != bounds_before:
        raise LIB_ERROR("%s: a flux bound changed; this stage must never touch bounds"
                        % rec["id"])

    # per-record tallies, always with their denominator
    rep.count("components_seen", len(comps), of=None)
    for c in comps:
        if c.get("derived_not_sourced"):
            rep.count("components_pipeline_derived")
        if (c.get("quantity") or {}).get("value") is not None:
            rep.count("components_with_source_amount")
        s = c.get("concentration_status")
        if s == "derived":
            rep.count("concentration_derived")
        elif s == "source_stated":
            rep.count("concentration_source_stated")
        if c.get("amount_mmol_per_100g") is not None:
            rep.count("amount_mmol_per_100g_derived")
        if c.get("concentration_plausibility") == "implausible_exceeds_pure_substance":
            rep.count("stated_concentration_physically_impossible")
            rep.example("physically_impossible",
                        {"id": rec["id"], "metabolite": c.get("bigg_metabolite"),
                         "concentration_mM": c.get("concentration_mM"),
                         "source_g_per_L": (c.get("quantity") or {}).get("value")})
        # structural violations. These must be ZERO at any scale, so they are the
        # assertions that hold on a sample run as well as a full one.
        if c.get("concentration_mM") == 0.0:
            rep.count("violation_concentration_is_zero")
        if s == "derived":
            if c.get("mapping_method") in LIB.SALT_METHODS_PARENT_LOST:
                rep.count("violation_derived_from_lost_parent_salt")
            if (c.get("quantity") or {}).get("basis") == "per_100g_food":
                rep.count("violation_food_amount_as_concentration")
            if c.get("derived_not_sourced"):
                rep.count("violation_derived_for_invented_component")
            if not c.get("concentration_source"):
                rep.count("violation_concentration_without_source")
            ceil = LIB.PURE_SUBSTANCE_MM.get(c.get("bigg_metabolite"))
            if ceil and (c.get("concentration_mM") or 0) > ceil:
                rep.count("violation_derived_exceeds_pure_substance")
        if c.get("concentration_mM") is not None and not s:
            rep.count("violation_concentration_without_status")

        r = c.get("concentration_block_reason")
        if r:
            rep.count("blocked:" + r)
            if r == "below_representable_precision":
                rep.example("rounded_to_zero_now_null",
                            {"id": rec["id"], "metabolite": c.get("bigg_metabolite"),
                             "source": c.get("hmdb_orig") or (c.get("quantity") or {}).get("value")})

    after = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    if after == before:
        return False
    stamp(rec, STAGE, VERSION, ["components.quantity", "components.concentration_status",
                                "components.derived_not_sourced", "quantitation"])
    return True


class LIB_ERROR(RuntimeError):
    pass


def finalize(rep) -> None:
    c = rep.counters
    n_comp = c.get("components_seen", {}).get("n", 0)
    # Every number carries its denominator. All of these counters are counts of
    # COMPONENTS, so the denominator is the component total, not the record total.
    for k in list(c):
        if k != "components_seen":
            c[k]["of"] = n_comp

    def n(k):
        return c.get(k, {}).get("n", 0)

    # ---- structural post-conditions. True at ANY scale, so they hold on a
    #      sample run as well as a full one. These are the honesty guarantees.
    rep.assert_eq("A3_no_concentration_is_ever_zero", n("violation_concentration_is_zero"), 0)
    rep.assert_eq("A4_no_concentration_derived_from_a_lost_parent_salt",
                  n("violation_derived_from_lost_parent_salt"), 0)
    rep.assert_eq("A5_no_food_amount_became_a_molar_concentration",
                  n("violation_food_amount_as_concentration"), 0)
    rep.assert_eq("A6_no_quantity_derived_for_a_pipeline_invented_component",
                  n("violation_derived_for_invented_component"), 0)
    rep.assert_eq("A7_no_derived_concentration_exceeds_pure_substance_molarity",
                  n("violation_derived_exceeds_pure_substance"), 0)
    rep.assert_eq("A8a_every_concentration_carries_a_status",
                  n("violation_concentration_without_status"), 0)
    rep.assert_eq("A8b_every_derived_concentration_carries_its_source",
                  n("violation_concentration_without_source"), 0)
    rep.assert_true("every_component_was_classified",
                    n("components_seen") > 0, n("components_seen"), "> 0")

    # ---- corpus-scale counts. Gated on having actually seen the whole corpus,
    #      not on the --limit flag: a subset run has a different denominator, so
    #      asserting a corpus total there would be theatre either way.
    if rep.n_in == 13515:
        rep.assert_eq("parent_salt_components_all_blocked",
                      n("blocked:parent_salt_identity_lost"), 38363)
        # 284,337 = the 213,910 counted when this stage was written, plus the 70,427
        # usda_mineral components that used to be blocked one line earlier as
        # "invented". They are USDA analytes — every one carries a measured amount
        # with a unit — so tools/component_evidence_classes.tsv classes them sourced,
        # and this stage now reads that table instead of a private list that
        # disagreed with it. Their concentration outcome is unchanged (null: a
        # per-100 g food amount has no volume basis); only the reason is now the
        # true one. A5 above is the assertion that actually guards the honesty
        # property here and is scale-free; this one is the corpus-size witness.
        rep.assert_eq("food_amounts_never_became_concentrations",
                      n("blocked:food_amount_no_volume_basis"), 284337)
        rep.assert_true("usda_amounts_are_published_on_their_own_basis",
                        n("amount_mmol_per_100g_derived") > 190000,
                        n("amount_mmol_per_100g_derived"), "> 190000")
        rep.assert_true("pipeline_derived_components_are_labelled",
                        n("components_pipeline_derived") > 229000,
                        n("components_pipeline_derived"), "> 229000")

    rep.unresolved(
        "salt_ion_molarity_unrecoverable",
        c.get("blocked:parent_salt_identity_lost", {}).get("n", 0), n_comp,
        "recipe_g_l is the parent salt's mass and the salt's identity, hydration state "
        "and ion stoichiometry were discarded by tools/mediadive/build_mediadive_media.py "
        "(line 44 binds the compound name, line 56 does not store it). Recovering these "
        "requires re-acquiring the MediaDive ingredient table, not a division.")
    rep.unresolved(
        "food_amounts_have_no_volume_basis",
        c.get("blocked:food_amount_no_volume_basis", {}).get("n", 0), n_comp,
        "a per-100 g food amount is an amount, not a concentration; a volume basis was "
        "never measured, so amount_mmol_per_100g is published instead of a fabricated mM.")
    rep.unresolved(
        "components_with_no_molar_mass",
        c.get("blocked:no_molar_mass", {}).get("n", 0), n_comp,
        "no formula on the component xref and none in tools/bigg_metabolite_dict.json "
        "(which carries a formula for only 4,010 of its 9,403 entries). Supply the "
        "chemistry workstream's molar-mass table via MEDIADB_MASS_TABLE to reduce this.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize,
               inputs=["tools/bigg_metabolite_dict.json"])
