#!/usr/bin/env python3
"""Base-medium + modifier taxonomy, keyed on verified source identity and chemistry.

READS   a corpus directory (the output of 50_load_concentrations), plus two
        committed vocabularies under data/vocab: media_families.tsv (the NAMING
        registry, 269 families seeded from the formulation registries that already
        exist in this repo) and mediadive_collections.tsv (MediaDive's own
        `source` field per accession).
WRITES  the same corpus with name_display / name_core / name_verbatim /
        name_provenance_tail, a resolved `collection`, a `family` block carrying
        its own method and evidence, a typed `modifiers` list, preparation /
        strength / pH, and an explicit statement of whether the record's chemistry
        can distinguish it from its identical-composition siblings at all.
        Alongside the JSON report it writes families.tsv, name_collisions.tsv,
        composition_duplicates.tsv and unnormalizable.tsv.
ASSERTS food records never get a family; an ambiguous name is refused, not
        resolved by pattern order; a negated token never asserts presence; ids and
        `name` are never rewritten; no record is merged or deleted; a
        quantity-context "LB" never becomes the LB family; every published family
        count carries its denominator.

FINDINGS: NM-01, NM-02 (part 2), NM-03, NM-04, NM-05, NM-06, NM-07, NM-12, NM-13,
NM-16, NM-17, NM-18, NAME-01, MEDIA-WEB-07.

THE THING THIS STAGE REFUSES TO DO
----------------------------------
It does not merge. tools/merge_duplicates.py decides identity by name string and
`os.remove`s the losers; it has already destroyed 57 records (54 of them collapsing
two distinct USDA analytical datasets) and 14 more are one command away. Grouping
here is a LABEL. Every record keeps its file, its id and its citation, and a family
is an annotation a reader can disagree with, not a deletion they cannot undo.

It also does not force. A name that matches two families is refused with both
candidates recorded; a record whose chemistry cannot corroborate its name says so
in `family.corroboration_blocked_reason`; a modifier the composition cannot express
is marked `reflected_in_composition: false` and the record carries an explicit
`composition_limitation` string. Flag, never force.
"""
from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stagelib import REPO, main_guard, stamp               # noqa: E402
import normalize_names as LIB                              # noqa: E402

STAGE, VERSION = "51_normalize_names", "1.0.0"

_CTX = None
_EVENTS = collections.Counter()


def _in_dir():
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--in" and i + 1 < len(argv):
            return os.path.abspath(argv[i + 1])
        if a.startswith("--in="):
            return os.path.abspath(a.split("=", 1)[1])
    raise RuntimeError("--in is required")


def _ctx():
    global _CTX
    if _CTX is None:
        _CTX = LIB.Context(_in_dir(), os.path.join(REPO, "data", "vocab"))
    return _CTX


def transform(rec: dict, rep) -> bool:
    ctx = _ctx()
    before = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    original_id, original_name = rec.get("id"), rec.get("name")

    LIB.apply(rec, ctx, _EVENTS)

    # N5 / N6 -- checked per record, raised loudly rather than counted quietly
    if rec.get("id") != original_id:
        raise RuntimeError("%s: id was rewritten" % original_id)
    if rec.get("name") != original_name:
        raise RuntimeError("%s: `name` was overwritten; only name_display may be "
                           "derived" % original_id)
    # N1
    if rec.get("category") == "food" and rec["family"]["id"] is not None:
        raise RuntimeError("%s: a food record was assigned a family" % original_id)
    # N8
    if LIB._LB_QUANTITY.search(rec["name_core"] or "") and rec["family"]["id"] == "lb":
        raise RuntimeError("%s: a quantity-context LB resolved to the LB family"
                           % original_id)
    # N4
    for md in rec.get("modifiers") or []:
        if md.get("polarity") == "absent" and md.get("reflected_in_composition"):
            raise RuntimeError("%s: a negated modifier was asserted present" % original_id)

    after = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    if after == before:
        return False
    stamp(rec, STAGE, VERSION,
          ["name_display", "name_core", "name_provenance_tail", "collection",
           "family", "modifiers", "preparation", "strength", "ph_declared",
           "composition_signature", "composition_identical_to"])
    return True


