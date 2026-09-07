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
    # ------------------------------------------------------------------ 2026-09-07
    # Five defects whose remedy is a corpus transform stage plus a promotion. The
    # published surfaces (payloads, browser, exports) are corrected where the
    # generating script could reach; the per-record files in data/media still carry
    # the original values, so each of these is a live difference between what the
    # site says and what data/media/<id>.json says, and each is asserted here so it
    # cannot be lost.
    "oxygen_defaulted_in_the_record": (
        "OXY-01", "5x naming/display stage",
        "11,926 records carry oxygen='facultative' while their own oxygen_note "
        "says the source stated no regime at all. The payloads and the browser now "
        "publish that as unknown and carry the facultative simulation default in a "
        "separate field, but the per-record file still reads facultative, so an API "
        "consumer reading data/media/<id>.json sees a regime nobody asserted"),
    "oxygen_note_stale_on_curated_records": (
        "OXY-02", "5x naming/display stage",
        "71 records carry oxygen='aerobic' with the note 'no oxygen requirement "
        "specified; O2 available but not asserted', left by a run predating the "
        "verification guard. The regime is a real curation; the note contradicts it"),
    "usda_nutrient_collision_last_wins": (
        "USDA-01", "USDA rebuild + a 4x chemistry stage",
        "2,025 collisions where two distinct USDA nutrients map to one BiGG "
        "exchange and dict assignment silently keeps whichever came last in the "
        "source array. 1,931 reach a shipped record and 1,434 of those disagree by "
        "more than 1%, up to a factor of 17.8; the discarded measurement exists "
        "nowhere in the shipped data, and the winner is the broad class nutrient on "
        "1,089 foods and the cis subset on 936, so the amount column is not "
        "comparable between USDA records"),
    "b12_name_is_a_different_molecule": (
        "CHEM-B12-03", "4x chemistry stage (remap_components rewrites target_name "
        "on a retarget and leaves `name` behind)",
        "4,320 components are named Cob(I)alamin while their exchange is "
        "EX_adocbl_e, adenosylcobalamin: a different molecule, and the only "
        "components in the corpus whose `name` matches neither source_name nor "
        "target_name. It reaches the documented components.parquet column a "
        "consumer joins on"),
    "en_dashes_in_the_shipped_records": (
        "VOICE-01", "5x naming/display stage",
        "all 13,515 records under data/media contain at least one U+2013/U+2014, "
        "minted by this repo's own name and citation joins. About one record page "
        "in seven renders one, through provenance.decomposition_refs[].citation, "
        "provenance.wellknown_reference or provenance.citation"),
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


def test_no_record_carries_a_licence_field_of_its_own(stream):
    """PROV-05, closed by licensing the compilation rather than each record.

    A blanket CC-BY-4.0 over CC BY-NC and all-rights-reserved material was the
    defect. The fix is one licence for the dataset, set at its most restrictive
    input (CC BY-NC 4.0), and no per-record licence field: the same string on
    every record would still read as a distinction that does not exist.
    """
    keys = ("license", "licence", "commercial_use", "commercial_use_ok",
            "attribution_required", "license_review_required")
    offenders = []
    for mid, rec in stream():
        prov = rec.get("provenance") or {}
        present = [k for k in keys if k in prov or k in rec]
        if present:
            offenders.append((mid, present))
    assert not offenders, (
        "%d records still carry per-record licence fields, e.g. %s"
        % (len(offenders), offenders[:3]))


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


# --------------------------------------------------------------------- 2026-09-07
# Five defects corrected on every published surface a generating script could
# reach, and still live in data/media because the corpus is a frozen snapshot whose
# only legitimate correction path is a transform stage plus a promotion. Each is a
# real difference between what the site says and what data/media/<id>.json says, so
# each one is asserted rather than described: when the owning stage lands, its test
# XPASSes and the marker comes off.

@_xfail("oxygen_defaulted_in_the_record")
def test_a_record_does_not_state_a_regime_no_source_asserted(stream):
    import web_payload
    lying = []
    for mid, rec in stream():
        note = (rec.get("oxygen_note") or "").strip()
        if (rec.get("oxygen") == "facultative"
                and note in web_payload.OXYGEN_NOT_STATED_NOTES):
            lying.append(mid)
    assert not lying, (
        "%d records state oxygen='facultative' while their own oxygen_note says no "
        "source stated a regime. The payloads publish these as unknown; the record "
        "file must too. e.g. %s" % (len(lying), lying[:3]))


