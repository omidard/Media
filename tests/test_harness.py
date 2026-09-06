"""
Tests for the stage harness itself — the machinery every correction depends on.

If stagelib silently dropped a record, or the runner failed to notice a stage that
mutated its input, every downstream correction would inherit the damage. So the
harness is tested against planted violations, not just happy paths.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = os.path.join(REPO, "tools", "stages")
sys.path.insert(0, STAGES)

import invariants  # noqa: E402
import stagelib    # noqa: E402
from run_stages import check_registry  # noqa: E402


def _rec(mid="m1", **kw):
    base = {"id": mid, "name": "M", "category": "laboratory", "description": "",
            "namespace": "bigg",
            "provenance": {"source_type": "database", "citation": "c"},
            "components": [], "n_components": 0, "n_mapped": 0, "n_in_biggr": 0}
    base.update(kw)
    return base


def _corpus(tmp_path, recs):
    d = tmp_path / "in"
    d.mkdir(parents=True, exist_ok=True)
    for r in recs:
        (d / (r["id"] + ".json")).write_text(json.dumps(r, indent=1), encoding="utf-8")
    return str(d)


# ----------------------------------------------------------------- registry


def test_stage_registry_and_filesystem_agree():
    """An unregistered stage would silently never run. That must be a hard error."""
    assert check_registry(verbose=False) == []


def test_every_registered_stage_declares_findings_and_an_owner():
    reg = stagelib.load_registry()
    for s in reg["stages"]:
        assert s.get("owner"), s["id"]
        assert s.get("findings"), "%s must name the findings it closes" % s["id"]
        assert "may_change_record_count" in s, s["id"]


def test_reserved_ranges_cover_every_registered_stage():
    reg = stagelib.load_registry()
    ranges = []
    for r in reg["reserved_ranges"]:
        lo, hi = r["range"].split("-")
        ranges.append((int(lo), int(hi)))
    for s in reg["stages"]:
        n = int(s["id"][:2])
        assert any(lo <= n <= hi for lo, hi in ranges), s["id"]


# ------------------------------------------------------------------ stagelib


def test_write_record_is_deterministic(tmp_path):
    r = _rec()
    p1, p2 = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    stagelib.write_record(p1, r)
    stagelib.write_record(p2, stagelib.read_record(p1))
    assert open(p1, "rb").read() == open(p2, "rb").read()


def test_run_stage_refuses_to_write_the_frozen_corpus(tmp_path):
    src = _corpus(tmp_path, [_rec()])
    rc = stagelib.run_stage("t", "1", lambda rec, rep: False,
                            argv=["--in", src, "--out", stagelib.FROZEN_CORPUS])
    assert rc == 2


def test_run_stage_refuses_in_equals_out(tmp_path):
    src = _corpus(tmp_path, [_rec()])
    rc = stagelib.run_stage("t", "1", lambda rec, rep: False,
                            argv=["--in", src, "--out", src])
    assert rc == 2


def test_run_stage_copies_every_record_through(tmp_path):
    src = _corpus(tmp_path, [_rec("a"), _rec("b"), _rec("c")])
    out = str(tmp_path / "out")
    rep = str(tmp_path / "r.json")
    rc = stagelib.run_stage("t", "1", lambda rec, r: False,
                            argv=["--in", src, "--out", out, "--report", rep])
    assert rc == 0
    assert sorted(os.listdir(out)) == ["a.json", "b.json", "c.json"]
    r = json.load(open(rep))
    assert r["n_in"] == r["n_out"] == 3 and r["n_changed"] == 0


def test_a_failed_assertion_makes_the_stage_exit_nonzero(tmp_path):
    src = _corpus(tmp_path, [_rec()])
    out = str(tmp_path / "out")

    def fin(rep):
        rep.assert_eq("deliberately_false", 1, 2)

    rc = stagelib.run_stage("t", "1", lambda rec, r: False, finalize=fin,
                            argv=["--in", src, "--out", out,
                                  "--report", str(tmp_path / "r.json")])
    assert rc == 1


def test_a_raising_stage_exits_nonzero_and_still_writes_a_report(tmp_path):
    src = _corpus(tmp_path, [_rec()])
    out = str(tmp_path / "out")
    rep = str(tmp_path / "r.json")

    def boom(rec, r):
        raise ValueError("input violates my assumption")

    rc = stagelib.run_stage("t", "1", boom, argv=["--in", src, "--out", out, "--report", rep])
    assert rc == 1
    assert "ValueError" in json.load(open(rep))["errors"][0]


def test_a_record_whose_id_disagrees_with_its_filename_is_fatal(tmp_path):
    src = _corpus(tmp_path, [_rec("a")])
    # rename the file so stem != id
    os.rename(os.path.join(src, "a.json"), os.path.join(src, "b.json"))
    rc = stagelib.run_stage("t", "1", lambda rec, r: False,
                            argv=["--in", src, "--out", str(tmp_path / "out"),
                                  "--report", str(tmp_path / "r.json")])
    assert rc == 1


def test_stamp_records_what_changed():
    r = _rec()
    stagelib.stamp(r, "10_normalize_schema", "1.0.0", ["version:int->str"])
    t = r["provenance"]["transforms"][0]
    assert t["stage"] == "10_normalize_schema" and t["changes"] == ["version:int->str"]


def test_counters_carry_their_denominator():
    rep = stagelib.Report("s", "1", "i", "o")
    rep.count("fixed", 3, of=100)
    assert rep.counters["fixed"] == {"n": 3, "of": 100}


# ---------------------------------------------------------------- invariants


def test_invariants_catch_a_broken_exchange(tmp_path):
    good = _rec("a", components=[{"name": "x", "bigg_metabolite": "glc__D",
                                  "exchange": "EX_glc__D_e", "in_biggr": True}],
                n_components=1, n_mapped=1, n_in_biggr=1)
    bad = json.loads(json.dumps(good))
    bad["id"] = "b"
    bad["components"][0]["exchange"] = "EX_glc__L_e"
    d = _corpus(tmp_path, [good, bad])
    s = invariants.summarize(d)
    assert s["exchange_identity_bad"], "U4 failed to notice a mismatched exchange"


def test_invariants_catch_a_dropped_record(tmp_path):
    before = invariants.summarize(_corpus(tmp_path, [_rec("a"), _rec("b")]))
    after = invariants.summarize(_corpus(tmp_path / "second", [_rec("a")]))
    res = invariants.check_all(before, after, {"id": "x"}, ["x"])
    u1 = next(r for r in res if r["id"] == "U1")
    assert u1["passed"] is False


def test_invariants_catch_an_undeclared_new_key(tmp_path):
    before = invariants.summarize(_corpus(tmp_path, [_rec("a")]))
    after = invariants.summarize(_corpus(tmp_path / "second", [_rec("a", surprise=1)]))
    res = invariants.check_all(before, after,
                               {"id": "x", "adds_keys": [], "removes_keys": []}, ["x"])
    u7 = next(r for r in res if r["id"] == "U7")
    assert u7["passed"] is False
    assert "surprise" in u7["observed"]["undeclared_added"]


def test_invariants_catch_a_new_empty_string(tmp_path):
    before = invariants.summarize(_corpus(tmp_path, [_rec("a", food_group=None)]))
    after = invariants.summarize(_corpus(tmp_path / "second", [_rec("a", food_group="")]))
    res = invariants.check_all(before, after,
                               {"id": "x", "adds_keys": [], "removes_keys": []}, ["x"])
    u6 = next(r for r in res if r["id"] == "U6")
    assert u6["passed"] is False


def test_enforced_from_defers_an_invariant_until_its_stage_has_run(tmp_path):
    d = _corpus(tmp_path, [_rec("a", version=1)])
    s = invariants.summarize(d)
    res = invariants.check_all(None, s, {"id": "00_baseline"}, ["00_baseline"])
    u10 = next(r for r in res if r["id"] == "U10")
    assert u10["enforced"] is False        # not enforced until 10_normalize_schema
    res2 = invariants.check_all(None, s, {"id": "10_normalize_schema"},
                                ["00_baseline", "10_normalize_schema"])
    u10b = next(r for r in res2 if r["id"] == "U10")
    assert u10b["enforced"] is True and u10b["passed"] is False


# ------------------------------------------------- the schema stage's own unit tests


def _run_norm(tmp_path, recs):
    src = _corpus(tmp_path, recs)
    out = str(tmp_path / "out")
    rep = str(tmp_path / "r.json")
    rc = subprocess.call([sys.executable, os.path.join(STAGES, "10_normalize_schema.py"),
                          "--in", src, "--out", out, "--report", rep])
    assert rc == 0, "stage exited %d" % rc
    return {f[:-5]: json.load(open(os.path.join(out, f))) for f in os.listdir(out)}, \
        json.load(open(rep))


def test_normalize_schema_recomputes_n_mapped(tmp_path):
    r = _rec("a", components=[
        {"name": "g", "bigg_metabolite": "glc__D", "exchange": "EX_glc__D_e", "in_biggr": True},
        {"name": "z", "bigg_metabolite": None, "exchange": "EX_cpd09225_e", "in_biggr": False},
    ], n_components=2, n_mapped=2, n_in_biggr=1)
    out, rep = _run_norm(tmp_path, [r])
    assert out["a"]["n_mapped"] == 1
    assert out["a"]["n_nonbigg_fallback"] == 1
    assert out["a"]["namespace"] == "mixed"
    # the fallback component is kept, never deleted
    assert len(out["a"]["components"]) == 2


def test_normalize_schema_never_infers_defined(tmp_path):
    out, _ = _run_norm(tmp_path, [_rec("a")])
    assert out["a"]["defined"] is None


def test_normalize_schema_merges_the_category_generation(tmp_path):
    out, _ = _run_norm(tmp_path, [_rec("a", category="growth_medium")])
    assert out["a"]["category"] == "laboratory"
    assert out["a"]["category_original"] == "growth_medium"


def test_normalize_schema_coerces_version_but_never_invents_one(tmp_path):
    out, _ = _run_norm(tmp_path, [_rec("a", version=1), _rec("b")])
    assert out["a"]["version"] == "1"
    assert "version" not in out["b"]          # absent stays absent, not "1.0"


def test_normalize_schema_renames_the_colliding_curation_key(tmp_path):
    out, _ = _run_norm(tmp_path, [_rec("a", curation="partial_complex")])
    assert out["a"]["formulation_class"] == "partial_complex"
    assert "curation" not in out["a"]


def test_normalize_schema_turns_empty_strings_into_null(tmp_path):
    out, _ = _run_norm(tmp_path, [_rec("a", organism_scope="", food_group="")])
    assert out["a"]["organism_scope"] is None and out["a"]["food_group"] is None


def test_normalize_schema_is_idempotent(tmp_path):
    recs = [_rec("a", category="growth_medium", version=1, curation="defined")]
    out1, _ = _run_norm(tmp_path, recs)
    out2, rep2 = _run_norm(tmp_path / "second", list(out1.values()))
    assert rep2["n_changed"] == 0
    assert out1["a"] == out2["a"]


def test_normalize_schema_reports_what_it_could_not_resolve(tmp_path):
    _, rep = _run_norm(tmp_path, [_rec("a")])
    assert "defined_unknown" in rep["unresolved"]
    assert rep["unresolved"]["defined_unknown"]["of"] == 1
