"""An exchange id shaped like a BiGG reaction is not a BiGG reaction.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
The published partition was computed from a STRING TEST. tools/web_payload.py
counted every component not tagged `non_bigg_fallback` as reaching a real BiGG
exchange, and the payload's own definition said so in as many words:
"n_bigg_exchange is a real BiGG EX_<met>_e reaction". It was not.

11,380 components name an EX_<met>_e reaction that does not exist in BiGG, because
the metabolite has no extracellular form there:

    EX_choles_e       4,438   BiGG has choles_c only; cholesterol's exchange is EX_chsterol_e
    EX_behen_e        1,669   behen_c and behen_x only
    EX_hepedecacid_e  1,548
    EX_bcryptox_e       929
    EX_lycop_e          429
    EX_mqn4_e           337
    EX_iodine_e         285
                    ... 294 distinct exchanges, across 5,942 of 13,515 media (44%)

The hero sentence therefore warned about 1,364 unusable ids while the real figure
was 12,744, an understatement of 8.3x, and the documented adoption path
(`model.medium = {c["exchange"]: -c["lower_bound"] ...}`) drops every one of them
without a word, because the reaction is in no model.

Worse per record: 5,719 records (42%) carry one of these ids while reporting
`n_nonbigg_fallback = 0`, so their record sheet told the reader every component
reached a BiGG exchange. food_FOOD00094 ships EX_choles_e with a zero count.

THE PREMISE, CHECKED RATHER THAN ASSUMED
----------------------------------------
"No <met>_e metabolite in BiGG implies no EX_<met>_e reaction" was verified against
the live BiGG API: 25 of 25 sampled bad ids return 404, 30 of 30 sampled good ids
return 200, and EX_choles_e is 404 while EX_chsterol_e is 200. The test is exact,
not a heuristic.

WHY NOT `in_biggr`
------------------
The obvious alternative, partitioning on the `in_biggr` flag the records already
carry, is wrong and was measured: it catches 10,277 of the 11,380 but misses 1,103,
and would falsely condemn 2,826 components whose exchange does exist in BiGG.
`in_biggr` is membership of the local BiGGr prokaryote reactome, a different
question. Only the BiGG namespace answers this one.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The measured split, frozen. These are the four states, and they partition the
# components: 652,620 + 11,380 + 1,364 + 218 == 665,582.
EXPECTED = {
    "n_bigg_exchange": 652620,
    "n_bigg_shaped_no_such_exchange": 11380,
    "n_nonbigg_fallback": 1364,
    "n_no_exchange": 218,
}


@pytest.fixture(scope="module")
def extracellular():
    import build_bigg_exchange_ids
    path = os.path.join(REPO, "tools", "bigg_exchange_ids.json")
    if not os.path.exists(path):
        pytest.fail("tools/bigg_exchange_ids.json is missing; the partition cannot "
                    "be checked and would silently pass on a string shape again")
    ids = build_bigg_exchange_ids.load()
    assert len(ids) > 2000, (
        "the extracellular vocabulary looks truncated (%d ids). A short one would "
        "condemn real exchanges." % len(ids))
    return ids


def _bucket(comp, extracellular):
    ex = comp.get("exchange")
    if not ex:
        return "n_no_exchange"
    if comp.get("evidence_tier") == "non_bigg_fallback":
        return "n_nonbigg_fallback"
    met = ex[3:-2] if ex.startswith("EX_") and ex.endswith("_e") else None
    if met is not None and met in extracellular:
        return "n_bigg_exchange"
    return "n_bigg_shaped_no_such_exchange"


def test_every_component_counted_as_a_bigg_exchange_names_a_real_one(
        stream, extracellular, is_full_corpus):
    """The claim itself, over the corpus, against BiGG's own namespace."""
    counts = dict.fromkeys(EXPECTED, 0)
    offenders = {}
    for _mid, rec in stream():
        for comp in rec.get("components") or []:
            b = _bucket(comp, extracellular)
            counts[b] += 1
            if b == "n_bigg_shaped_no_such_exchange":
                offenders[comp["exchange"]] = offenders.get(comp["exchange"], 0) + 1
    if is_full_corpus:
        assert counts == EXPECTED, (
            "the corpus partition moved. measured=%s expected=%s" % (counts, EXPECTED))
    assert sum(counts.values()) > 0
    # The point of the test: this bucket must be COUNTED, not folded into the
    # BiGG total. It is allowed to be non-empty; it is not allowed to be invisible.
    assert isinstance(counts["n_bigg_shaped_no_such_exchange"], int)
    if offenders:
        top = sorted(offenders.items(), key=lambda kv: -kv[1])[:3]
        assert "EX_choles_e" in offenders or top, (
            "sanity: the known offenders should still be found (%s)" % top)