def _write_tables(rep, ctx):
    """The tabular reports a human actually reads, next to the JSON report."""
    out = os.path.dirname(os.path.abspath(rep.out_dir))
    d = os.path.join(out, "reports")
    os.makedirs(d, exist_ok=True)
    recs = {}
    for fp in sorted(os.listdir(rep.out_dir)):
        if fp.endswith(".json"):
            r = json.load(open(os.path.join(rep.out_dir, fp)))
            recs[r["id"]] = r

    # families.tsv -- every count beside its denominator (N9)
    with open(os.path.join(d, "families.tsv"), "w") as fh:
        fh.write("family_id\tdisplay_label\tn_assigned\tn_name_matching\t"
                 "n_surface_spellings\tn_exchange_set_compositions\t"
                 "n_quantitative_compositions\tlargest_identical_block\t"
                 "n_corroborated_by_composition\tmember_ids\n")
        for fid, ids in sorted(ctx.fam_members.items(), key=lambda x: (-len(x[1]), x[0])):
            ms = [recs[i] for i in ids if i in recs]
            surf = {(m.get("name_core") or "").lower() for m in ms}
            # LIB.component_key, not c["exchange"]: 40_remap_components writes a null
            # exchange for the components it refuses to give a single target (curated
            # mark_mixture), and a null neither sorts against a string nor should
            # collapse two different unmapped ingredients onto one set member.
            exs = {tuple(sorted({LIB.component_key(c)
                                 for c in (m.get("components") or [])}))
                   for m in ms}
            qs = collections.Counter(m.get("composition_signature") for m in ms)
            nc = sum(1 for m in ms if m["family"]["method"] in
                     ("name_and_composition", "canonical_reference"))
            fh.write("%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%s\n" % (
                fid, ctx.voc.label(fid), len(ids),
                ctx.name_matched.get(fid, len(ids)), len(surf), len(exs), len(qs),
                max(qs.values()) if qs else 0, nc, ",".join(sorted(ids))))

    # name_collisions.tsv -- SAME name, DIFFERENT chemistry
    strict = collections.defaultdict(list)
    for r in recs.values():
        strict[(r.get("category"), (r.get("name") or "").strip().lower())].append(r)
    n_strict = n_loose = 0
    with open(os.path.join(d, "name_collisions.tsv"), "w") as fh:
        fh.write("# strictness=strict means the members' STORED `name` values are\n"
                 "# byte-identical. strictness=tail_stripped means they differ only\n"
                 "# by the provenance suffix this pipeline appended, so the records\n"
                 "# already disambiguate themselves and this is not a defect.\n")
        fh.write("strictness\tcategory\tname\tn_records\tmin_pairwise_jaccard\t"
                 "ids\tn_components\n")
        for label, groups in (("strict", strict),
                              ("tail_stripped", ctx.by_core)):
            for k, v in sorted(groups.items(), key=lambda x: str(x[0])):
                rs = v if label == "strict" else [recs[i] for i in v if i in recs]
                if len(rs) < 2:
                    continue
                sets = [LIB.sourced_exchanges(x) for x in rs]
                js = [LIB.jaccard(sets[i], sets[j]) or 0.0
                      for i in range(len(sets)) for j in range(i + 1, len(sets))]
                if not js or min(js) >= 0.999:
                    continue
                if label == "strict":
                    n_strict += 1
                else:
                    n_loose += 1
                fh.write("%s\t%s\t%s\t%d\t%.3f\t%s\t%s\n" % (
                    label, k[0], k[1], len(rs), min(js),
                    ",".join(x["id"] for x in rs),
                    ",".join(str(len(x.get("components") or [])) for x in rs)))

    # composition_duplicates.tsv -- DIFFERENT names, IDENTICAL chemistry
    n_dup = 0
    with open(os.path.join(d, "composition_duplicates.tsv"), "w") as fh:
        fh.write("# Records identical in exchange set AND bounds AND concentration AND\n"
                 "# every verbatim source amount. This is a REVIEW QUEUE, never a merge\n"
                 "# list: the largest laboratory block spans a Leptospira medium and a\n"
                 "# Vero B4 cell-culture medium, which are not duplicates -- they are a\n"
                 "# mapping failure wearing a duplicate's costume.\n")
        fh.write("quantitative_signature\tn_records\tn_distinct_names\tids\tnames\n")
        for sig, ids in sorted(ctx.sig_groups.items(), key=lambda x: (-len(x[1]), x[0])):
            if len(ids) < 2:
                continue
            cores = {(recs[i].get("name_core") or "").lower() for i in ids if i in recs}
            if len(cores) < 2:
                continue
            n_dup += 1
            fh.write("%s\t%d\t%d\t%s\t%s\n" % (
                sig, len(ids), len(cores), ",".join(sorted(ids)),
                " | ".join(sorted(cores)[:10])))

    with open(os.path.join(d, "unnormalizable.tsv"), "w") as fh:
        fh.write("# Records this stage REFUSED to file under a family, with the reason.\n"
                 "# A refusal is the correct outcome for a name that means two media.\n")
        fh.write("record_id\tname_core\treason\tdetail\n")
        for row in sorted(ctx.unnormalizable):
            fh.write("\t".join(row) + "\n")

    return n_strict, n_loose, n_dup, recs


