"""Stage 52: the browser payload, and the defects it must not be able to reintroduce.

Every fixture is a record shaped like one the audit found wrong, written out in full so
the suite runs with no corpus present. Each test has a partner that asserts the defect
cannot silently return: an unclassifiable evidence tier must RAISE rather than land in
whichever chip happens to be last (MEDIA-WEB-01), and an absent measurement must stay
null rather than become a flattering number (MEDIA-WEB-05).
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

from web_payload import (CLASS_ORDER, COLUMNS, EVIDENCE_CLASSES,   # noqa: E402
                         TIER_TO_CLASS, TOMBSTONE_REASON_CODES, build_payload)


def record(mid, **kw):
    """A minimal but schema-shaped medium record."""
    rec = {
        "id": mid,
        "name": kw.get("name", mid),
        "name_display": kw.get("name_display", kw.get("name", mid)),
        "category": kw.get("category", "laboratory"),
        "organism_scope": "prokaryote-generic",
        "oxygen": kw.get("oxygen", "facultative"),
        "aerobic": True,
        "namespace": "bigg",
        "n_components": kw.get("n_components", 2),
        "n_mapped": kw.get("n_components", 2),
        "n_in_biggr": kw.get("n_components", 2),
        "n_derived": kw.get("n_derived", 0),
        "n_observed": kw.get("n_components", 2) - kw.get("n_derived", 0),
        "n_unmappable": 0,
        "defined": None,
        "food_group": None,
        "version": "1.0",
        "uncovered": kw.get("uncovered", []),
        "coverage": {"n_uncovered": len(kw.get("uncovered", [])), "pct_covered": 100.0},
        "coverage_source": kw.get("coverage_source", {
            "n_sourced": kw.get("n_components", 2) - kw.get("n_derived", 0),
            "pct_covered_source": kw.get("pct_covered_source", 100.0),
            "pct_covered_source_denominator": 2,
            "pct_covered_source_is_upper_bound": kw.get("upper_bound", False)}),
        "quantitation": {"n_with_concentration_mM": kw.get("n_conc", 0),
                         "n_with_source_amount": 0},
        "tier_counts": kw.get("tier_counts", {"name_table": kw.get("n_components", 2)}),
        "family": kw.get("family", {"id": None, "label": None, "method": None}),
        "modifiers": kw.get("modifiers", []),
        "composition_signature": kw.get("signature", "sig-" + mid),
        "composition_identical_to": [],
        "provenance": {
            "source_type": "standard",
            "source_name": kw.get("source_name", "DSMZ MediaDive"),
            "citation": "a citation",
            "verification_status": kw.get("verification_status", "unverified"),
            "collection": None,
        },
        "components": kw.get("components", [
            {"name": "Glucose", "bigg_metabolite": "glc__D",
             "exchange": "EX_glc__D_e", "lower_bound": -1.0,
             "evidence_tier": "name_table", "xref": {"kegg": "C00031"}},
            {"name": "Water", "bigg_metabolite": "h2o", "exchange": "EX_h2o_e",
             "lower_bound": -1000.0, "evidence_tier": "name_table", "xref": {}},
        ]),
    }
    return rec


def write_corpus(tmp_path, records):
    d = tmp_path / "media"
    d.mkdir()
    for rec in records:
        (d / (rec["id"] + ".json")).write_text(json.dumps(rec), encoding="utf-8")
    return str(d)


def build(tmp_path, records, quarantine=None, reason_codes=None):
    media = write_corpus(tmp_path, records)
    out = tmp_path / "web"
    qpath = None
    if quarantine is not None:
        qpath = tmp_path / "_quarantine.json"
        qpath.write_text(json.dumps(quarantine), encoding="utf-8")
        qpath = str(qpath)
    cpath = None
    if reason_codes is not None:
        cpath = tmp_path / "reason_codes.tsv"
        cpath.write_text(
            "id\treason_code\tsource_reason\tnote\tevidence\n"
            + "".join("%s\t%s\t\t\t\n" % (k, v) for k, v in reason_codes.items()),
            encoding="utf-8")
        cpath = str(cpath)
    report = build_payload(media, str(out), repo=REPO, quarantine=qpath or "/nonexistent",
                           reason_codes=cpath)
    loaded = {n: json.loads((out / n).read_text(encoding="utf-8"))
              for n in os.listdir(out)}
    return report, loaded


# --------------------------------------------------------------- the vocabulary


def test_every_declared_tier_belongs_to_exactly_one_class():
    seen = []
    for cls in EVIDENCE_CLASSES:
        seen += cls["tiers"]
    assert len(seen) == len(set(seen)), "a tier is claimed by two evidence classes"
    assert set(seen) == set(TIER_TO_CLASS)


def test_class_order_is_the_trust_order():
    assert CLASS_ORDER[0] == "structure"
    assert CLASS_ORDER[-1] == "unresolved"
    assert CLASS_ORDER.index("name") > CLASS_ORDER.index("identifier"), (
        "a name match must never be ordered above an identifier match")


# ------------------------------------------------------- MEDIA-WEB-01 regression


def test_unknown_evidence_tier_raises_instead_of_landing_in_a_chip(tmp_path):
    """The audit's mechanism: a bare `else` swallowed five of seven values into the
    calmest grey. An unrecognised tier must be loud."""
    rec = record("m1", tier_counts={"a_tier_nobody_declared": 2})
    with pytest.raises(ValueError) as e:
        build(tmp_path, [rec])
    assert "a_tier_nobody_declared" in str(e.value)


def test_evidence_classes_partition_the_components(tmp_path):
    rec = record("m1", n_components=4,
                 tier_counts={"structural_xref": 1, "name_table": 2,
                              "derived_component": 1},
                 n_derived=1)
    report, out = build(tmp_path, [rec])
    classes = out["catalog.json"]["evidence_classes"]
    assert sum(c["n"] for c in classes) == 4
    assert all(c["of"] == 4 for c in classes), "every class must carry its denominator"
    by = {c["id"]: c["n"] for c in classes}
    assert by["structure"] == 1 and by["name"] == 2 and by["derived"] == 1


def test_no_class_is_labelled_exact(tmp_path):
    """'exact' was the withdrawn word. It must not reappear as a class label."""
    report, out = build(tmp_path, [record("m1")])
    labels = " ".join(c["label"].lower() for c in out["catalog.json"]["evidence_classes"])
    assert "exact" not in labels


# ------------------------------------------------------- MEDIA-WEB-05 regression


def test_absent_source_coverage_stays_null_and_is_counted(tmp_path):
    rec = record("m1", coverage_source={"n_sourced": 0,
                                        "pct_covered_source": None,
                                        "pct_covered_source_is_upper_bound": False})
    report, out = build(tmp_path, [rec])
    cols = out["catalog.json"]["columns"]
    row = out["catalog.json"]["rows"][0]
    assert row[cols.index("pct_covered_source")] is None, (
        "an absent coverage measurement must stay null, never become 100")
    assert out["catalog.json"]["coverage_bands_source"]["not_computed"] == 1
    assert out["catalog.json"]["coverage_bands_source"]["of"] == 1


def test_coverage_bands_partition_the_library(tmp_path):
    recs = [record("m%d" % i, pct_covered_source=p)
            for i, p in enumerate([100.0, 95.0, 70.0, 20.0])]
    report, out = build(tmp_path, recs)
    bands = out["catalog.json"]["coverage_bands_source"]
    assert bands["high_ge_90"] + bands["mid_60_90"] + bands["review_lt_60"] \
        + bands["not_computed"] == 4 == bands["of"]


def test_upper_bound_flag_survives_into_the_payload(tmp_path):
    recs = [record("m1", upper_bound=True), record("m2", upper_bound=False)]
    report, out = build(tmp_path, recs)
    cols = out["catalog.json"]["columns"]
    flags = [r[cols.index("pct_covered_source_is_upper_bound")]
             for r in out["catalog.json"]["rows"]]
    assert sorted(flags) == [0, 1]
    assert out["catalog.json"]["media_totals"][
        "n_media_source_coverage_is_upper_bound"] == 1


# --------------------------------------------------------------- UX-01 regression


def test_unknown_oxygen_is_null_and_never_anaerobic(tmp_path):
    recs = [record("m1", oxygen=None), record("m2", oxygen="anaerobic")]
    report, out = build(tmp_path, recs)
    cols = out["catalog.json"]["columns"]
    values = [r[cols.index("oxygen")] for r in out["catalog.json"]["rows"]]
    dicts = out["catalog.json"]["dicts"]["oxygen"]
    decoded = [None if v is None else dicts[v] for v in values]
    assert None in decoded, "an unknown oxygen regime must reach the browser as null"
    assert decoded.count("anaerobic") == 1, (
        "the unknown record must not be folded into anaerobic")
    assert out["catalog.json"]["by_oxygen"]["None"] == 1


# ---------------------------------------------------- MEDIA-WEB-06 / NM-05 support


def test_compound_index_covers_every_exchange_in_the_corpus(tmp_path):
    rec = record("m1")
    report, out = build(tmp_path, [rec])
    comp = out["compounds.json"]
    assert set(comp["postings"]) == {"EX_glc__D_e", "EX_h2o_e"}
    assert comp["meta"]["EX_glc__D_e"]["kegg"] == "C00031", (
        "the compound dictionary must carry cross-references so a compound can be "
        "resolved by chemistry and not only by name")
    assert comp["n_media"] == 1


def test_postings_are_delta_encoded_row_indices(tmp_path):
    recs = [record("a"), record("b"), record("c")]
    report, out = build(tmp_path, recs)
    deltas = out["compounds.json"]["postings"]["EX_h2o_e"]
    expanded, prev = [], 0
    for d in deltas:
        prev += d
        expanded.append(prev)
    assert expanded == [0, 1, 2]


def test_families_carry_their_members_and_a_denominator(tmp_path):
    fam = {"id": "lb", "label": "LB broth", "method": "name_only",
           "evidence": "name_regex:lb", "composition_corroborated": None,
           "corroboration_blocked_reason": None}
    recs = [record("lb1", family=fam, signature="same"),
            record("lb2", family=fam, signature="same"),
            record("other")]
    report, out = build(tmp_path, recs)
    fams = out["families.json"]
    assert fams["n_families"] == 1
    assert fams["n_media_in_a_family"] == 2
    assert fams["n_media_without_a_family"] == 1
    assert fams["n_media"] == 3
    entry = fams["families"][0]
    assert entry["n_members"] == 2 and entry["n_members_of"] == 3
    assert entry["n_distinct_compositions"] == 1, (
        "two variants with one composition between them must be visible as such")


# ------------------------------------------------------- COV-05 / MEDIA-WEB-11 ---


def test_a_withdrawn_identifier_resolves_to_a_class_level_reason_code(tmp_path):
    quarantine = [
        {"id": "gone_a", "name": "A", "reason": "workflow:rejected",
         "note": "REJECTED as a defined growth medium. The entry conflates ...",
         "evidence": "Live sponge explants were transferred to ..."},
        {"id": "gone_b", "name": "B", "reason": "workflow:not_found"},
    ]
    codes = {"gone_a": "extraction_artifact", "gone_b": "composition_not_stated"}
    report, out = build(tmp_path, [record("m1")], quarantine=quarantine,
                        reason_codes=codes)
    tomb = out["tombstones.json"]
    assert tomb["n_withdrawn"] == 2
    assert tomb["records"]["gone_a"] == {"name": "A",
                                         "reason_code": "extraction_artifact"}
    assert set(tomb["records"]["gone_b"]) == {"name", "reason_code"}, (
        "a tombstone carries the identifier's state, never the review that "
        "produced it")
    by_code = {c["code"]: c for c in tomb["reason_codes"]}
    assert set(by_code) == {c["code"] for c in TOMBSTONE_REASON_CODES}
    assert by_code["extraction_artifact"]["n"] == 1
    assert by_code["extraction_artifact"]["of"] == 2, (
        "every published count carries its denominator")
    assert all(c["label"] and c["definition"] for c in tomb["reason_codes"])
    blob = json.dumps(tomb)
    for banned in ("REJECTED", "sponge explants", "workflow:", "verification pass"):
        assert banned not in blob, (
            "%r reached the shipped payload; the per-record review stays in "
            "tools/curation/tombstone_reason_codes.tsv" % banned)


def test_an_unmapped_withdrawn_identifier_fails_the_build(tmp_path):
    quarantine = [{"id": "gone_a", "name": "A", "reason": "workflow:rejected"}]
    with pytest.raises(ValueError, match="no reason code"):
        build(tmp_path, [record("m1")], quarantine=quarantine, reason_codes={})


def test_a_missing_quarantine_file_is_an_empty_ledger_not_a_crash(tmp_path):
    report, out = build(tmp_path, [record("m1")])
    assert out["tombstones.json"]["n_withdrawn"] == 0


# ------------------------------------------------------------------ COV-02 ------


def test_every_aggregate_carries_its_denominator(tmp_path):
    recs = [record("m%d" % i) for i in range(3)]
    report, out = build(tmp_path, recs)
    cat = out["catalog.json"]
    for key in ("by_category", "by_source_db", "by_oxygen",
                "by_verification_status"):
        assert cat[key]["_of"] == 3, "%s ships without a denominator" % key
    assert cat["count"] == 3
    assert cat["media_totals"]["of"] == 3
    assert cat["component_totals"]["of"] == cat["component_totals"]["n_components"]


def test_summary_carries_the_same_numbers_without_the_rows(tmp_path):
    recs = [record("m%d" % i) for i in range(3)]
    report, out = build(tmp_path, recs)
    cat, summary = out["catalog.json"], out["summary.json"]
    assert "rows" not in summary and "dicts" not in summary
    assert summary["count"] == cat["count"]
    assert summary["component_totals"] == cat["component_totals"]
    assert summary["evidence_classes"] == cat["evidence_classes"]


def test_row_width_matches_the_declared_columns(tmp_path):
    report, out = build(tmp_path, [record("m1")])
    cat = out["catalog.json"]
    assert cat["columns"] == COLUMNS
    assert all(len(r) == len(COLUMNS) for r in cat["rows"])


def test_an_empty_corpus_is_fatal_not_an_empty_library(tmp_path):
    """Writing a payload of zero media would replace the library with a confident zero."""
    empty = tmp_path / "media"
    empty.mkdir()
    with pytest.raises(SystemExit):
        build_payload(str(empty), str(tmp_path / "web"), repo=REPO)
