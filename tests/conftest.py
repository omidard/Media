"""
Shared fixtures for the MediaDB test suite.

The corpus is 13,515 records / 665,582 components / 451 MB, so nothing here loads
it all into memory: tests stream it, and the aggregate facts come from one shared
pass (tools/stages/invariants.summarize) computed once per session.

Point the suite at a different corpus with:

    pytest --corpus data/_rebuild/media      # the corrected corpus from the chain
    pytest --corpus data/_rebuild/sample/media
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools", "stages"))

DEFAULT_CORPUS = os.path.join(REPO, "data", "media")


def pytest_addoption(parser):
    parser.addoption("--corpus", action="store", default=DEFAULT_CORPUS,
                     help="corpus directory of per-medium JSON records to test")
    parser.addoption("--limit", action="store", type=int, default=0,
                     help="test only the first N records (development shortcut)")


@pytest.fixture(scope="session")
def repo():
    return REPO


@pytest.fixture(scope="session")
def corpus_dir(request):
    d = os.path.abspath(request.config.getoption("--corpus"))
    if not os.path.isdir(d):
        pytest.skip("corpus directory %s does not exist" % d)
    return d


@pytest.fixture(scope="session")
def limit(request):
    return request.config.getoption("--limit") or None


@pytest.fixture(scope="session")
def corpus_ids(corpus_dir, limit):
    ids = sorted(f[:-5] for f in os.listdir(corpus_dir) if f.endswith(".json"))
    return ids[:limit] if limit else ids


@pytest.fixture(scope="session")
def stream(corpus_dir, corpus_ids):
    """Yield (id, record) for every record, one at a time."""
    def _stream():
        for mid in corpus_ids:
            with open(os.path.join(corpus_dir, mid + ".json"), encoding="utf-8") as fh:
                yield mid, json.load(fh)
    return _stream


@pytest.fixture(scope="session")
def summary(corpus_dir, limit):
    """One shared aggregate pass over the corpus (see tools/stages/invariants.py)."""
    from invariants import summarize
    return summarize(corpus_dir, limit)


@pytest.fixture(scope="session")
def baseline():
    """The measured facts this remediation started from (tests/baseline.json)."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def is_full_corpus(corpus_dir, limit, baseline):
    return (not limit) and os.path.abspath(corpus_dir) == os.path.abspath(DEFAULT_CORPUS)


@pytest.fixture(scope="session")
def bigg_dict(repo):
    with open(os.path.join(repo, "tools", "bigg_metabolite_dict.json"),
              encoding="utf-8") as fh:
        return json.load(fh)
