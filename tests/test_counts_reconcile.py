"""One catalogue, one total.

Four different totals ship at once (COV-02, PROV-11, COV-06, NM-20): 13,515 on disk and in
index.json, 13,073 in the orphaned stats.json, 12,387 in media_stats.json and
presence_matrix.json, 11,367 in the README. The site renders a 13,515 headline above a
category doughnut summing to 12,387.

These tests define the corpus on disk as the authority — the only total that is computed
rather than typed — and check every other shipped artifact against it. They are EXPECTED TO
FAIL until the rebuild stage regenerates the derived artifacts; a failing test with real
output is the honest state, and it becomes the gate that stops the totals diverging again.

THE SAME DEFECT, ONE SCALE DOWN. COV-02 was four totals for one catalogue; the corners held
it for the smaller numbers. 14,341 was the concentration denominator until 296 values that
were an absence encoded as 0.0 were nulled and 10 were newly derived; the corrected 14,055
reached data/index.json and a typed 14,341 stayed in LICENSE, NOTICE, README.md,
PROVENANCE.md, tools/licenses.tsv and the shipped methods.html. "The literature records"
named five different populations, sized 1,371 / 1,456 / 1,457 / 1,459 / 1,460, and one
document stated 1,456 where the measurement is 1,371. build_index.py now measures all of
them into data/index.json (`concentration_provenance`, `literature_populations`), and
tools/verify_counts.check_stated_statistics checks every document against it — including
that a literature count sits next to the predicate that says WHICH population it counts.

Run just the gate:  python3 tools/verify_counts.py
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import verify_counts  # noqa: E402


@pytest.fixture(scope="module")
def results(request):
    data_dir = os.path.join(REPO, "data")
    readme = os.path.join(REPO, "README.md")
    authoritative, rows = verify_counts.check(data_dir, readme)
    return authoritative, {r["check"]: r for r in rows}


def test_the_authoritative_count_is_computed_from_the_corpus(results):
    authoritative, _ = results
    assert authoritative > 0


@pytest.mark.parametrize("name", [
    "data/index.json count",
    "data/index.json media rows",
    "data/index.json by_category keys",
    "data/index.json by_category values",
    "data/media_stats.json total",
    "data/media_stats.json by_category keys",
    "data/presence_matrix.json n_media",
    "data/stats.json count",
    "data/stats.json by_category",
    "README media totals",
    # The same defect one scale down: a statistic typed into prose that no generator
    # owns. 14,341 was the concentration denominator until 296 absences encoded as 0.0
    # were nulled; the corrected 14,055 reached data/index.json and six documents kept
    # the old one. "The literature records" named five populations sized 1,371 / 1,456
    # / 1,457 / 1,459 / 1,460, and one document stated 1,456 where 1,371 is measured.
    "every stated concentration denominator is the measured one",
    "every stated concentration numerator is a measured one",
    "every stated concentration percentage is the measured one",
    "every stated component denominator is the measured one",
    "every stated literature count names the population it counts",
    "every stated literature count equals its population's measurement",
    "data/index.json field_renames[].measured is populated",
    "data/api/manifest.json field_renames[].measured is populated",
    "data/MANIFEST.json permanently-unreproducible count",
])
def test_every_shipped_total_agrees_with_the_corpus(results, name):
    _, rows = results
    r = rows.get(name)
    if r is None:
        pytest.skip("%s: artifact not present in this tree" % name)
    assert r["ok"], "%s — expected %s, actual %s%s" % (
        name, r["expected"], r["actual"], ("; " + r["note"]) if r["note"] else "")
