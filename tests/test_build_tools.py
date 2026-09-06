"""
Tests for the build tools' path handling and failure behaviour (PIPE-01, PIPE-02).

The original defect was not only that 19 generators pointed at a deleted directory.
It was that fixing the paths naively would turn 19 scripts that safely CRASH into
19 scripts that silently WRITE over data/media — the only surviving copy of the
corpus. These tests pin both halves: no dead path may come back, and no tool may
default its output to the frozen corpus.
"""
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import mediapaths  # noqa: E402

DEAD_SCRATCHPAD = re.compile(r"/tmp/claude-\d+/[^\"' ]*scratchpad")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "data"}


def _source_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".py", ".js")):
                yield os.path.join(root, f)


def test_no_tool_hardcodes_a_session_scratchpad_path():
    """PIPE-01: 18 files pointed into a deleted /tmp scratchpad.

    tools/mediapaths.py and tools/fetch_sources.py may MENTION the dead path in
    prose (they document the defect); no file may USE one.
    """
    offenders = {}
    for p in _source_files():
        with open(p, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                if not DEAD_SCRATCHPAD.search(line):
                    continue
                stripped = line.strip()
                is_prose = (stripped.startswith(("#", "//", "*", '"""', "'''"))
                            or os.path.basename(p) in ("mediapaths.py", "fetch_sources.py")
                            or "scratchpad" in stripped and "/..." in stripped)
                if not is_prose:
                    offenders.setdefault(os.path.relpath(p, REPO), []).append(i)
    assert not offenders, "dead scratchpad paths in use: %s" % offenders


def test_the_output_root_is_never_the_frozen_corpus():
    assert os.path.abspath(mediapaths.OUT_MEDIA) != os.path.abspath(mediapaths.FROZEN_MEDIA)
    with pytest.raises(RuntimeError):
        mediapaths.assert_not_frozen_corpus(mediapaths.FROZEN_MEDIA)


def test_roots_are_derived_from_the_file_not_from_the_cwd():
    assert mediapaths.REPO == REPO
    assert mediapaths.SOURCES.startswith(REPO) or "MEDIA_SOURCES" in os.environ


def test_a_missing_source_fails_with_actionable_guidance():
    with pytest.raises(mediapaths.MissingSource) as e:
        mediapaths.source_file("mediadive", "definitely_absent.json")
    msg = str(e.value)
    assert "status: public" in msg
    assert "fetch_sources.py mediadive" in msg
    assert "MEDIA_SOURCES=" in msg


def test_an_unrecoverable_source_says_so_instead_of_offering_a_fix():
    with pytest.raises(mediapaths.MissingSource) as e:
        mediapaths.source_file("lit", "extractions")
    msg = str(e.value)
    assert "status: lost" in msg
    assert "cannot be re-acquired" in msg
    assert "wearing the old citations" in msg or "new content" in msg


def test_build_index_refuses_to_write_an_empty_catalog(tmp_path):
    """PIPE-02: run from the wrong directory it used to write count=0 and exit 0."""
    empty = tmp_path / "media"
    empty.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    r = subprocess.run([sys.executable, os.path.join(REPO, "build_index.py"),
                        "--media", str(empty), "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "no media found" in (r.stdout + r.stderr)
    assert not (out / "index.json").exists()


def test_build_index_is_cwd_independent(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "x.json").write_text(
        '{"id":"x","name":"X","category":"laboratory","description":"",'
        '"namespace":"bigg","provenance":{"source_type":"database","citation":"c"},'
        '"components":[],"n_components":0,"n_mapped":0,"n_in_biggr":0,'
        '"coverage":{"n_compounds":0,"n_covered":0,"n_uncovered":0,"pct_covered":null}}',
        encoding="utf-8")
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, os.path.join(REPO, "build_index.py"),
                        "--media", str(media), "--out", str(out)],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (out / "index.json").exists() and (out / "stats.json").exists()


def test_build_index_does_not_fabricate_coverage(tmp_path):
    """SCHEMA-07: a record with no coverage block became pct_covered 100.0."""
    import json
    media = tmp_path / "media"
    media.mkdir()
    (media / "x.json").write_text(json.dumps(
        {"id": "x", "name": "X", "category": "laboratory", "description": "",
         "namespace": "bigg", "provenance": {"source_type": "database", "citation": "c"},
         "components": [], "n_components": 0, "n_mapped": 0, "n_in_biggr": 0}),
        encoding="utf-8")
    out = tmp_path / "out"
    subprocess.check_call([sys.executable, os.path.join(REPO, "build_index.py"),
                           "--media", str(media), "--out", str(out)])
    row = json.load(open(out / "index.json"))["media"][0]
    assert row["pct_covered"] is None
    assert row["n_uncovered"] is None


def test_build_index_does_not_truncate_citations(tmp_path):
    """SCHEMA-07: citation[:140] cut 157 citations, 11 of them mid-PMID."""
    import json
    media = tmp_path / "media"
    media.mkdir()
    long_cite = "A" * 400 + " PMID: 11204708"
    (media / "x.json").write_text(json.dumps(
        {"id": "x", "name": "X", "category": "laboratory", "description": "",
         "namespace": "bigg",
         "provenance": {"source_type": "database", "citation": long_cite},
         "components": [], "n_components": 0, "n_mapped": 0, "n_in_biggr": 0}),
        encoding="utf-8")
    out = tmp_path / "out"
    subprocess.check_call([sys.executable, os.path.join(REPO, "build_index.py"),
                           "--media", str(media), "--out", str(out)])
    row = json.load(open(out / "index.json"))["media"][0]
    assert row["citation"] == long_cite


def test_the_source_manifest_records_what_is_lost(repo):
    """The recovery ledger must state absence explicitly, not by omission."""
    import json
    p = os.path.join(repo, "data", "_sources", "MANIFEST.json")
    if not os.path.exists(p):
        pytest.skip("no source manifest yet — run tools/fetch_sources.py")
    man = json.load(open(p, encoding="utf-8"))
    for name in ("lit", "growthdb"):
        assert man["sources"].get(name, {}).get("status") == "lost", name
        assert man["sources"][name]["lost_reason"]
    for name, entry in man["sources"].items():
        assert entry.get("licence"), "%s has no licence recorded" % name


def test_the_artifact_manifest_is_current(repo):
    p = os.path.join(repo, "data", "MANIFEST.json")
    if not os.path.exists(p):
        pytest.skip("no artifact manifest yet — run tools/build_manifest.py")
    r = subprocess.run([sys.executable, os.path.join(repo, "tools", "build_manifest.py"),
                        "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# --------------------------------------------------------------- frozen fixtures
# Vendored by `python3 tools/fetch_sources.py --fixtures` from the re-acquired source
# cache, so these tests run with no network and pin the shape of the upstream inputs
# the builders parse. If an upstream changes its format, this is where it shows up.

FIXTURES = os.path.join(REPO, "tests", "fixtures")


def test_mediadive_fixture_has_the_shape_the_builder_reads():
    import json
    p = os.path.join(FIXTURES, "mediadive_detail_1.json")
    if not os.path.exists(p):
        pytest.skip("fixtures not vendored yet (make fixtures)")
    d = json.load(open(p, encoding="utf-8"))
    med = (d.get("data") or {}).get("medium")
    assert med and "name" in med and "complex_medium" in med
    sols = (d.get("data") or {}).get("solutions")
    assert isinstance(sols, list) and sols
    # the builder reads recipe rows as {compound_id, g_l, compound}
    rows = [r for s in sols for r in (s.get("recipe") or [])]
    assert rows and all("compound_id" in r for r in rows)


def test_bigg_namespace_fixture_parses_into_id_and_name():
    p = os.path.join(FIXTURES, "bigg_models_metabolites.head200.txt")
    if not os.path.exists(p):
        pytest.skip("fixtures not vendored yet (make fixtures)")
    with open(p, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        first = fh.readline().rstrip("\n").split("\t")
    assert "universal_bigg_id" in header and "name" in header
    assert len(first) == len(header)


# --------------------------------------------------- generator-level regressions
# The corrections above are only durable if the GENERATORS stop reintroducing them.
# tools/enrich_coverage.py runs on every push (make derived / CI), so if it still
# wrote the old values it would silently undo the schema stage on the next build.


def test_enrich_coverage_does_not_make_n_mapped_a_tautology():
    """SCHEMA-01 at its source: it used to set n_mapped = n_components = n_covered."""
    import enrich_coverage as EC
    med = {
        "id": "t", "name": "t", "category": "laboratory", "namespace": "bigg",
        "provenance": {"source_type": "database", "citation": "c"},
        "components": [
            {"name": "glucose", "bigg_metabolite": "glc__D", "exchange": "EX_glc__D_e",
             "lower_bound": -10.0, "upper_bound": 1000.0, "in_biggr": True,
             "mapping_method": "curated", "exchange_source": "bigg", "xref": {}},
            {"name": "mystery", "bigg_metabolite": None, "exchange": "EX_cpd09225_e",
             "lower_bound": -1.0, "upper_bound": 1000.0, "in_biggr": False,
             "mapping_method": "modelseed_fallback", "exchange_source": "modelseed",
             "xref": {}},
        ],
        "uncovered": [],
    }
    EC.enrich(med)
    assert med["n_components"] == 2
    assert med["n_mapped"] == 1, "n_mapped must count components carrying a BiGG id"
    assert med["n_nonbigg_fallback"] == 1


def test_enrich_coverage_does_not_score_an_empty_medium_as_fully_covered():
    """SCHEMA-07 at its source: `if total else 100.0` invented a perfect score."""
    import enrich_coverage as EC
    med = {"id": "t", "name": "t", "category": "laboratory", "namespace": "bigg",
           "provenance": {"source_type": "database", "citation": "c"},
           "components": [], "uncovered": []}
    EC.enrich(med)
    assert med["coverage"]["pct_covered"] is None, (
        "a medium with no compounds is unmeasured, not perfectly covered")


def test_no_bare_except_swallows_a_failure_in_the_build_tools():
    """A bare `except:` is how a builder drops records without saying so.

    tools/lit/build_lit_media.py used to answer 'extraction records in: 0' when its
    entire input directory was missing, and the MediaDive builder dropped any medium
    whose detail file would not parse.
    """
    offenders = {}
    for p in _source_files():
        if not p.endswith(".py"):
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                if re.match(r"\s*except\s*:", line):
                    offenders.setdefault(os.path.relpath(p, REPO), []).append(i)
    assert not offenders, ("bare except clauses (catch the specific exception, count "
                           "the loss, and report it): %s" % offenders)
