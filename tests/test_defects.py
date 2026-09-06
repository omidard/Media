"""
One test per defect class the remediation is fixing.

Each of these FAILS against the frozen snapshot, on purpose. They are marked xfail
(non-strict) so the suite is landable today, and they carry the finding id and the
stage that is expected to close them. When a stage lands, its test XPASSes — pytest
reports that — and the marker is then removed so the defect can never come back
silently. That is the whole point: a fixed defect must have a test that would fail
if it returned.

    pytest tests/test_defects.py -rX      # show which defects are now fixed

`make test-strict` runs this file with `--runxfail`, which is what CI will use once
the ledger is empty.
"""
import json
import os

import pytest

# defect id -> (finding, stage expected to fix it, one-line statement)
LEDGER = {
    "n_mapped_tautology": (
        "SCHEMA-01", "10_normalize_schema",
        "n_mapped equals n_components in 13,515/13,515 records, overstating BiGG "
        "mapping by 1,364 components across 275 media"),
    "namespace_is_a_constant": (
        "SCHEMA-01", "10_normalize_schema",
        "namespace is the literal 'bigg' on every record, including the 276 media "
        "carrying 1,384 non-BiGG exchange ids"),
    "category_vocabulary_split": (
        "SCHEMA-06", "10_normalize_schema",
        "443 records use growth_medium for what 4,930 records call laboratory"),
    "version_type_split": (
        "SCHEMA-06", "10_normalize_schema",
        "version is a string on 12,339 records and an int on 443"),
    "curation_key_collision": (
        "SCHEMA-05", "10_normalize_schema",
        "record-level `curation` holds a composition descriptor while the index "
        "writes a trust tier under the same key"),
    "defined_key_absent": (
        "SCHEMA-03", "10_normalize_schema",
        "`defined` is absent on 9,798 records and became '' in the catalog, so a "
        "documented defined=False query returns 79% unknowns"),
    "exact_confidence_on_a_name_match": (
        "MAP-02 / COV-01", "4x chemistry stage",
        "components are labelled mapping_confidence 'exact' while their "
        "mapping_method is a name-string route, not a cross-reference"),
    "derived_components_are_not_flagged": (
        "MAP-06 / PROV-07", "3x components stage",
        "229,509 pipeline-derived components (34.5%) are not marked "
        "derived-not-sourced and are counted as covered"),
    "unknown_oxygen_asserted_as_a_boolean": (
        "UX-01", "3x/5x stage",
        "media with no stated oxygen requirement carry aerobic=false, which the "
        "site renders as 'anaerobic'"),
    "no_per_record_licence": (
        "PROV-05", "2x licensing stage",
        "no record states its upstream licence, so 1,189 non-commercial / "
        "all-rights-reserved records are redistributed under a blanket CC-BY-4.0"),
    "empty_string_means_unknown": (
        "SCHEMA-02", "10_normalize_schema",
        "474 fields hold '' to mean 'not known' (organism_scope 471, food_group 2, "
        "oxygen_note 1), which is a value pretending to be an absence"),
    "component_missing_in_biggr": (
        "MAP-09 / SCHEMA-08", "4x chemistry stage",
        "136 components carry no in_biggr flag at all, so 'is it in the reactome' is "
        "unanswerable for them rather than false"),
    "mapping_method_spelling_split": (
        "SCHEMA-02", "4x chemistry stage (after reconciling bound conventions)",
        "the same recovery step is spelled remap_X by one emitter and X_remap by "
        "the other, and the spelling is the only marker of which bound convention "
        "was applied"),
}


def _xfail(defect):
    finding, stage, what = LEDGER[defect]
    return pytest.mark.xfail(
        reason="%s — %s (expected to be fixed by %s)" % (finding, what, stage),
        strict=False)


NAME_ROUTES = ("name", "name_remap", "name_alias_remap", "remap_name",
               "name_deformula_remap", "remap_name_deformula", "name_strict",
               "name_idx", "name_nf", "name_acid_heuristic",
               "remap_name_acid_heuristic", "foodb_inchikey_name", "mediadb_alias")
DERIVED_METHODS = ("hydrolysate_approximation", "complex_decomposition",
                   "mineral_base", "base_medium_expansion")


@_xfail("n_mapped_tautology")
def test_n_mapped_counts_only_bigg_mapped_components(summary):
    assert summary["n_mapped_mismatch"] == [], (
        "%d records declare n_mapped != the number of components with a BiGG id, "
        "e.g. %s" % (len(summary["n_mapped_mismatch"]), summary["n_mapped_mismatch"][:3]))


@_xfail("namespace_is_a_constant")
def test_namespace_is_computed_not_constant(stream):
    lying = []
    for mid, rec in stream():
        comps = rec.get("components") or []
        has_nonbigg = any(not c.get("bigg_metabolite") and c.get("exchange") for c in comps)
        if has_nonbigg and rec.get("namespace") == "bigg":
            lying.append(mid)
    assert not lying, ("%d records claim namespace 'bigg' while carrying non-BiGG "
                       "exchange ids, e.g. %s" % (len(lying), lying[:5]))


@_xfail("category_vocabulary_split")
def test_category_uses_one_vocabulary(summary):
    assert "growth_medium" not in summary["category_values"], summary["category_values"]


