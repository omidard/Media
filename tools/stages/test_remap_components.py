#!/usr/bin/env python3
"""Regression tests for the corrected metabolite mapper and the remap stage.

Run:  python3 tools/stages/test_remap_components.py

Every test below encodes a defect the audit PROVED, so a future edit that
re-introduces it fails loudly instead of shipping a plausible-looking wrong answer.
The stereo tests in particular assert BOTH directions in one test, because the
cheapest way to "fix" an enantiomer bug is to invert it onto a larger population
(audit MAP-01, risk_if_fixed_naively).
"""
import json, os, sys, tempfile, collections

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import chem_identity as CHEM
from map_metabolite import Mapper
from evidence_tiers import TIER_ORDER, tier_for_method, METHOD_TIERS
import remap_components as RC

FAILS = []


def check(cond, label, detail=""):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}   {detail}")
        FAILS.append(label)


def bid(m, name, **kw):
    r = m.map(name=name, **kw)
    return None if r is None else r.get("bigg_metabolite")


def tier(m, name, **kw):
    r = m.map(name=name, **kw)
    return None if r is None else r.get("evidence_tier")


def main():
    m = Mapper()

    print("\n[MAP-01] CO2 vs Co2+ -- case and charge are the only discriminators")
    # BOTH directions in one test: the naive fix (alias table before the name index)
    # converts 11,621 genuine cobalt rows into carbon dioxide.
    check(bid(m, "CO2") == "co2", "CO2 -> co2", bid(m, "CO2"))
    check(bid(m, "CO2 (carbon dioxide, gas)") == "co2", "CO2 (carbon dioxide, gas) -> co2")
    check(bid(m, "Co2+") == "cobalt2", "Co2+ -> cobalt2", bid(m, "Co2+"))
    check(bid(m, "Co2+ (from CoCl2)") == "cobalt2", "Co2+ (from CoCl2) -> cobalt2")
    check(bid(m, "carbon dioxide") == "co2", "carbon dioxide -> co2")
    check(bid(m, "CO") == "co", "CO -> co (carbon monoxide)")
    check(bid(m, "NO3-") == "no3", "NO3- -> no3: the charge is stripped, the subscript is not",
          bid(m, "NO3-"))
    check(bid(m, "Nitrate (NO3-)") == "no3", "Nitrate (NO3-) -> no3, not nitric oxide",
          bid(m, "Nitrate (NO3-)"))
    check(bid(m, "SO42-") == "so4", "SO42- -> so4", bid(m, "SO42-"))
    check(CHEM.formula_elements("CO2") == {"C", "O"}, "formula_elements('CO2') == {C,O}")
    check(CHEM.formula_elements("Co") == {"Co"}, "formula_elements('Co') == {Co}")

    print("\n[MAP-03] D/L stereochemistry survives lookup, in both directions")
    pairs = [("Serine", "ser__L", "ser__D"), ("Glutamate", "glu__L", "glu__D"),
             ("Lactate", "lac__L", "lac__D"), ("Malate", "mal__L", "mal__D"),
             ("Alanine", "ala__L", "ala__D"), ("Ornithine", "orn__L", "orn__D")]
    for base, lid, did in pairs:
        gl, gd = bid(m, "L-" + base), bid(m, "D-" + base)
        check(gl == lid and gd == did, f"L-/D-{base} -> {lid}/{did}", f"got {gl}/{gd}")
        check(gl != gd, f"L-{base} and D-{base} do not collapse to one id")
    check(bid(m, "sodium L-lactate") == "lac__L",
          "sodium L-lactate -> lac__L (cation stripped, stereo kept)", bid(m, "sodium L-lactate"))

    print("\n[MAP-03 risk 2] the alias lane must not regress when stereo is enforced")
    for nm, want in [("L-Glutamic acid", "glu__L"), ("L-malic acid", "mal__L"),
                     ("L-ascorbic acid", "ascb__L"), ("L-Aspartic acid", "asp__L"),
                     ("L-lactic acid", "lac__L"), ("L-glycine", "gly"),
                     ("DL-6,8-thioctic acid", "lipoate")]:
        check(bid(m, nm) == want, f"{nm} -> {want}", bid(m, nm))

    print("\n[doctrine] absent is null, never a guess")
    check(bid(m, "L-Glucose") is None, "L-Glucose refused (BiGG has no L-glucose)")
    check(bid(m, "DL-Alanine") is None, "DL-Alanine refused (a racemate is not one metabolite)")
    check(bid(m, "Chromium") is None, "Chromium refused (BiGG has only Cr(VI) chromate)")
    r = m.map(name="DL-Alanine", strict=True)
    check(r["evidence_tier"] == "unmapped" and r["refusal_kind"] == "racemate",
          "a refusal states its kind", r.get("refusal_kind"))

    print("\n[MAP-02 / MAP-04] evidence tiers and match keys are never overstated")
    r = m.map(name="D-Glucose", inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N")
    check(r["evidence_tier"] == "structural_xref", "InChIKey hit is structural_xref")
    check(r["match_key"] == "WQZGKKKJIJFFOK-GASJEMHNSA-N", "match_key is the SOURCE identifier")
    check(r["source_xref"] == {"inchikey": "WQZGKKKJIJFFOK-GASJEMHNSA-N"}, "source_xref recorded")
    r = m.map(name="L-Serine")
    check(r["match_key"] is None, "a name match carries NO match_key")
    check(r["matched_name"] == "L-Serine", "the matched name string is recorded separately")
    check(r["source_xref"] is None, "source_xref is None when the source gave no identifier")
    check(r["source_name"] == "L-Serine", "the source string is preserved verbatim")
    check(r["target_xref"] == r["xref"], "xref is retained as a deprecated alias of target_xref")
    # the proven case: a component named L-serine must not carry D-serine's InChIKey
    check(r["target_xref"].get("inchikey") == "MTCFGRXMJLQNBG-REOHCLBHSA-N",
          "L-Serine carries L-serine's InChIKey, not D-serine's",
          r["target_xref"].get("inchikey"))

    print("\n[MAP-04] a supplied identifier that misses is recorded as a miss")
    r = m.map(name="L-serine", inchikey="ZZZZZZZZZZZZZZ-ZZZZZZZZZZ-Z")
    check("xref_miss" in (r.get("mapping_note") or ""),
          "an unindexed source InChIKey is reported, not silently overwritten")
    check(r["match_key"] is None, "a name fallback does not inherit the identifier's authority")

    print("\n[honesty cap] a chemistry-free target cannot be certified exact")
    for nm in ["Cholesterol", "Vitamin B-12", "Cystine", "MOPS"]:
        r = m.map(name=nm)
        check(r and r["evidence_tier"] != "exact_name",
              f"{nm} is not exact_name (its target has no InChIKey and no formula)",
              r and r["evidence_tier"])

    print("\n[MAP-12] a reactome-absent id is replaced only when chemistry proves identity")
    check(bid(m, "isovaleric acid") == "ival",
          "3mb (no formula, not in BiGGr) -> ival (same InChIKey, in BiGGr)")
    check(bid(m, "Cholesterol") == "choles",
          "choles is NOT migrated: it has no InChIKey, so nothing proves the identity")

    print("\n[chain length] gamma- vs dihomo-gamma-linolenic acid are two carbons apart")
    check(bid(m, "gamma-linolenic acid") == "lnlncg", "gamma-linolenic acid -> lnlncg (C18:3 n-6)",
          bid(m, "gamma-linolenic acid"))
    check(bid(m, "dihomo-gamma-linolenic acid") == "dlnlcg",
          "dihomo-gamma-linolenic acid -> dlnlcg (C20:3 n-6)")
    check(bid(m, "alpha-linolenic acid") == "lnlnca", "alpha-linolenic acid -> lnlnca (C18:3 n-3)")

    print("\n[MAP-08] a parenthetical that carries the specific identity wins")
    check(bid(m, "Vitamin K (Menaquinone-4)") == "mqn4",
          "Vitamin K (Menaquinone-4) -> mqn4, not phylloquinone",
          bid(m, "Vitamin K (Menaquinone-4)"))

    print("\n[MAP-14] salt precleaning still resolves, and stereo is not lost with it")
    check(bid(m, "Calcium D-pantothenate") == "pnto__R", "Calcium D-pantothenate -> pnto__R")
    check(bid(m, "Thiamine HCl (vitamin B1)") == "thm", "Thiamine HCl (vitamin B1) -> thm")

    print("\n[tier vocabulary] every shipped mapping_method has an honest tier")
    for meth, (t, _, _) in METHOD_TIERS.items():
        if t not in TIER_ORDER:
            check(False, f"method {meth} maps to unknown tier {t}")
    check(all(tier_for_method(x)[0] in TIER_ORDER for x in ["", "made_up_method"]),
          "an unrecognised method falls to a valid tier, not a crash")
    check(tier_for_method("made_up_method")[0] == "fuzzy_name",
          "an unrecognised method gets the FLOOR tier, never the ceiling")

    print("\n[stage] corrections table loads and every row is justified")
    rules = RC.load_corrections()
    check(len(rules) >= 25, f"{len(rules)} correction rows loaded")
    check(all(r["chemistry"].strip() for r in rules), "every row carries a chemical justification")
    ids = [r["correction_id"] for r in rules]
    check(len(ids) == len(set(ids)), "correction ids are unique")

    print("\n[stage] the documented fixes, end to end on synthetic media")
    stage = RC.Stage(corrections=rules, mapper=m)
    med = {
        "id": "test_medium", "components": [
            # MAP-01: CO2 stamped as cobalt
            {"name": "CO2 (carbon dioxide, gas)", "bigg_metabolite": "cobalt2",
             "exchange": "EX_cobalt2_e", "lower_bound": -1000.0, "in_biggr": True,
             "xref": {"inchikey": "XLJKHNWPARRRJB-UHFFFAOYSA-N", "formula": "Co"},
             "mapping_method": "name_remap", "mapping_confidence": "inferred"},
            # a genuine cobalt row that must NOT move
            {"name": "Co2+", "bigg_metabolite": "cobalt2", "exchange": "EX_cobalt2_e",
             "lower_bound": -1000.0, "in_biggr": True,
             "xref": {"inchikey": "XLJKHNWPARRRJB-UHFFFAOYSA-N", "formula": "Co"},
             "mapping_method": "mediadive_salt", "mapping_confidence": "convention"},
            # MAP-03: L-named component delivering the D enantiomer
            {"name": "L-serine", "bigg_metabolite": "ser__D", "exchange": "EX_ser__D_e",
             "lower_bound": -1.0, "in_biggr": True,
             "xref": {"inchikey": "MTCFGRXMJLQNBG-UWTATZPHSA-N", "formula": "C3H7NO3"},
             "mapping_method": "name_remap", "mapping_confidence": "inferred"},
            # MAP-02/COV-01: a hand-typed USDA table row stamped "exact"
            {"name": "L-Cysteine", "bigg_metabolite": "cys__L", "exchange": "EX_cys__L_e",
             "lower_bound": -1.0, "in_biggr": True, "usda_amount": 0.1, "usda_unit": "g",
             "xref": {"inchikey": "XUJNEKJLAYXESH-REOHCLBHSA-N", "formula": "C3H7NO2S"},
             "mapping_method": "usda_nutrient", "mapping_confidence": "exact"},
            # MAP-05: an element assay given an oxyanion, stamped "exact"
            {"name": "Selenite", "bigg_metabolite": "slnt", "exchange": "EX_slnt_e",
             "lower_bound": -1000.0, "in_biggr": True,
             "xref": {"inchikey": "MCAHWIHFGHIESP-UHFFFAOYSA-L", "formula": "O3Se"},
             "mapping_method": "usda_mineral", "mapping_confidence": "exact"},
            # MAP-10: an undefined hydrolysate given a nitrate uptake
            {"name": "Proteose peptone (No. 3)", "bigg_metabolite": "no3",
             "exchange": "EX_no3_e", "lower_bound": -1.0, "in_biggr": True,
             "xref": {"formula": "NO3"},
             "mapping_method": "name_alias_remap", "mapping_confidence": "inferred"},
            # MAP-06/PROV-07: a pipeline-invented component
            {"name": "L-Alanine", "bigg_metabolite": "ala__L", "exchange": "EX_ala__L_e",
             "lower_bound": -1.0, "in_biggr": True, "xref": {"formula": "C3H7NO2"},
             "mapping_method": "hydrolysate_approximation", "mapping_confidence": "convention"},
            # SCHEMA-04: a pre-2018 BiGG id flagged in_biggr true
            {"name": "D-Glucose", "bigg_metabolite": "glc_D", "exchange": "EX_glc_D_e",
             "lower_bound": -10.0, "in_biggr": True, "xref": {},
             "mapping_method": "curated", "mapping_confidence": "high"},
        ]}
    out = stage.transform_medium(med)
    c = out["components"]

    check(c[0]["bigg_metabolite"] == "co2" and c[0]["exchange"] == "EX_co2_e",
          "CO2 component retargeted cobalt2 -> co2", c[0]["bigg_metabolite"])
    check(c[0]["target_xref"].get("formula") == "CO2",
          "and its cross-references now describe carbon dioxide", c[0]["target_xref"].get("formula"))
    check(c[0]["evidence_tier"] == "curated_mapping", "at tier curated_mapping")
    check(c[0]["name"] == "CO2 (carbon dioxide, gas)" and c[0]["target_name"] == "CO2 CO2",
          "and the SOURCE's own compound string survives the retarget", c[0]["name"])
    check(c[1]["bigg_metabolite"] == "cobalt2", "the genuine Co2+ row is untouched")
    check(c[2]["bigg_metabolite"] == "ser__L" and c[2]["exchange"] == "EX_ser__L_e",
          "L-serine corrected ser__D -> ser__L", c[2]["bigg_metabolite"])
    check(c[2]["target_xref"].get("inchikey") == "MTCFGRXMJLQNBG-REOHCLBHSA-N",
          "and its InChIKey now describes L-serine")
    check(c[2]["name"] == "L-serine", "and the source string survives the stereo correction")
    check(c[2].get("flux_consequential") is True, "flagged flux-consequential")
    check(c[3]["mapping_confidence"] != "exact" and c[3]["evidence_tier"] == "name_table",
          "the USDA table row is no longer 'exact'", c[3]["mapping_confidence"])
    check(c[3].get("source_name_candidates") == ["Cystine", "Cysteine"],
          "and both possible source nutrients are recorded, since the source was destroyed",
          c[3].get("source_name_candidates"))
    check(c[4]["evidence_tier"] == "class_proxy" and c[4].get("proxy_for") == ["slnt"],
          "the selenium assay is a declared species proxy", c[4]["evidence_tier"])
    check(c[5]["bigg_metabolite"] is None and c[5]["exchange"] is None
          and c[5]["evidence_tier"] == "unmappable_mixture",
          "proteose peptone no longer has a nitrate uptake", c[5]["evidence_tier"])
    check(c[6]["evidence_tier"] == "derived_component" and c[6]["source_observed"] is False,
          "the invented component is kept, labelled, and excluded from coverage")
    check(c[7]["bigg_metabolite"] == "glc__D" and c[7]["legacy_bigg_metabolite"] == "glc_D",
          "the legacy BiGG id is migrated and the published id retained", c[7].get("bigg_metabolite"))
    check(out["n_observed"] == 7 and out["n_derived"] == 1,
          "coverage arithmetic separates observed from derived",
          (out["n_observed"], out["n_derived"]))
    check(out["pct_sourced_components_with_bigg_id"] == round(100 * 6 / 7, 2),
          "pct_sourced_components_with_bigg_id excludes the mixture that has no "
          "exchange", out["pct_sourced_components_with_bigg_id"])

    print("\n[stage] assertions actually fire")
    bad = {"id": "bad", "components": [
        {"name": "x", "bigg_metabolite": "not_a_real_bigg_id", "exchange": "EX_not_a_real_bigg_id_e",
         "mapping_method": "curated", "xref": {}}]}
    try:
        RC.Stage(corrections=rules, mapper=m).transform_medium(bad)
        check(False, "A2 rejects an unknown BiGG id")
    except SystemExit as e:
        check("A2 FAILED" in str(e), "A2 rejects an unknown BiGG id", str(e)[:60])
    bad2 = {"id": "bad2", "components": [
        {"name": "x", "bigg_metabolite": "glc__D", "exchange": "EX_wrong_e",
         "mapping_method": "curated", "xref": {}}]}
    try:
        RC.Stage(corrections=rules, mapper=m).transform_medium(bad2)
        check(False, "A3 rejects an exchange that disagrees with its metabolite")
    except SystemExit as e:
        check("A3 FAILED" in str(e), "A3 rejects an exchange that disagrees with its metabolite")

    print("\n[stage] a real sample of the shipped corpus round-trips")
    media_dir = RC.MEDIA_DIR
    files = sorted(os.listdir(media_dir))[:60]
    st = RC.Stage(corrections=rules, mapper=m)
    n_in = n_out = 0
    for f in files:
        with open(os.path.join(media_dir, f), encoding="utf-8") as fh:
            src = json.load(fh)
        n_in += len(src.get("components") or [])
        res = st.transform_medium(src)
        n_out += len(res["components"])
        for comp in res["components"]:
            if comp["evidence_tier"] not in TIER_ORDER:
                check(False, f"{f}: bad tier {comp['evidence_tier']}")
            if comp.get("bigg_metabolite") and comp["evidence_tier"] in (
                    "exact_name", "name_table", "fuzzy_name", "class_proxy"):
                if comp.get("match_key"):
                    check(False, f"{f}: name tier carries a match_key")
    check(n_in == n_out and n_in > 0, f"A8: component count preserved ({n_in} in, {n_out} out)")
    check(True, f"{len(files)} shipped media transformed without an assertion failure")

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURES: " + "; ".join(FAILS))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
