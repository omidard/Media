"""
The build is runnable from the repository, and CI commits what it claims to.

Four defects the independent verifier found, each pinned here so it cannot come
back quietly:

  (c) `make derived` rewrites all of data/web/*, data/MANIFEST.json sha256-hashes
      those files, every page reads them — and the CI commit step did not stage
      them. The first run would have committed a manifest describing a payload it
      had not committed, and nothing in the repository could have noticed.
  (d) the workflow's `paths:` trigger filter named tools/enrich_coverage.py, which
      `make derived` no longer runs, and omitted tools/build_coverage_index.py and
      tools/build_web_payload.py, which it does — so editing either builder
      rebuilt nothing.
  (e) data/MANIFEST.json credited tools/enrich_coverage.py with data/coverage.json
      after authorship moved to tools/build_coverage_index.py: a provenance error
      in the one file whose entire job is provenance.
  (f) `make stages` and `make stages-sample` were documented as runnable and both
      failed, because the chain's only input was an untracked archive on one
      machine — finding PIPE-01 (builders pointing at a deleted scratchpad)
      recreated one level up, in the targets that exist to fix it.
"""
import json
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import baseline as baseline_mod          # noqa: E402
import build_ci_paths                    # noqa: E402
import build_manifest                    # noqa: E402

WORKFLOWS = os.path.join(REPO, ".github", "workflows")
BUILD_API = os.path.join(WORKFLOWS, "build-api.yml")
TESTS_YML = os.path.join(WORKFLOWS, "tests.yml")
MAKEFILE = os.path.join(REPO, "Makefile")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def manifest():
    with open(os.path.join(REPO, "data", "MANIFEST.json"), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------- (f) input


def test_chain_input_is_committed_and_intact():
    """(f) The archive the chain consumes is in the repository, and is what it says."""
    meta = baseline_mod.load_meta()
    archive = os.path.join(REPO, meta["archive"])
    assert os.path.exists(archive), (
        "%s is missing: the stage chain has no input and `make stages` cannot run "
        "from a clone" % meta["archive"])
    assert baseline_mod.sha256_file(archive) == meta["archive_sha256"]
    assert meta["n_records"] == 13515


def test_chain_input_is_tracked_by_git():
    """An input that is not committed is not an input a fresh clone has."""
    meta = baseline_mod.load_meta()
    rc = subprocess.run(["git", "-C", REPO, "ls-files", "--error-unmatch",
                         meta["archive"]], capture_output=True).returncode
    assert rc == 0, ("%s exists but is not tracked — the chain input must ship with "
                     "the repository, which is the whole of finding (f)"
                     % meta["archive"])


def test_chain_does_not_default_to_the_promoted_corpus():
    """(f) The chain must not be fed its own output.

    data/media is what the chain PRODUCES once `make promote` has run. Feeding it
    back in is not a build: stage 10 counted 906 non-BiGG fallbacks against 913
    unmapped components and the chain aborted on its first stage.
    """
    src = read(os.path.join(REPO, "tools", "stages", "run_stages.py"))
    assert "baseline.ensure(" in src, (
        "run_stages.py must default its input to the committed chain input")
    assert not re.search(r"args\.in_dir\s*=\s*args\.in_dir\s*or\s*FROZEN", src), (
        "run_stages.py defaults the chain input to data/media again")

    sample = read(os.path.join(REPO, "tools", "stages", "make_sample.py"))
    assert "baseline.ensure(" in sample, (
        "make_sample.py must draw the sample from the chain input, not from the "
        "promoted corpus")


def test_documented_build_commands_name_no_path_outside_the_repository():
    """(f) generalised: a recipe or CI step may not depend on a machine-local path.

    Only executable lines are checked — Makefile recipes and workflow `run:` bodies.
    Prose may name the old backup archive as history; a command may not read it.
    """
    offenders = []
    for line in read(MAKEFILE).splitlines():
        if not line.startswith("\t"):
            continue
        body = line[1:].lstrip("@-")
        for m in re.finditer(r"(?<![\w./$)-])(/[A-Za-z][\w./-]+|~/[\w./-]+)", body):
            offenders.append(("Makefile", body.strip(), m.group(1)))
    for wf in (BUILD_API, TESTS_YML):
        for line in read(wf).splitlines():
            s = line.strip()
            if s.startswith("#") or not s:
                continue
            for m in re.finditer(r"(?<![\w./$)-])(~/[\w./-]+)", s):
                offenders.append((os.path.basename(wf), s, m.group(1)))
    assert not offenders, (
        "a documented build command depends on a path outside the repository:\n"
        + "\n".join("  %s: %s  ->  %s" % o for o in offenders))


# ---------------------------------------------------------------- (d) trigger list


def test_workflow_trigger_paths_match_the_makefile():
    """(d) The trigger list is generated; drift from `make derived` must fail."""
    paths, problems = build_ci_paths.compute()
    assert not problems, "\n".join(problems)
    have = build_ci_paths.current_block(read(BUILD_API))
    assert have is not None, "build-api.yml lost its generated block markers"
    assert have == build_ci_paths.render(paths), (
        "the workflow trigger list is out of date — run `make ci-paths`")


def test_every_builder_make_derived_runs_is_a_trigger():
    """The concrete form of (d), stated as the fact rather than as the mechanism."""
    targets = build_ci_paths.parse_makefile()
    scripts = set(build_ci_paths.scripts_of_target(targets, "derived"))
    assert "tools/build_coverage_index.py" in scripts
    assert "tools/build_web_payload.py" in scripts
    block = build_ci_paths.current_block(read(BUILD_API))
    for s in scripts:
        assert '"%s"' % s in block, "%s is run by `make derived` but triggers nothing" % s


def test_no_trigger_path_is_an_artifact_the_job_commits():
    """Loop safety, structurally: the job must not trigger on what it writes."""
    with open(os.path.join(REPO, "data", "MANIFEST.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    block = build_ci_paths.current_block(read(BUILD_API))
    listed = set(re.findall(r'-\s+"([^"]+)"', block))
    for rel in man["artifacts"]:
        if rel.endswith("/"):
            continue
        assert rel not in listed, (
            "%s is both a trigger and an artifact this job commits — the job can "
            "re-trigger itself" % rel)


# ------------------------------------------------------------- (c) what CI stages


def test_ci_stages_the_manifest_artifact_list_not_a_hand_written_one():
    """(c) The hand-written `git add` list is how data/web went uncommitted."""
    src = read(BUILD_API)
    assert "build_manifest.py --paths" in src, (
        "the commit step must derive what it stages from data/MANIFEST.json")
    assert "--check-tree" in src, (
        "the commit step must verify the manifest against the committed tree")
    add_lines = [l.strip() for l in src.splitlines()
                 if re.match(r"^\s*git add ", l)]
    for line in add_lines:
        assert line in ("git add data/MANIFEST.json",), (
            "hand-listed `git add` in the workflow: %r. The list must come from "
            "the manifest, or the next artifact goes missing the way data/web did"
            % line)
    assert " -A" not in src and "git add ." not in src


def test_web_payload_is_in_what_ci_stages(manifest):
    """(c) restated as the fact: the browser payload is staged."""
    staged = build_manifest.artifact_paths(manifest)
    for name in ("catalog", "summary", "compounds", "families", "tombstones"):
        rel = "data/web/%s.json" % name
        assert rel in staged, "%s would not be committed by CI" % rel


def test_manifest_declares_every_published_payload_file(manifest):
    """A new payload file must be declared, or CI will not stage it either."""
    problems = build_manifest.check_complete(manifest)
    assert not problems, "\n".join(problems)


def test_ci_asserts_the_build_did_not_write_the_corpus():
    src = read(BUILD_API)
    assert "git diff --quiet -- data/media" in src, (
        "the workflow must assert that `make derived` left data/media alone")


# ----------------------------------------------------------- (e) generator truth


def test_every_manifest_generator_exists_and_writes_its_artifact(manifest):
    """(e) The manifest named a script that no longer produces the file."""
    problems = build_manifest.check_attribution(manifest)
    assert not problems, "\n".join(problems)


def test_coverage_json_is_credited_to_the_script_that_builds_it():
    """(e), pinned by name: the attribution that was wrong."""
    gens = dict((rel, gen) for rel, gen, _inputs, _how in build_manifest.ARTIFACTS)
    assert gens["data/coverage.json"] == "tools/build_coverage_index.py"
    makefile = read(MAKEFILE)
    assert "tools/build_coverage_index.py" in makefile
    derived = build_ci_paths.scripts_of_target(build_ci_paths.parse_makefile(), "derived")
    assert "tools/enrich_coverage.py" not in derived, (
        "enrich_coverage.py is back in `make derived`; if that is intended, the "
        "manifest attribution and the trigger list must follow it")


def test_manifest_matches_the_committed_tree(manifest):
    """(c)+(e) together: the manifest must describe what git actually holds."""
    if subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                      capture_output=True).returncode != 0:
        pytest.skip("not a git checkout")
    assert build_manifest.check_tree(manifest) == 0