@_xfail("version_type_split")
def test_version_is_always_a_string(summary):
    assert summary["version_non_string"] == [], summary["version_non_string"][:5]


@_xfail("curation_key_collision")
def test_curation_key_does_not_carry_two_meanings(stream):
    offenders = [mid for mid, rec in stream() if "curation" in rec]
    assert not offenders, ("%d records still use the `curation` key for a composition "
                           "descriptor; it must be formulation_class (the trust tier "
                           "owns `curation_tier` in the index). e.g. %s"
                           % (len(offenders), offenders[:5]))


@_xfail("defined_key_absent")
def test_defined_is_an_explicit_tristate(stream):
    missing = [mid for mid, rec in stream() if "defined" not in rec]
    assert not missing, ("`defined` absent on %d records; it must be present as "
                         "true | false | null so 'unknown' is distinguishable from "
                         "'not defined'. e.g. %s" % (len(missing), missing[:5]))


@_xfail("exact_confidence_on_a_name_match")
def test_exact_confidence_is_reserved_for_verified_chemistry(stream):
    n_exact_by_name = n_exact = 0
    example = []
    for mid, rec in stream():
        for c in rec.get("components") or []:
            if c.get("mapping_confidence") != "exact":
                continue
            n_exact += 1
            if str(c.get("mapping_method", "")) in NAME_ROUTES:
                n_exact_by_name += 1
                if len(example) < 3:
                    example.append((mid, c.get("name"), c.get("mapping_method")))
    assert n_exact_by_name == 0, (
        "%d of %d components labelled 'exact' were resolved by a name string, not by "
        "structure or a verified cross-reference, e.g. %s"
        % (n_exact_by_name, n_exact, example))


@_xfail("derived_components_are_not_flagged")
def test_pipeline_derived_components_say_they_are_derived(stream):
    unflagged = 0
    total = 0
    example = []
    for mid, rec in stream():
        for c in rec.get("components") or []:
            total += 1
            if str(c.get("mapping_method", "")) in DERIVED_METHODS:
                if not (c.get("derived") or c.get("derived_not_sourced")
                        or c.get("evidence") == "derived"):
                    unflagged += 1
                    if len(example) < 3:
                        example.append((mid, c.get("name"), c.get("mapping_method")))
    assert unflagged == 0, (
        "%d of %d component rows were produced by the pipeline rather than read from "
        "the cited source, and carry no derived flag, e.g. %s"
        % (unflagged, total, example))


@_xfail("unknown_oxygen_asserted_as_a_boolean")
def test_unknown_oxygen_is_null_not_false(stream):
    lying = []
    for mid, rec in stream():
        note = (rec.get("oxygen_note") or "").lower()
        unknown = ("no oxygen requirement specified" in note
                   or "unknown" in note or rec.get("oxygen") in (None, "", "unknown"))
        if unknown and rec.get("aerobic") is False:
            lying.append(mid)
    assert not lying, ("%d media with no stated oxygen requirement assert aerobic=false, "
                       "which renders as 'anaerobic'. e.g. %s" % (len(lying), lying[:5]))


@_xfail("no_per_record_licence")
def test_every_record_states_its_upstream_licence(stream):
    missing = []
    for mid, rec in stream():
        prov = rec.get("provenance") or {}
        if not (prov.get("licence") or prov.get("license") or rec.get("licence")):
            missing.append(mid)
    assert not missing, ("%d records carry no upstream licence; 1,189 of them are "
                         "non-commercial or all-rights-reserved. e.g. %s"
                         % (len(missing), missing[:5]))


@_xfail("empty_string_means_unknown")
def test_absent_is_null_never_an_empty_string(stream):
    counts = {}
    for _mid, rec in stream():
        for k, v in rec.items():
            if v == "":
                counts[k] = counts.get(k, 0) + 1
    assert not counts, "empty strings standing for 'unknown': %s" % counts


@_xfail("component_missing_in_biggr")
def test_every_component_answers_whether_it_is_in_the_reactome(stream):
    missing = 0
    example = []
    for mid, rec in stream():
        for c in rec.get("components") or []:
            if "in_biggr" not in c:
                missing += 1
                if len(example) < 3:
                    example.append((mid, c.get("name")))
    assert missing == 0, ("%d components have no in_biggr flag, e.g. %s"
                          % (missing, example))


@_xfail("mapping_method_spelling_split")
def test_one_spelling_per_mapping_method(stream):
    seen = set()
    for _mid, rec in stream():
        for c in rec.get("components") or []:
            m = c.get("mapping_method")
            if m:
                seen.add(m)
    pairs = sorted((m, "remap_" + m[:-len("_remap")]) for m in seen
                   if m.endswith("_remap") and "remap_" + m[:-len("_remap")] in seen)
    assert not pairs, ("the same recovery step ships under two spellings: %s" % pairs)


def test_the_ledger_is_complete():
    """Every xfail in this file must be in LEDGER with a finding id and an owner."""
    import inspect
    src = inspect.getsource(__import__(__name__, fromlist=["x"]))
    used = {line.split('"')[1] for line in src.splitlines()
            if line.strip().startswith("@_xfail(")}
    assert used <= set(LEDGER), "xfail without a ledger entry: %s" % (used - set(LEDGER))
    for k, (finding, stage, what) in LEDGER.items():
        assert finding and stage and what, k