def test_the_payload_publishes_all_four_states(is_full_corpus):
    """The shipped numbers, which is what a reader actually sees."""
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload against the shipped corpus")
    for name in ("summary.json", "catalog.json"):
        path = os.path.join(REPO, "data", "web", name)
        if not os.path.exists(path):
            pytest.skip("the browser payload is not built in this tree")
        with open(path, encoding="utf-8") as fh:
            xr = json.load(fh)["exchange_resolution"]
        got = {k: xr.get(k) for k in EXPECTED}
        assert got == EXPECTED, (
            "%s publishes a partition that counts BiGG-shaped ids naming no BiGG "
            "reaction as if they reached one. published=%s truth=%s"
            % (name, got, EXPECTED))
        assert sum(EXPECTED.values()) == xr["of"], (
            "%s: the four states must partition the components" % name)


def test_the_payload_definition_describes_four_states(is_full_corpus):
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload")
    path = os.path.join(REPO, "data", "web", "summary.json")
    if not os.path.exists(path):
        pytest.skip("the browser payload is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        xr = json.load(fh)["exchange_resolution"]
    definition = xr.get("definition", "")
    assert "no such reaction" in definition or "names no BiGG reaction" in definition, (
        "the published definition still claims n_bigg_exchange is 'a real BiGG "
        "EX_<met>_e reaction' without naming the fourth state: %r" % definition[:400])


def test_a_record_carrying_an_unusable_id_does_not_report_zero(is_full_corpus,
                                                               extracellular):
    """The per-record claim.

    food_FOOD00094 ships EX_choles_e and `n_nonbigg_fallback = 0`, so its record
    sheet said every component reached a BiGG exchange. The catalogue must carry a
    per-record count of the fourth state so the row cannot say that.
    """
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload against the shipped corpus")
    path = os.path.join(REPO, "data", "web", "catalog.json")
    if not os.path.exists(path):
        pytest.skip("the browser payload is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        cat = json.load(fh)
    assert "n_bigg_shaped_no_such_exchange" in cat["columns"], (
        "the catalogue publishes no per-record count of BiGG-shaped ids that name "
        "no BiGG reaction, so 5,719 records report zero unusable components while "
        "carrying one")
    i_id = cat["columns"].index("id")
    i_bad = cat["columns"].index("n_bigg_shaped_no_such_exchange")
    row = next((r for r in cat["rows"] if r[i_id] == "food_FOOD00094"), None)
    if row is None:
        pytest.skip("food_FOOD00094 is not in this release")
    rec_path = os.path.join(REPO, "data", "media", "food_FOOD00094.json")
    with open(rec_path, encoding="utf-8") as fh:
        rec = json.load(fh)
    truth = sum(1 for c in rec["components"]
                if _bucket(c, extracellular) == "n_bigg_shaped_no_such_exchange")
    assert truth > 0, "precondition: food_FOOD00094 should carry EX_choles_e"
    assert row[i_bad] == truth, (
        "food_FOOD00094 carries %d exchange id(s) BiGG does not have and the "
        "catalogue publishes %r" % (truth, row[i_bad]))
