"""No published payload carries an en-dash or an em-dash.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
The house standard bans both, absolutely, in visible copy. All 13,515 records
carried at least one and about one record page in six rendered one: the medium's
title on the record sheet, the Formulation reference, the decomposition citations,
the results-table name column, four family member names, and the header comment of
the COBRApy snippet a reader copies.

They were never quotations. Every one is a join this repository mints itself
("<name> - <citation>", "<name> - in-silico approximation (aerobic)"), and
tools/curate_name_formatting.py listed the em dash beside the German O-umlaut and
the chemical middot as "legitimate non-ASCII ... left alone". It was an explicit
exemption, so this is a rule that was never wired in rather than a fix that
regressed.

WHY THIS TEST PARSES AND DOES NOT GREP
--------------------------------------
tests/test_defects.py::test_no_shipped_record_carries_an_en_or_em_dash walks
data/media only, through the `stream` fixture, so families.json, catalog.json,
refs.json and index.json were outside any check: clean every record, flip that test
green, and 247 + 8 + 1 + 277 dash-bearing strings still ship and still render in
the results table.

And data/index.json writes its dashes ESCAPED, as \\u2014. `open().read().count()`
reports 0 for that file while it holds 273 em-dashes and 4 en-dashes, so a gate
built on the raw text passes it dirty. This one loads the JSON and re-encodes with
ensure_ascii=False.
"""
import glob
import json
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = re.compile(r"[–—]")

PAYLOADS = [
    os.path.join(REPO, "data", "web", "families.json"),
    os.path.join(REPO, "data", "web", "catalog.json"),
    os.path.join(REPO, "data", "web", "summary.json"),
    os.path.join(REPO, "data", "web", "compounds.json"),
    os.path.join(REPO, "data", "web", "twins.json"),
    os.path.join(REPO, "data", "web", "tombstones.json"),
    os.path.join(REPO, "data", "refs.json"),
    os.path.join(REPO, "data", "index.json"),
]


def _dashes(obj, path=""):
    """Every dash-bearing string, with the path it sits at."""
    if isinstance(obj, str):
        return [(path, obj)] if DASH.search(obj) else []
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            out += _dashes(k, path + ".<key>")
            out += _dashes(v, path + "." + str(k))
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            out += _dashes(v, path + "[]")
        return out
    return []


@pytest.mark.parametrize("path", PAYLOADS, ids=lambda p: os.path.basename(p))
def test_no_published_payload_carries_an_en_or_em_dash(path):
    if not os.path.exists(path):
        pytest.skip("%s is not built in this tree" % os.path.basename(path))
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    hits = _dashes(payload)
    assert not hits, (
        "%s carries %d dash-bearing string(s). e.g. %s"
        % (os.path.relpath(path, REPO), len(hits),
           [(p, s[:90]) for p, s in hits[:3]]))


def test_no_shipped_record_carries_an_en_or_em_dash():
    """The corpus itself, read as bytes, so an escape cannot hide one either."""
    files = sorted(glob.glob(os.path.join(REPO, "data", "media", "*.json")))
    if not files:
        pytest.skip("no corpus in this tree")
    hits = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        if DASH.search(json.dumps(rec, ensure_ascii=False)):
            hits.append(os.path.basename(path)[:-5])
        if len(hits) > 5:
            break
    assert not hits, (
        "%d+ of the %d shipped records contain U+2013 or U+2014. e.g. %s"
        % (len(hits), len(files), hits[:3]))


def test_the_mint_sites_no_longer_emit_one():
    """The corpus is a frozen snapshot, so the stage is the only fix it can get.

    Everything that still GENERATES a name or a citation must stop minting them,
    or the next rebuild reintroduces what the stage removes.
    """
    # Every file that writes a string INTO a record, not the two that were
    # remembered. tools/curate_wellknown_media.py mints the REF_* citations that
    # become provenance.wellknown_reference (17 of them carried one), and
    # tools/complex_ingredients.py mints the decomposition_ref sentences, which is
    # the single largest population: 26,527 components carry one.
    for rel in ("tools/laboratory_media.py", "tools/base_media.py",
                "tools/curate_wellknown_media.py", "tools/complex_ingredients.py",
                "tools/formulate_base_media.py", "tools/usda/usda_media.py",
                "tools/build_food_media_v2.py"):
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        # Comments are prose about the defect and may quote it; the check is on
        # the string literals that become published names.
        emitted = [ln for ln in body.splitlines()
                   if DASH.search(ln) and not ln.lstrip().startswith("#")]
        assert not emitted, (
            "%s still mints a dash into a published string: %s"
            % (rel, [ln.strip()[:100] for ln in emitted[:3]]))