@_xfail("oxygen_note_stale_on_curated_records")
def test_no_curated_regime_carries_a_no_statement_note(stream):
    import web_payload
    stale = []
    for mid, rec in stream():
        note = (rec.get("oxygen_note") or "").strip()
        if (rec.get("oxygen") in ("aerobic", "anaerobic")
                and note in web_payload.OXYGEN_NOT_STATED_NOTES):
            stale.append((mid, rec["oxygen"]))
    assert not stale, (
        "%d records carry a curated regime AND a note saying nothing was stated. "
        "The regime is real and the note is a leftover: e.g. %s"
        % (len(stale), stale[:3]))


@_xfail("b12_name_is_a_different_molecule")
def test_a_component_name_names_the_molecule_its_exchange_carries(stream):
    """No component's `name` may disagree with BOTH its source and its target.

    4,320 do, all one triple: name Cob(I)alamin, source_name Vitamin B-12,
    target_name Adenosylcobalamin, exchange EX_adocbl_e. Cob(I)alamin is BiGG
    cbl1, a different molecule, and 3,525 other components in this same library
    map that name to EX_cbl1_e, so one string names two molecules here.
    """
    wrong = []
    for mid, rec in stream():
        for c in rec.get("components") or []:
            nm = (c.get("name") or "").strip()
            sn = (c.get("source_name") or "").strip()
            tn = (c.get("target_name") or "").strip()
            if nm and sn and tn and nm != sn and nm != tn:
                wrong.append((mid, nm, sn, tn, c.get("exchange")))
    assert not wrong, (
        "%d components carry a `name` matching neither source_name nor "
        "target_name; the documented components.parquet leads with that column. "
        "e.g. %s" % (len(wrong), wrong[:2]))


@_xfail("en_dashes_in_the_shipped_records")
def test_no_shipped_record_carries_an_en_or_em_dash(stream):
    """The Director's ban is absolute and these strings are minted by this repo.

    They reach a reader: about one record page in seven renders one, through
    provenance.decomposition_refs[].citation, provenance.wellknown_reference or
    provenance.citation.
    """
    import re
    dash = re.compile(r"[–—]")
    hits = []
    for mid, rec in stream():
        if dash.search(json.dumps(rec, ensure_ascii=False)):
            hits.append(mid)
    assert not hits, (
        "%d of the shipped records contain U+2013 or U+2014. e.g. %s"
        % (len(hits), hits[:3]))


@_xfail("usda_nutrient_collision_last_wins")
def test_a_colliding_usda_nutrient_publishes_both_amounts(stream):
    """Two USDA nutrients on one exchange must not silently discard one amount.

    `comps[ex] = {...}` inside the per-nutrient loop keeps whichever came last in
    the source array. The shipped record names both labels in source_name and
    publishes one quantity, so a consumer cannot learn the two disagreed, by up to
    a factor of 17.8, or which one they are holding.
    """
    bad = []
    for mid, rec in stream():
        if not mid.startswith("usda_"):
            continue
        for c in rec.get("components") or []:
            if "|" not in (c.get("source_name") or ""):
                continue
            q = c.get("quantity") or {}
            if q.get("value") is None:
                continue
            if not q.get("alternatives") and not q.get("chose_by"):
                bad.append((mid, c.get("source_name"), q.get("value")))
    assert not bad, (
        "%d components credit two source nutrients and publish one amount with no "
        "record of the other and no stated rule for choosing. e.g. %s"
        % (len(bad), bad[:2]))


def test_the_ledger_is_complete():
    """Every xfail in this file must be in LEDGER with a finding id and an owner."""
    import inspect
    src = inspect.getsource(__import__(__name__, fromlist=["x"]))
    used = {line.split('"')[1] for line in src.splitlines()
            if line.strip().startswith("@_xfail(")}
    assert used <= set(LEDGER), "xfail without a ledger entry: %s" % (used - set(LEDGER))
    for k, (finding, stage, what) in LEDGER.items():
        assert finding and stage and what, k
