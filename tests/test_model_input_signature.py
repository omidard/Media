"""Two records a solver cannot tell apart must hash the same.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
`_hash` in tools/model_input.py was
`sha256(json.dumps(sorted(rows), default=str))`. json.dumps renders the int -1000
as `-1000` and the float -1000.0 as `-1000.0`, so two records whose Python triple
sets compare EQUAL hashed differently. The corpus stores both spellings of the same
bound because different builders wrote different literals for the same mineral, so
the split was not exotic: it broke 130 groups covering 632 media.

The published consequence, in the field this resource exists to expose:

    published (the broken hash)  sharing 6827  unique 6688  groups 1623  distinct 8311
    ground truth (set equality)  sharing 7012  unique 6503  groups 1663  distinct 8166

and 185 records were served with `model_input_twins = 0` beside the published
column note "0 means this record's model input is unique in the library", each of
them having a set-equal twin. usda_171727 was published as unique while
usda_168395, whose triple set is equal to it, was published with 38 twins.

The module's own PRIMARY_DEFINITION, republished verbatim in summary.json and
twins.json, says the comparison is over "the set of (exchange reaction, lower
bound, upper bound) triples", and calls records sharing one "indistinguishable to a
solver". -1000 and -1000.0 are the same constraint to any solver, and the documented
adoption path (`-c["lower_bound"]`) builds the identical medium dict from either.
So the code contradicted the definition the site publishes, not the reverse.

WHY THE CORPUS-WIDE TEST IS HERE AND NOT A PAYLOAD CHECK
--------------------------------------------------------
The suite already compared catalog.json's per-record twin counts against
catalog.json's own degeneracy block, and twins.json against itself. Both sides come
from the same hash, so they agreed while both were wrong: a payload
self-consistency check dressed as a correctness check. These assertions are grounded
outside the hash, in Python set equality over the triples.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_PAIR = ("usda_168395", "usda_171727")


def _triples(rec):
    return frozenset(
        (c.get("exchange"), c.get("lower_bound"), c.get("upper_bound"))
        for c in rec.get("components") or [] if c.get("exchange"))


def _load(corpus_dir, mid):
    path = os.path.join(corpus_dir, mid + ".json")
    if not os.path.exists(path):
        pytest.skip("%s is not in this corpus" % mid)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_seeded_pair_hashes_the_same(corpus_dir):
    """The worked example, so a regression names a record rather than a count.

    These two differ in exactly one place: EX_mn2_e carries (-1000.0, 1000.0) in one
    and (-1000, 1000.0) in the other. Same constraint, two spellings.
    """
    import model_input

    a, b = (_load(corpus_dir, m) for m in SEED_PAIR)
    assert _triples(a) == _triples(b), (
        "precondition failed: %s and %s no longer hand a model the same triple set, "
        "so this pair can no longer test the hash" % SEED_PAIR)
    assert model_input.signature(a) == model_input.signature(b), (
        "%s and %s hand a model an identical constraint set and hash differently. "
        "A numeric bound written as an int and as a float is the same constraint to "
        "a solver and must not split a group." % SEED_PAIR)


def test_the_signature_partitions_the_corpus_the_way_the_definition_says(
        corpus_dir, corpus_ids, stream):
    """The property the published definition claims, over the whole corpus.

    Group every record by the Python set of its triples, group it again by
    signature(), and require the two partitions to be identical. Grounded outside
    the hash, so it cannot agree with a broken hash the way the payload checks did.
    """
    import model_input

    by_set = {}
    by_sig = {}
    for mid, rec in stream():
        by_set.setdefault(_triples(rec), []).append(mid)
        by_sig.setdefault(model_input.signature(rec), []).append(mid)
    part_set = sorted(sorted(v) for v in by_set.values())
    part_sig = sorted(sorted(v) for v in by_sig.values())
    if part_set != part_sig:
        split = [g for g in part_set if g not in part_sig]
        n_media = sum(len(g) for g in split)
        pytest.fail(
            "signature() splits %d set-equal group(s) covering %d media, so the "
            "published degeneracy numbers are wrong in the direction that flatters "
            "the library. First three: %s"
            % (len(split), n_media, split[:3]))


def test_no_record_is_published_as_unique_while_it_has_a_set_equal_twin(
        repo, corpus_dir, stream, is_full_corpus):
    """The per-record claim, read back off the shipped payload.

    catalog.json publishes `model_input_twins` with the column note "0 means this
    record's model input is unique in the library", and 185 rows carried a 0 while a
    set-equal twin existed.
    """
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload against the shipped corpus")
    path = os.path.join(repo, "data", "web", "catalog.json")
    if not os.path.exists(path):
        pytest.skip("the browser payload is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        cat = json.load(fh)
    i_id = cat["columns"].index("id")
    i_tw = cat["columns"].index("model_input_twins")
    published = {r[i_id]: r[i_tw] for r in cat["rows"]}

    by_set = {}
    for mid, rec in stream():
        by_set.setdefault(_triples(rec), []).append(mid)
    truth = {}
    for members in by_set.values():
        for mid in members:
            truth[mid] = len(members) - 1

    liars = [(mid, truth[mid]) for mid, n in published.items()
             if n == 0 and truth.get(mid, 0) > 0]
    assert not liars, (
        "%d record(s) are published as having a unique model input while a set-equal "
        "twin exists. First five, as (id, true twin count): %s"
        % (len(liars), liars[:5]))


def test_the_published_degeneracy_block_matches_set_equality(
        repo, stream, is_full_corpus):
    """The library-wide numbers, against the same ground truth."""
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload against the shipped corpus")
    path = os.path.join(repo, "data", "web", "summary.json")
    if not os.path.exists(path):
        pytest.skip("the browser payload is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        block = json.load(fh)["model_input_degeneracy"]

    by_set = {}
    for mid, rec in stream():
        by_set.setdefault(_triples(rec), []).append(mid)
    groups = [v for v in by_set.values() if len(v) > 1]
    sharing = sum(len(g) for g in groups)
    n = sum(len(v) for v in by_set.values())
    want = {
        "n_media_sharing_a_model_input": sharing,
        "n_media_with_a_unique_model_input": n - sharing,
        "n_groups": len(groups),
        "n_distinct_model_inputs": len(by_set),
    }
    got = {k: block.get(k) for k in want}
    assert got == want, (
        "the published degeneracy block does not match set equality over the "
        "corpus. published=%s truth=%s" % (got, want))
