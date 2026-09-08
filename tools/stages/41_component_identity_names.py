#!/usr/bin/env python3
"""A component's `name` names the molecule its exchange carries.

FINDINGS: CHEM-B12-03

THE DEFECT
----------
4,320 published component rows are named "Cob(I)alamin" while their exchange is
EX_adocbl_e and their target_name is "Adenosylcobalamin". Those are different
molecules: Cob(I)alamin is the BiGG display name of cbl1 (C62H87CoN13O14P,
InChIKey OMAOKVYASDIYQG-DSRCUDDDSA-L) and the exchange carries adocbl
(C72H100CoN18O17P, ZIHHMGTYZOSFRC-QRVZQHAISA-N). The rows span 4,320 of 13,515
records, 32% of the library.

`name` is residue, not a claim: tools/stages/remap_components.py rewrites
`target_name` at each of its four retarget sites (lines 324, 395, 436, 477) and
never rewrites `name`, so `name` keeps the display name of the metabolite the
component USED to point at.

WHY IT MATTERS EVEN THOUGH THE PAGE IS RIGHT
--------------------------------------------
assets/media.js:613 reads `c.target_name || c.name`, and the browser CSV export
does the same, so a visitor sees the correct molecule. The defect reaches the
documented programmatic routes instead: data/api/components.parquet, which API.md
documents `name` in with no caveat, and data/media/<id>.json, which
pymediadb.iter_full_records() walks. A consumer joining on `name` reads a molecule
that contradicts the `exchange`, `bigg_metabolite`, `target_name` and
`xref_inchikey` sitting in the same row. Identity resolved by a stale string is
exactly what this resource exists to argue against.

WHAT THIS STAGE DOES
--------------------
The general rule, not a B12 special case: if `name` matches NEITHER `source_name`
nor `target_name` (nor any entry in `source_name_candidates`, which is where a
recorded name collision is kept), then `name` is residue and is replaced. The
replacement is `source_name` when the source stated one, because `name` is
documented as the source's own string, and `target_name` otherwise.

Measured over the shipped corpus, this rewrites 4,956 rows:
  4,320  Cob(I)alamin              -> Vitamin B-12                (source's label)
    111  Vitamin B12 / vitamin B12 -> Adenosylcobalamin           (source_name null)
    636  L-cystine / L-Cystine     -> L Cystine C6H12N2O4S2       (source_name null)
Zero rows whose `name` already agrees with source_name or target_name are touched.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not use the broader rule "name equals some OTHER metabolite's BiGG display
name". That over-catches 20 legitimate rows such as ('1-Butanol', btoh,
'1-Butanol'), where the source genuinely used a label that collides with another
BiGG id. Agreement with the row's own two names is the test.

It does not touch `target_name`, `bigg_metabolite`, `exchange` or any xref: this
stage corrects a display string, not a mapping. The cystine rows remain a
mis-target (Cystine is the disulfide dimer cysi__L, not the monomer cys__L); that
is a separate defect, stated in the component's own mapping note, and renaming the
row does not fix it and must not look as though it did.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stagelib import main_guard, stamp                            # noqa: E402

STAGE, VERSION = "41_component_identity_names", "1.0.0"


def _norm(s):
    return (s or "").strip().casefold()


def transform(rec: dict, rep) -> bool:
    changed = []
    for comp in rec.get("components") or []:
        name = comp.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        known = {_norm(comp.get("source_name")), _norm(comp.get("target_name"))}
        for cand in comp.get("source_name_candidates") or []:
            known.add(_norm(cand))
        known.discard("")
        if _norm(name) in known:
            continue
        replacement = comp.get("source_name") or comp.get("target_name")
        if not isinstance(replacement, str) or not replacement.strip():
            # Nothing established to replace it with. Leave the residue rather
            # than blanking the field: an empty string would be a value pretending
            # to be an absence, and null here would lose the only string there is.
            rep.count("name_is_residue_and_nothing_to_replace_it_with")
            continue
        rep.count("component_name_replaced")
        if comp.get("exchange") == "EX_adocbl_e":
            rep.count("adocbl_row_renamed")
        comp["name"] = replacement
        changed.append("components[].name")
    if not changed:
        return False
    stamp(rec, STAGE, VERSION, changed)
    return True


def finalize(rep):
    c = rep.counters

    def got(name):
        return c.get(name, {"n": 0})["n"]

    rep.count("records_seen", 0, rep.n_in)
    rep.unresolved(
        "component_name_is_a_mis_target_not_only_a_mis_name",
        got("adocbl_row_renamed"), rep.n_in,
        "the 636 cystine rows this stage renames still point cys__L (the monomer) "
        "at a Cystine measurement (the disulfide dimer, cysi__L). Renaming the "
        "display string does not correct the mapping and is not claimed to; the "
        "component's own mapping note states the mis-target.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize, inputs=[])