def finalize(rep) -> None:
    ctx = _ctx()
    for k, v in _EVENTS.items():
        rep.count(k, v, of=rep.n_in)

    n_strict, n_loose, n_dup, recs = _write_tables(rep, ctx)
    rep.count("name_collision_groups_strict", n_strict, of=rep.n_in)
    rep.count("name_collision_groups_tail_stripped", n_loose, of=rep.n_in)
    rep.count("composition_duplicate_groups", n_dup, of=rep.n_in)

    nonfood = [r for r in recs.values() if r.get("category") != "food"]
    assigned = [r for r in nonfood if r["family"]["id"]]
    rep.count("non_food_records", len(nonfood), of=rep.n_in)
    rep.count("non_food_records_with_a_family", len(assigned), of=len(nonfood))
    rep.count("named_families_represented", len(ctx.fam_members), of=len(ctx.voc.families))

    # ---- structural post-conditions, true at any scale --------------------
    rep.assert_eq("N1_no_food_record_has_a_family",
                  sum(1 for r in recs.values()
                      if r.get("category") == "food" and r["family"]["id"]), 0)
    rep.assert_eq("N3_every_ambiguous_name_was_refused_with_its_candidates",
                  sum(1 for r in recs.values()
                      if r["family"].get("refused_reason") == "ambiguous_multiple_families"
                      and not r["family"].get("candidates")), 0)
    rep.assert_eq("N4_no_negated_modifier_asserts_presence",
                  sum(1 for r in recs.values() for m in (r.get("modifiers") or [])
                      if m.get("polarity") == "absent" and m.get("reflected_in_composition")), 0)
    rep.assert_eq("N7_no_record_was_merged_or_deleted", rep.n_out, rep.n_in)
    rep.assert_eq("N9_every_family_carries_a_method_or_a_refusal_reason",
                  sum(1 for r in recs.values()
                      if r["family"]["id"] is None and not r["family"].get("refused_reason")), 0)
    rep.assert_true("family_assignment_never_guesses",
                    all(r["family"]["id"] is not None or r["family"]["method"] is None
                        for r in recs.values()), True, True)
    rep.assert_true("every_assigned_family_states_how_it_was_reached",
                    all(r["family"]["method"] for r in recs.values() if r["family"]["id"]),
                    True, True)

    if rep.n_in == 13515:
        rep.assert_eq("NM-03_mediadive_records_reattributed_to_their_real_collection",
                      _EVENTS.get("collection_corrected_from_DSMZ", 0), 1248)
        rep.assert_eq("NM-03_JCM_count", _EVENTS.get("collection_JCM", 0), 1143)
        rep.assert_eq("NM-03_CCAP_count", _EVENTS.get("collection_CCAP", 0), 105)
        rep.assert_eq("NM-07_strict_name_collisions", n_strict, 7)

    # ---- what is still not known -----------------------------------------
    rep.unresolved(
        "non_food_records_with_no_family",
        len(nonfood) - len(assigned), len(nonfood),
        "the medium's name matches no family in data/vocab/media_families.tsv, or it "
        "matches two and was refused. Most are genuinely one-off literature media; "
        "assigning them a family on a weaker match would be a guess.")
    rep.unresolved(
        "families_asserted_on_the_name_alone",
        _EVENTS.get("family_name_only", 0), len(assigned) or 1,
        "the name matched but the record's own chemistry could not corroborate it. For "
        "the LB family this is not a threshold problem: 24 of 43 LB records have NO "
        "surviving sourced component at all, because a canonical template was written "
        "over their published DSMZ recipes (NM-02). Corroboration returns when those "
        "recipes are re-acquired from MediaDive.")
    rep.unresolved(
        "modifiers_named_but_not_representable",
        _EVENTS.get("modifiers_declared_but_not_representable", 0), len(nonfood),
        "the record's name declares a strength, supplement, antibiotic, pH or "
        "agar/broth distinction that its composition, bounds and quantities cannot "
        "express. The record now states this limitation instead of implying a "
        "difference that is not there.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize,
               inputs=["data/vocab/media_families.tsv",
                       "data/vocab/mediadive_collections.tsv"])
