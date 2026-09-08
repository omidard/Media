"""
One test per defect class the remediation is fixing.

Each of these FAILS against the frozen snapshot, on purpose. They carry the finding
id and the stage that is expected to close them, and the marker is removed the
moment the stage lands, so the defect can never come back silently. That is the
whole point: a fixed defect must have a test that would fail if it returned.

THE MARKERS ARE STRICT, and that is the mechanism, not a detail. They were
`strict=False`, which reports a defect that has been fixed as an XPASS and a defect
that has REGRESSED as an XFAIL, and pytest exits 0 on both. Ten of them had
outlived their defects and were still in place, so ten schema and evidence-class
invariants could regress with the whole suite green: measured, by planting one
faithful regression per fixed defect in a corpus copy and running the suite, which
reported "2 passed, 12 xfailed, 5 xpassed" and exit 0, then the same corpus with
--runxfail, which reported 12 failures. Neither CI workflow runs `make test-strict`,
so the exit code was the entire signal. With `strict=True` a defect that starts
passing FAILS, which forces the marker to be promoted to a real test instead of
quietly rotting.

    pytest tests/test_defects.py -rX      # show which defects are now fixed

`make test-strict` runs this file with `--runxfail`, which is what CI will use once
the ledger is empty.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# defect id -> (finding, stage expected to fix it, one-line statement)
LEDGER = {
    "unknown_oxygen_asserted_as_a_boolean": (
        "UX-01", "3x/5x stage",
        "media with no stated oxygen requirement carry aerobic=false, which the "
        "site renders as 'anaerobic'"),
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
    "usda_two_nutrient_names_one_unattributed_amount": (
        "USDA-02", "a USDA rebuild that records which nutrient it read",
        "16,937 components carry a source_name of the form 'A|B' -- two USDA "
        "nutrient labels the name map collapsed onto one BiGG id -- publish one "
        "amount, and never say which of the two labels it was read from. Unlike "
        "USDA-01 no measurement was discarded here (only one of the two names is "
        "reported by these foods), so no number is wrong; the attribution is "
        "absent. Recording it needs the reported name per component, which the "
        "frozen corpus does not carry and which a USDA rebuild would"),
    "oxygen_note_stale_on_curated_records": (
        "OXY-02", "5x naming/display stage",
        "71 records carry oxygen='aerobic' with the note 'no oxygen requirement "
        "specified; O2 available but not asserted', left by a run predating the "
        "verification guard. The regime is a real curation; the note contradicts it"),
}


def _xfail(defect):
    finding, stage, what = LEDGER[defect]
    return pytest.mark.xfail(
        reason="%s: %s (expected to be fixed by %s)" % (finding, what, stage),
        strict=True)


NAME_ROUTES = ("name", "name_remap", "name_alias_remap", "remap_name",
               "name_deformula_remap", "remap_name_deformula", "name_strict",
               "name_idx", "name_nf", "name_acid_heuristic",
               "remap_name_acid_heuristic", "foodb_inchikey_name", "mediadb_alias")
DERIVED_METHODS = ("hydrolysate_approximation", "complex_decomposition",
                   "mineral_base", "base_medium_expansion")


def test_n_mapped_counts_only_bigg_mapped_components(summary):
    assert summary["n_mapped_mismatch"] == [], (
        "%d records declare n_mapped != the number of components with a BiGG id, "
        "e.g. %s" % (len(summary["n_mapped_mismatch"]), summary["n_mapped_mismatch"][:3]))


def test_namespace_is_computed_not_constant(stream):
    lying = []
    for mid, rec in stream():
        comps = rec.get("components") or []
        has_nonbigg = any(not c.get("bigg_metabolite") and c.get("exchange") for c in comps)
        if has_nonbigg and rec.get("namespace") == "bigg":
            lying.append(mid)
    assert not lying, ("%d records claim namespace 'bigg' while carrying non-BiGG "
                       "exchange ids, e.g. %s" % (len(lying), lying[:5]))


def test_category_uses_one_vocabulary(summary):
    assert "growth_medium" not in summary["category_values"], summary["category_values"]


def test_version_is_always_a_string(summary):
    assert summary["version_non_string"] == [], summary["version_non_string"][:5]


def test_curation_key_does_not_carry_two_meanings(stream):
    offenders = [mid for mid, rec in stream() if "curation" in rec]
    assert not offenders, ("%d records still use the `curation` key for a composition "
                           "descriptor; it must be formulation_class (the trust tier "
                           "owns `curation_tier` in the index). e.g. %s"
                           % (len(offenders), offenders[:5]))


def test_defined_is_an_explicit_tristate(stream):
    missing = [mid for mid, rec in stream() if "defined" not in rec]
    assert not missing, ("`defined` absent on %d records; it must be present as "
                         "true | false | null so 'unknown' is distinguishable from "
                         "'not defined'. e.g. %s" % (len(missing), missing[:5]))


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


def test_absent_is_null_never_an_empty_string(stream):
    counts = {}
    for _mid, rec in stream():
        for k, v in rec.items():
            if v == "":
                counts[k] = counts.get(k, 0) + 1
    assert not counts, "empty strings standing for 'unknown': %s" % counts


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
# Defects corrected on every published surface a generating script could reach, and
# still live in data/media because the corpus is a frozen snapshot whose only
# legitimate correction path is a transform stage plus a promotion. Each is a real
# difference between what the site says and what data/media/<id>.json says, so each
# one is asserted rather than described: when the owning stage lands, its test
# XPASSes, and because the markers are strict that XPASS is a FAILURE, which is what
# forces the marker off instead of letting it rot.

def test_a_record_does_not_state_a_regime_no_source_asserted(stream):
    """Closed by 54_oxygen_regime_absent_when_unstated, promoted 2026-09-08.

    11,926 records read oxygen='facultative' while their own oxygen_note said no
    source stated a regime at all: 88% of the library carrying a curated-looking
    answer in the field the site itself calls the most consequential bound in an FBA
    medium. The payloads had published it as null since the OXY-01 fix, and
    data/media/<id>.json had not, which is the copy API.md sends a reader to and the
    one pymediadb walks.

    The regime and the simulation convention are separate fields now, so no tally
    moved: by_oxygen is unchanged at {null 12,365, anaerobic 749, facultative 210,
    aerobic 191}.
    """
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


def test_a_record_that_hides_its_regime_publishes_the_convention_it_used(stream):
    """Nulling the field is only half of it: EX_o2_e was still written from something.

    A record whose regime is unknown still exports an oxygen bound, and a reader who
    is told only "unknown" cannot tell whether the medium they just copied opens
    EX_o2_e or closes it. oxygen_default_for_simulation carries that, on every
    record, so the curated regime and the convention can never be the same number
    again.
    """
    missing = []
    for mid, rec in stream():
        if "oxygen_default_for_simulation" not in rec:
            missing.append(mid)
    assert not missing, (
        "%d records publish no simulation default beside their regime, so what "
        "EX_o2_e was written from is unstated. e.g. %s"
        % (len(missing), missing[:3]))


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


def test_a_colliding_usda_nutrient_publishes_both_amounts(stream, is_full_corpus):
    """Two USDA nutrients on one exchange must not silently discard one amount.

    `comps[ex] = {...}` inside the per-nutrient loop keeps whichever came last in
    the source array. The shipped record named both labels in source_name and
    published one quantity, so a consumer could not learn the two disagreed, by up
    to a factor of 17.8, or which one they were holding.

    THE PREDICATE IS THE COLLISION, NOT THE PIPE. This test used to flag every
    component whose source_name contains "|", which is 18,867 of them, when only
    1,930 involve an amount that was actually discarded: 4,834 carry
    "Cystine|Cysteine" and no USDA food reports both (4,826 report Cystine, 24
    report Cysteine, 0 report both), so nothing was ever overwritten there. The
    ground truth is tools/usda_nutrient_collisions.json, replayed from the source
    zips rather than read back out of the corpus this test is checking.

    The remaining 16,937 pipe-carrying components are a DIFFERENT defect, on the
    ledger as usda_two_nutrient_names_one_unattributed_amount: they credit two
    source labels and never say which one the amount came from.
    """
    import sys
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import build_usda_nutrient_collisions as UC
    if not os.path.exists(UC.OUT):
        pytest.skip("tools/usda_nutrient_collisions.json is not built in this tree")
    table = UC.load()

    bad, checked = [], 0
    for mid, rec in stream():
        per_medium = table.get(mid)
        if not per_medium:
            continue
        for c in rec.get("components") or []:
            entry = per_medium.get(c.get("exchange"))
            if not entry:
                continue
            q = c.get("quantity") or {}
            if q.get("value") is None:
                continue
            checked += 1
            chosen = next(r for r in entry["measurements"]
                          if r["source_name"] == entry["chosen"])
            if not q.get("alternatives") or not q.get("chose_by"):
                bad.append((mid, c.get("source_name"), q.get("value")))
            elif q["value"] != chosen["value"]:
                bad.append((mid, "applied %r, chemistry chooses %r"
                            % (q["value"], chosen["value"]), entry["chosen"]))
    assert not bad, (
        "%d components credit two source nutrients and publish one amount with no "
        "record of the other, or publish the measurement the stated rule does not "
        "choose. e.g. %s" % (len(bad), bad[:2]))
    if is_full_corpus:
        assert checked == 1930, (
            "precondition: 1,930 colliding components reach a shipped record; this "
            "run examined %d, so the assertion above proved less than it claims"
            % checked)


@_xfail("usda_two_nutrient_names_one_unattributed_amount")
def test_a_collapsed_usda_nutrient_name_says_which_one_it_read(stream):
    """"MUFA 18:1 c|MUFA 18:1" with one amount does not say which was measured.

    Sibling of USDA-01 and deliberately separate from it. There no measurement was
    lost, so no published number is wrong; what is absent is the attribution, and
    an absent attribution must read as absent rather than as a component credited
    to two sources at once. The fix is upstream of this corpus: the builder has the
    reported nutrient name in hand and does not keep it.
    """
    import sys
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import build_usda_nutrient_collisions as UC
    table = UC.load() if os.path.exists(UC.OUT) else {}
    unattributed = []
    for mid, rec in stream():
        per_medium = table.get(mid) or {}
        for c in rec.get("components") or []:
            if "|" not in (c.get("source_name") or ""):
                continue
            if c.get("exchange") in per_medium:
                continue                      # USDA-01: a real collision, resolved
            q = c.get("quantity") or {}
            if q.get("value") is None:
                continue
            if not q.get("reported_source_name"):
                unattributed.append((mid, c.get("source_name")))
    assert not unattributed, (
        "%d components credit two USDA nutrient labels for one amount without "
        "naming the one it was read from. e.g. %s"
        % (len(unattributed), unattributed[:2]))


def test_the_ledger_is_complete():
    """Every xfail in this file must be in LEDGER with a finding id and an owner."""
    import inspect
    src = inspect.getsource(__import__(__name__, fromlist=["x"]))
    used = {line.split('"')[1] for line in src.splitlines()
            if line.strip().startswith("@_xfail(")}
    assert used <= set(LEDGER), "xfail without a ledger entry: %s" % (used - set(LEDGER))
    for k, (finding, stage, what) in LEDGER.items():
        assert finding and stage and what, k
