"""
Schema validation over EVERY record in the corpus.

One streaming pass collects every violation with its count and up to five worked
examples, so a failure names what is wrong and how much of it there is rather than
dying on the first bad record.

These tests are written against the record contract in tools/stages/README.md and
DESIGN.md, corrected where the audit proved the documentation wrong (SCHEMA-02).
"""
import json
import re

import pytest

EX_RE = re.compile(r"^EX_.+_e$")

REQUIRED_TOP = ("id", "name", "category", "description", "namespace", "provenance",
                "components", "n_components", "n_mapped", "n_in_biggr")
REQUIRED_PROV = ("source_type", "citation")
REQUIRED_COMP = ("name", "bigg_metabolite", "exchange", "lower_bound", "upper_bound",
                 "in_biggr", "mapping_method")

TOP_TYPES = {
    "id": str, "name": str, "category": str, "description": str, "namespace": str,
    "n_components": int, "n_mapped": int, "n_in_biggr": int,
    "components": list, "provenance": dict,
}
NULLABLE_BOOL = ("aerobic", "defined", "complex", "complex_medium", "assay_base")


def _report(violations, cap=5):
    lines = []
    for k, v in sorted(violations.items(), key=lambda kv: -len(kv[1])):
        lines.append("  %-46s %6d  e.g. %s" % (k, len(v), v[:cap]))
    return "\n".join(lines)


@pytest.fixture(scope="session")
def violations(stream):
    """One pass: {violation name: [examples]}."""
    v = {}

    def bad(name, example):
        v.setdefault(name, []).append(example)

    for mid, rec in stream():
        if rec.get("id") != mid:
            bad("id_does_not_match_filename", (mid, rec.get("id")))
        for k in REQUIRED_TOP:
            if k not in rec:
                bad("missing_top_key:" + k, mid)
        for k, t in TOP_TYPES.items():
            if k in rec and not isinstance(rec[k], t):
                bad("wrong_type:%s(expected %s)" % (k, t.__name__),
                    (mid, type(rec[k]).__name__))
        if "version" in rec and rec["version"] is not None and not isinstance(rec["version"], str):
            bad("wrong_type:version(expected str)", (mid, type(rec["version"]).__name__))
        for k in NULLABLE_BOOL:
            if k in rec and rec[k] is not None and not isinstance(rec[k], bool):
                bad("wrong_type:%s(expected bool or null)" % k, (mid, repr(rec[k])[:40]))
        prov = rec.get("provenance") or {}
        for k in REQUIRED_PROV:
            if k not in prov:
                bad("missing_provenance_key:" + k, mid)

        comps = rec.get("components") or []
        if rec.get("n_components") != len(comps):
            bad("n_components_disagrees_with_components", (mid, rec.get("n_components"), len(comps)))
        n_bigg = n_inb = 0
        for c in comps:
            if not isinstance(c, dict):
                bad("component_is_not_an_object", (mid, type(c).__name__))
                continue
            for k in REQUIRED_COMP:
                if k not in c:
                    bad("missing_component_key:" + k, (mid, c.get("name")))
            ex, b = c.get("exchange"), c.get("bigg_metabolite")
            if ex is not None and not EX_RE.match(str(ex)):
                bad("exchange_is_not_EX_x_e", (mid, ex))
            if b:
                n_bigg += 1
                if ex != "EX_%s_e" % b:
                    bad("exchange_does_not_match_bigg_metabolite", (mid, b, ex))
            for k in ("lower_bound", "upper_bound"):
                if k in c and not isinstance(c[k], (int, float)):
                    bad("wrong_type:component.%s" % k, (mid, repr(c.get(k))[:30]))
            if c.get("concentration_mM") is not None and not isinstance(
                    c["concentration_mM"], (int, float)):
                bad("wrong_type:component.concentration_mM", (mid, repr(c["concentration_mM"])[:30]))
            if "xref" in c and not isinstance(c["xref"], dict):
                bad("wrong_type:component.xref", (mid, type(c["xref"]).__name__))
            if c.get("in_biggr") is True:
                n_inb += 1
        if rec.get("n_in_biggr") != n_inb:
            bad("n_in_biggr_disagrees_with_components", (mid, rec.get("n_in_biggr"), n_inb))
        # n_mapped is checked separately (test_defects) because the frozen snapshot
        # violates it by construction until 10_normalize_schema runs.
        cov = rec.get("coverage")
        if cov is not None and not isinstance(cov, dict):
            bad("wrong_type:coverage", (mid, type(cov).__name__))
    return v


