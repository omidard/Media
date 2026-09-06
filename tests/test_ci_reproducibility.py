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


def test_every_script_a_make_target_runs_is_committed():
    """(f) generalised: a documented command must work from a clone.

    The chain input was not the only thing a fresh clone did not have; a recipe that
    invokes an untracked script fails there for exactly the same reason. Both are
    'the repository does not contain what the build says to run'.
    """
    missing, untracked = [], []
    for line in read(MAKEFILE).splitlines():
        if not line.startswith("\t"):
            continue
        for m in re.finditer(r"\$\(PY\)\s+([^\s;]+\.py)", line):
            rel = m.group(1)
            if not os.path.exists(os.path.join(REPO, rel)):
                missing.append(rel)
            elif subprocess.run(["git", "-C", REPO, "ls-files", "--error-unmatch", rel],
                                capture_output=True).returncode != 0:
                untracked.append(rel)
    assert not missing, ("a Makefile recipe runs a script that does not exist: %s"
                         % sorted(set(missing)))
    assert not untracked, (
        "a Makefile recipe runs a script that is not committed, so the target fails "
        "from a fresh clone: %s" % sorted(set(untracked)))


def test_documented_build_commands_name_no_path_outside_the_repository():
    """(f) generalised: a recipe or CI step may not depend on a machine-local path.

    Only executable lines are checked — Makefile recipes and workflow `run:` bodies.
    Prose may name the old backup archive as history; a command may not read it.
    """
    # /tmp and system paths are fine — they are scratch that any machine has. A path
    # under a user's or an operator's data root is not: that is the shape the chain
    # input had (/data/media_curate_backups/...), and it is why `make stages` worked
    # on one machine and nowhere else.
    machine_local = re.compile(r"(?<![\w./$)-])(~/[\w./-]+|/(?:data|home|Users|mnt|media)/[\w./-]+)")
    offenders = []
    for line in read(MAKEFILE).splitlines():
        if not line.startswith("\t"):
            continue
        body = line[1:].lstrip("@-")
        for m in machine_local.finditer(body):
            offenders.append(("Makefile", body.strip(), m.group(1)))
    for wf in (BUILD_API, TESTS_YML):
        for line in read(wf).splitlines():
            s = line.strip()
            if s.startswith("#") or not s:
                continue
            for m in machine_local.finditer(s):
                offenders.append((os.path.basename(wf), s, m.group(1)))
    assert not offenders, (
        "a documented build command depends on a machine-local path:\n"
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
    staged = set(build_manifest.artifact_paths(man))
    for rel in staged:
        assert rel not in listed, (
            "%s is both a trigger and an artifact this job commits — the job can "
            "re-trigger itself" % rel)
    # Corpus paths are the opposite case and must be triggers.
    for rel in build_manifest.corpus_paths(man):
        assert rel in listed or rel + "/**" in listed, (
            "%s is corpus data every builder reads, but changing it triggers no "
            "rebuild" % rel)


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
    assert "--corpus-paths" in src and "git diff --quiet" in src, (
        "the workflow must assert that `make derived` left the corpus alone, over "
        "the corpus paths the manifest declares")


def test_corpus_and_derived_are_disjoint(manifest):
    """A path CI stages must not be a path CI is forbidden to change."""
    staged = set(build_manifest.artifact_paths(manifest))
    corpus = set(build_manifest.corpus_paths(manifest))
    assert not (staged & corpus), sorted(staged & corpus)
    assert "data/media" in corpus


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


# ------------------------------------ (c) again: the guard, seeded and made to fire
# `make preflight` ran `derived` and then `manifest-check --check-tree`, and could
# never pass: the six data/web payloads and the manifest carried a wall-clock
# built_utc, so the just-rebuilt artifacts always differed from the committed ones by
# exactly one line. The fix is idempotence at the generator — a stamp that dates the
# build which last CHANGED the payload — and the risk of that fix is that it could
# blunt the check it unblocks. These two tests hold both ends: the rebuild must be a
# no-op when the data is unchanged, and the check must still fire when data/web is
# genuinely stale or unstaged, which is defect (c) itself.

def _tmp_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    os.makedirs(os.path.join(tmp_path, "data", "web"))
    return str(tmp_path)


def _point_build_manifest_at(monkeypatch, root):
    monkeypatch.setattr(build_manifest, "REPO", root)
    monkeypatch.setattr(build_manifest, "DATA", os.path.join(root, "data"))
    monkeypatch.setattr(build_manifest, "OUT",
                        os.path.join(root, "data", "MANIFEST.json"))


def _write_web(root, name, payload):
    with open(os.path.join(root, "data", "web", name), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _commit(root, *paths):
    subprocess.run(["git", "-C", root, "add", "--"] + list(paths), check=True)
    subprocess.run(["git", "-C", root, "commit", "-qm", "payload"], check=True)


def test_check_tree_still_fires_when_the_payload_is_stale_or_unstaged(
        tmp_path, monkeypatch, capsys):
    """(c), seeded: a manifest that describes bytes git does not hold must fail."""
    root = _tmp_repo(tmp_path)
    _point_build_manifest_at(monkeypatch, root)

    _write_web(root, "catalog.json", {"built_utc": "2026-09-06T00:00:00Z",
                                      "git_head": None, "rows": [[1], [2]]})
    man = build_manifest.build()
    with open(os.path.join(root, "data", "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh)
    _commit(root, "data/web/catalog.json", "data/MANIFEST.json")
    assert build_manifest.check_tree(man) == 0, "a consistent tree must pass"

    # Seed the defect: the payload genuinely changes (a record was added) and the
    # rebuilt manifest describes it, but data/web is never staged.
    _write_web(root, "catalog.json", {"built_utc": "2026-09-07T00:00:00Z",
                                      "git_head": None, "rows": [[1], [2], [3]]})
    stale = build_manifest.build()
    capsys.readouterr()
    assert build_manifest.check_tree(stale) == 1, (
        "the manifest describes a payload git does not hold and --check-tree "
        "passed: defect (c) is back")
    out = capsys.readouterr().out
    assert "data/web/catalog.json" in out and "not committed" in out

    # A payload file that exists and is described but was never added at all.
    _write_web(root, "summary.json", {"built_utc": "2026-09-07T00:00:00Z",
                                      "git_head": None, "count": 3})
    untracked = build_manifest.build()
    capsys.readouterr()
    assert build_manifest.check_tree(untracked) == 1
    assert "NOT" in capsys.readouterr().out

    # Staging both clears it — the guard is discriminating, not merely noisy.
    _commit(root, "data/web/catalog.json", "data/web/summary.json")
    fixed = build_manifest.build()
    with open(os.path.join(root, "data", "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(fixed, fh)
    _commit(root, "data/MANIFEST.json")
    assert build_manifest.check_tree(fixed) == 0


def test_rebuilding_an_unchanged_payload_changes_no_bytes(tmp_path):
    """Idempotence at the generator: this is what lets `make preflight` pass."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import web_payload                                        # noqa: E402

    path = os.path.join(tmp_path, "catalog.json")
    first = {"schema": "s", "built_utc": "2026-09-06T10:00:00Z",
             "git_head": "a" * 40, "count": 2, "rows": [[1], [2]]}
    blob, rewritten = web_payload.write_payload_file(path, first)
    assert rewritten
    before = (open(path, "rb").read(), os.path.getmtime(path))

    # A later build of the SAME data, from a different commit, seconds later.
    again = dict(first, built_utc="2026-09-06T11:22:33Z", git_head="b" * 40)
    blob2, rewritten2 = web_payload.write_payload_file(path, again)
    assert not rewritten2, "an unchanged payload was rewritten for its stamp alone"
    assert (open(path, "rb").read(), os.path.getmtime(path)) == before
    assert json.loads(blob2)["built_utc"] == "2026-09-06T10:00:00Z"

    # A real change moves both the data and the stamp.
    changed = dict(again, count=3, rows=[[1], [2], [3]])
    blob3, rewritten3 = web_payload.write_payload_file(path, changed)
    assert rewritten3
    assert json.loads(blob3)["built_utc"] == "2026-09-06T11:22:33Z"
    assert json.loads(open(path, encoding="utf-8").read())["count"] == 3


def test_the_manifest_keeps_its_stamp_when_nothing_it_describes_changed():
    """The same rule one level up: data/MANIFEST.json must not churn either."""
    old = {"schema": "m", "built_utc": "2026-09-06T10:00:00Z", "git_head": "a" * 40,
           "artifacts": {"data/web/catalog.json": {"present": True, "sha256": "ff",
                                                   "mtime_utc": "2026-09-06T10:00:00Z"}}}
    def rebuilt():
        """What build() would produce seconds later, from a different commit."""
        m = json.loads(json.dumps(old))
        m["built_utc"] = "2026-09-06T12:00:00Z"
        m["git_head"] = "b" * 40
        m["artifacts"]["data/web/catalog.json"]["mtime_utc"] = "2026-09-06T12:00:00Z"
        return m

    carried = build_manifest.carry_stamps_forward(rebuilt(), old)
    assert carried == old

    moved = rebuilt()
    moved["artifacts"]["data/web/catalog.json"]["sha256"] = "ee"
    carried2 = build_manifest.carry_stamps_forward(moved, old)
    assert carried2["built_utc"] == "2026-09-06T12:00:00Z", (
        "a manifest whose artifacts changed must carry the new build stamp")


# --------------------------------------- the reproduction claim, cheaply sentinelled
# `make reproduce` runs the whole chain over 13,515 records and takes ~20 minutes, so
# it is not in `make preflight` and no test can run it. It failed on 13,515 of 13,515
# records for ONE reason: the corpus was promoted before stage 40 renamed
# pct_covered_observed -> pct_sourced_components_with_bigg_id, so the shipped records
# carried a field name the chain no longer emits, and README's "reproducible byte for
# byte" was false. The corpus is now the chain's output. This is the cheap sentinel
# for that class — the field names the chain writes must be the ones the shipped
# records carry — so the same drift fails in seconds instead of surviving to a
# pre-push audit.

def test_the_corpus_carries_the_field_names_the_chain_emits(corpus_dir, corpus_ids):
    stage = read(os.path.join(REPO, "tools", "stages", "remap_components.py"))
    emitted = re.findall(r'med\["(pct_[a-z_0-9]+)"\]\s*=', stage)
    assert "pct_sourced_components_with_bigg_id" in emitted, (
        "stage 40 no longer writes pct_sourced_components_with_bigg_id; if that is "
        "intended, promote a chain run and update this test with it")
    retired = "pct_covered_observed"
    assert retired not in emitted

    offenders = []
    for mid in corpus_ids:
        with open(os.path.join(corpus_dir, mid + ".json"), encoding="utf-8") as fh:
            text = fh.read()
        if '"%s"' % retired in text:
            offenders.append(mid)
        elif '"pct_sourced_components_with_bigg_id"' not in text:
            offenders.append(mid)
        if len(offenders) >= 5:
            break
    assert not offenders, (
        "%s of the shipped records carry the retired field name or lack the one the "
        "chain emits (%s ...) — the corpus is not what `make stages` produces and "
        "`make reproduce` will fail on every record"
        % (len(offenders), ", ".join(offenders)))
