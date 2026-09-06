"""One catalogue, one total.

Four different totals ship at once (COV-02, PROV-11, COV-06, NM-20): 13,515 on disk and in
index.json, 13,073 in the orphaned stats.json, 12,387 in media_stats.json and
presence_matrix.json, 11,367 in the README. The site renders a 13,515 headline above a
category doughnut summing to 12,387.

These tests define the corpus on disk as the authority — the only total that is computed
rather than typed — and check every other shipped artifact against it. They are EXPECTED TO
FAIL until the rebuild stage regenerates the derived artifacts; a failing test with real
output is the honest state, and it becomes the gate that stops the totals diverging again.

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
    "data/stats.json is not a hand-maintained orphan",
    "README media totals",
])
def test_every_shipped_total_agrees_with_the_corpus(results, name):
    _, rows = results
    r = rows.get(name)
    if r is None:
        pytest.skip("%s: artifact not present in this tree" % name)
    assert r["ok"], "%s — expected %s, actual %s%s" % (
        name, r["expected"], r["actual"], ("; " + r["note"]) if r["note"] else "")