# Schema defects the audit measured in the frozen snapshot, pinned at their measured
# size so they can GROW into a failure but a fix does not break the suite. Whether
# each is fixed is owned by tests/test_defects.py, which XPASSes when a stage closes
# it. Anything not listed here is a hard failure.
KNOWN = {
    "wrong_type:version(expected str)": (443, "SCHEMA-06", "10_normalize_schema"),
    "missing_component_key:in_biggr": (136, "MAP-09 / SCHEMA-08", "4x chemistry stage"),
}


def _split_known(hard):
    unknown, grown = {}, {}
    for k, ex in hard.items():
        if k in KNOWN:
            cap = KNOWN[k][0]
            if len(ex) > cap:
                grown[k] = (len(ex), cap)
        else:
            unknown[k] = ex
    return unknown, grown


def test_every_record_parses_and_has_the_required_shape(violations):
    hard = {k: ex for k, ex in violations.items()
            if k.startswith(("missing_top_key", "missing_provenance_key",
                             "wrong_type:", "component_is_not_an_object",
                             "id_does_not_match_filename"))}
    unknown, grown = _split_known(hard)
    assert not unknown, "schema violations:\n" + _report(unknown)
    assert not grown, ("a known schema defect grew: %s (recorded size in tests/"
                       "test_schema.py KNOWN)" % grown)


def test_component_shape(violations):
    hard = {k: ex for k, ex in violations.items()
            if k.startswith(("missing_component_key", "exchange_is_not"))}
    unknown, grown = _split_known(hard)
    assert not unknown, "component schema violations:\n" + _report(unknown)
    assert not grown, "a known component-schema defect grew: %s" % grown


def test_counters_agree_with_components(violations):
    hard = {k: ex for k, ex in violations.items()
            if k in ("n_components_disagrees_with_components",
                     "n_in_biggr_disagrees_with_components")}
    assert not hard, "record counters disagree with the component list:\n" + _report(hard)


def test_exchange_identity_holds_for_every_mapped_component(violations):
    """exchange == EX_<bigg_metabolite>_e — held in 664,218/664,218 components.

    This is the invariant the whole chemistry workstream must preserve: a stage
    that rewrites a metabolite id has to rewrite its exchange in the same step.
    """
    bad = violations.get("exchange_does_not_match_bigg_metabolite", [])
    assert not bad, "exchange/metabolite mismatch in %d components, e.g. %s" % (len(bad), bad[:5])


# Empty-string-for-unknown, measured in the frozen snapshot (SCHEMA-02). Fixed by
# 10_normalize_schema; tests/test_defects.py owns the "is it fixed yet" signal.
KNOWN_EMPTY_STRINGS = {"organism_scope": 471, "food_group": 2, "oxygen_note": 1}


def test_no_new_empty_string_stands_for_unknown(stream):
    """Absent is null. An empty string is a value, and it lies about being one."""
    counts = {}
    for _mid, rec in stream():
        for k, v in rec.items():
            if v == "":
                counts[k] = counts.get(k, 0) + 1
    new_fields = {k: v for k, v in counts.items() if k not in KNOWN_EMPTY_STRINGS}
    grown = {k: (v, KNOWN_EMPTY_STRINGS[k]) for k, v in counts.items()
             if k in KNOWN_EMPTY_STRINGS and v > KNOWN_EMPTY_STRINGS[k]}
    assert not new_fields, ("empty strings used as 'unknown' in fields that had none "
                            "(absent must be null): %s" % new_fields)
    assert not grown, "empty-string usage grew: %s" % grown


def test_corpus_size_matches_the_recorded_baseline(summary, baseline, is_full_corpus):
    if not is_full_corpus:
        pytest.skip("not the full frozen corpus")
    assert summary["n_records"] == baseline["n_media"]
    assert summary["n_components_total"] == baseline["n_components"]
