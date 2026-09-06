"""
Regression tests for the invariants the audit PROVED hold, plus the artifact
consistency identity it proved does NOT.

An invariant that currently holds is a regression test: it must never quietly
break. An invariant that currently fails is in tests/test_defects.py with its
finding id, so it cannot be quietly "fixed" by being forgotten either.
"""
import glob
import json
import os

import pytest


def test_exchange_identity_is_universal(summary, baseline, is_full_corpus, stream):
    """Every mapped component's exchange is EX_<bigg_metabolite>_e, and no component
    loses its mapping except through a curated correction that says why.

    The audit measured 664,218 of 665,582 components carrying a BiGG id. The corrected
    corpus carries fewer, and that is the point: 40_remap_components applies reviewed
    corrections that REMOVE an id where none is defensible — chromium, and the
    mark_mixture verdicts on yeast extract, peptone and "trace element solution". A
    plain equality against the audit number would either forbid that correction or, if
    the number were simply updated, would stop noticing a silent loss.

    So the delta is asserted against the evidence in the data: it must equal exactly the
    number of components the chain tiered `unmapped` or `unmappable_mixture`. On a corpus
    the chain has not processed there are none, and this reduces to the original
    equality.
    """
    assert summary["exchange_identity_bad"] == [], summary["exchange_identity_bad"][:5]
    if not is_full_corpus:
        return
    refused = 0
    for _mid, rec in stream():
        for c in rec.get("components") or []:
            if c.get("evidence_tier") in ("unmapped", "unmappable_mixture"):
                assert not c.get("bigg_metabolite"), (
                    "a component tiered %r still carries a BiGG id" % c["evidence_tier"])
                refused += 1
    assert summary["components_with_bigg"] + refused == baseline["components_with_bigg"], (
        "components with a BiGG id: %d now, %d at the audit, %d refused by a curated "
        "correction. The difference must be exactly the refusals — anything else is a "
        "mapping lost without a reason."
        % (summary["components_with_bigg"], baseline["components_with_bigg"], refused))


def test_n_in_biggr_is_honest(summary):
    """n_in_biggr counts components with in_biggr true — 0 records disagreed."""
    assert summary["n_in_biggr_mismatch"] == [], summary["n_in_biggr_mismatch"][:5]


def test_ids_are_unique_and_match_filenames(corpus_ids, summary):
    assert len(corpus_ids) == len(set(corpus_ids))
    assert summary["id_filename_mismatch"] == []


def test_every_record_is_valid_json(summary):
    assert summary["json_errors"] == [], summary["json_errors"][:5]


def test_coverage_json_reproduces_the_records(repo, corpus_dir, is_full_corpus):
    """data/coverage.json must be exactly what the per-medium coverage blocks say.

    The audit reproduced this with 0 disagreements; if it ever drifts, the site's
    central honesty artifact is describing a corpus that no longer exists.
    """
    if not is_full_corpus:
        pytest.skip("coverage.json describes the shipped corpus only")
    p = os.path.join(repo, "data", "coverage.json")
    if not os.path.exists(p):
        pytest.skip("data/coverage.json not present")
    with open(p, encoding="utf-8") as fh:
        cov = json.load(fh)
    rows = cov["media"] if isinstance(cov, dict) and "media" in cov else cov
    by_id = {r["id"]: r for r in rows} if isinstance(rows, list) else rows

    disagree = []
    checked = 0
    for fp in sorted(glob.glob(os.path.join(corpus_dir, "*.json"))):
        with open(fp, encoding="utf-8") as fh:
            rec = json.load(fh)
        row = by_id.get(rec["id"])
        if row is None:
            disagree.append((rec["id"], "missing from coverage.json"))
            continue
        checked += 1
        for k in ("n_compounds", "n_covered", "n_uncovered", "pct_covered"):
            a = (rec.get("coverage") or {}).get(k)
            b = row.get(k) if isinstance(row, dict) else None
            if b is not None and a != b:
                disagree.append((rec["id"], k, a, b))
    assert checked > 0
    assert not disagree, "coverage.json disagrees with %d records, e.g. %s" % (
        len(disagree), disagree[:5])


def test_index_json_matches_the_corpus(repo, corpus_ids, is_full_corpus):
    if not is_full_corpus:
        pytest.skip("data/index.json describes the shipped corpus only")
    with open(os.path.join(repo, "data", "index.json"), encoding="utf-8") as fh:
        idx = json.load(fh)
    assert idx["count"] == len(idx["media"])
    assert idx["count"] == len(corpus_ids), (
        "index.json says %d media, the corpus holds %d" % (idx["count"], len(corpus_ids)))
    assert {r["id"] for r in idx["media"]} == set(corpus_ids), (
        "index.json and data/media disagree on WHICH media exist, not just how many")


def test_every_bigg_metabolite_resolves_in_the_mapping_dictionary(stream, bigg_dict):
    """A BiGG id that is not in the repo's own dictionary is not a BiGG id.

    Known offender: cdm_lactobacillaceae ships 20 retired single-underscore ids
    (MAP-09 / SCHEMA-01). They are listed here so the number cannot grow silently.
    """
    KNOWN = {"cdm_lactobacillaceae"}
    offenders = {}
    for mid, rec in stream():
        for c in rec.get("components") or []:
            b = c.get("bigg_metabolite")
            if b and b not in bigg_dict:
                offenders.setdefault(mid, set()).add(b)
    unexpected = {k: sorted(v) for k, v in offenders.items() if k not in KNOWN}
    assert not unexpected, ("media carrying BiGG ids absent from "
                            "tools/bigg_metabolite_dict.json: %s" % unexpected)


def test_derived_artifacts_agree_on_how_many_media_exist(repo, is_full_corpus):
    """STALE-01: media_stats.json and presence_matrix.json were 1,128 media stale.

    This is the identity that would have caught it, and it also asserts the id
    SETS match where they are available — 133 ghosts and 1,261 missing records
    would survive a pure count check whenever they happened to cancel.
    """
    if not is_full_corpus:
        pytest.skip("derived artifacts describe the shipped corpus only")
    counts = {}
    n_media = len(glob.glob(os.path.join(repo, "data", "media", "*.json")))
    counts["data/media/*.json"] = n_media
    for rel, key in (("data/index.json", "count"),
                     ("data/stats.json", "count"),
                     ("data/media_stats.json", "total"),
                     ("data/presence_matrix.json", "n_media"),
                     ("data/api/manifest.json", "catalog_count")):
        p = os.path.join(repo, rel)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                counts[rel] = json.load(fh).get(key)
    disagreeing = {k: v for k, v in counts.items() if v != n_media}
    assert not disagreeing, (
        "derived artifacts disagree with the corpus (%d media): %s" % (n_media, disagreeing))
