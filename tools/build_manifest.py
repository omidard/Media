#!/usr/bin/env python3
"""
build_manifest — write data/MANIFEST.json: what every shipped artifact is, what
generated it, from what, when, how many rows it holds, and its sha256.

    python3 tools/build_manifest.py [--check]

Why it exists
-------------
The audit found four different totals for the same catalogue shipping at once
(README 11,367 / media_stats 12,387 / stats 13,073 / index 13,515), two published
endpoints that no workflow regenerated, and no record anywhere of which script
produces which file. A consumer could not tell a fresh artifact from a stale one,
and neither could the pipeline.

The manifest fixes the second half of that: every derived artifact is listed with
its generator, its inputs, its row count and its digest, so drift is detectable
mechanically. `--check` re-reads every artifact and fails if a recorded count or
digest no longer matches, which is what CI runs.

It also records what the corpus is NOT: the `provenance` block states that
data/media is a frozen snapshot whose generators are dead, how much of it is
regenerable in principle, and how much is permanently unreproducible — the numbers
from finding PIPE-01, so nobody has to rediscover them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mediapaths import REPO  # noqa: E402

DATA = os.path.join(REPO, "data")
OUT = os.path.join(DATA, "MANIFEST.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows_json(path: str, key: str | None) -> int | None:
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    if key is None:
        return len(obj) if isinstance(obj, (list, dict)) else None
    cur = obj
    for k in key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return len(cur) if isinstance(cur, (list, dict)) else cur


# artifact -> (generator, inputs, how to count its rows)
ARTIFACTS = [
    ("data/media/", "frozen snapshot — generators are dead (PIPE-01)",
     ["(none surviving)"], "dir"),
    ("data/index.json", "build_index.py", ["data/media/*.json"], "json:media"),
    ("data/stats.json", "build_index.py", ["data/media/*.json"], "json:count"),
    # Attribution corrected: stage 39_recompute_coverage took authorship of the
    # per-medium coverage blocks, tools/enrich_coverage.py refuses to run over a
    # corpus carrying that stamp, and it was removed from `make derived`. The file
    # is projected from the corpus by tools/build_coverage_index.py. The manifest
    # named the wrong script, which is a provenance error in the one file whose job
    # is provenance — `check()` now asserts the attribution mechanically.
    ("data/coverage.json", "tools/build_coverage_index.py", ["data/media/*.json"], "json:media"),
    ("data/media_stats.json", "tools/build_media_stats.py",
     ["data/media/*.json", "tools/bigg_metabolite_dict.json"], "json:total"),
    ("data/presence_matrix.json", "tools/build_presence_matrix.py",
     ["data/media/*.json", "tools/bigg_metabolite_dict.json"], "json:n_media"),
    ("data/api/manifest.json", "tools/build_api_exports.py", ["data/index.json"], "json:catalog_count"),
    ("data/api/media.parquet", "tools/build_api_exports.py",
     ["data/index.json", "data/media/*.json"], "parquet"),
    ("data/api/components.parquet", "tools/build_api_exports.py",
     ["data/index.json", "data/media/*.json"], "parquet"),
    # Sharded: the single media.jsonl.gz is 141 MB against the corrected corpus, past
    # GitHub's 100 MiB per-file hard limit. tools/build_api_exports.py writes parts and
    # asserts the budget; the parts concatenate to a byte-identical stream.
    ("data/api/media.jsonl.part01.gz", "tools/build_api_exports.py",
     ["data/index.json", "data/media/*.json"], "gzlines"),
    ("data/api/media.jsonl.part02.gz", "tools/build_api_exports.py",
     ["data/index.json", "data/media/*.json"], "gzlines"),
    ("data/api/media.sqlite.gz", "tools/build_api_exports.py",
     ["data/index.json", "data/media/*.json"], None),
    ("data/cluster/clustergram.json", "tools/build_cluster_data.py",
     ["data/api/media.parquet", "data/api/components.parquet"], None),
    ("data/cluster/cooccurrence.json", "tools/build_cluster_data.py",
     ["data/api/media.parquet", "data/api/components.parquet"], None),
    ("data/_quarantine.json", "tools/apply_verification.py", ["data/media/*.json"], None),
    # The browser payload. Projected straight from the corpus so the site can never
    # render a number that the records do not support; the same projection is asserted
    # inside the stage chain by tools/stages/52_web_payload.py.
    ("data/web/catalog.json", "tools/build_web_payload.py",
     ["data/media/*.json", "data/_quarantine.json"], "json:rows"),
    ("data/web/summary.json", "tools/build_web_payload.py",
     ["data/media/*.json"], "json:count"),
    ("data/web/compounds.json", "tools/build_web_payload.py",
     ["data/media/*.json"], "json:n_exchanges"),
    ("data/web/families.json", "tools/build_web_payload.py",
     ["data/media/*.json"], "json:n_families"),
    ("data/web/tombstones.json", "tools/build_web_payload.py",
     ["data/_quarantine.json"], "json:n_withdrawn"),
    ("data/web/twins.json", "tools/build_web_payload.py",
     ["data/media/*.json"], "json:n_groups"),
]

#: Directories whose every published file must be declared above. `make derived`
#: rewrites all of these; an artifact that appears in one without a row here is
#: unhashed, unstaged by CI and undetectable when it goes stale — which is exactly
#: how data/web shipped a payload the manifest described but CI never committed.
PAYLOAD_DIRS = ["data/web", "data/api", "data/cluster"]

PROVENANCE = {
    "corpus_status": "frozen snapshot",
    "why": ("The raw inputs are gone. 19 generator scripts hardcoded a session "
            "scratchpad that was deleted, none of the upstream payloads was ever "
            "committed, and the shipped data/media/*.json is the only surviving copy "
            "of the corpus (audit finding PIPE-01)."),
    "measured_2026_09_06": {
        "media_total": 13515,
        "media_with_a_dead_generator": 13248,
        "media_with_a_live_generator": 267,
        "media_permanently_unreproducible": 1456,
        "media_permanently_unreproducible_why":
            "lit_ 87 + growthlit_ 1,036 + complexlit_ 333 came from LLM extraction "
            "batches that no longer exist; re-running the miner would file DIFFERENT "
            "compositions under the SAME citations.",
        "media_recoverable_in_principle": 11792,
        "media_recoverable_in_principle_why":
            "usda_/mediadive_/food_/mdb_/biospecimen_ sources are public and "
            "re-fetchable (see data/_sources/MANIFEST.json), though upstream has moved "
            "since the original snapshot, so a rebuild is a source-version delta, not a "
            "reproduction.",
    },
    "how_corrections_are_made": (
        "As transform stages under tools/stages/, composed by "
        "tools/stages/run_stages.py in the order recorded in tools/stages/stages.json. "
        "Corrections are never hand-patched into data/media/*.json."),
    "source_ledger": "data/_sources/MANIFEST.json",
}


def count_rows(path: str, how) -> int | None:
    if how == "dir":
        return len(glob.glob(os.path.join(path, "*.json")))
    if how is None:
        return None
    if how == "parquet":
        try:
            import pyarrow.parquet as pq
            return pq.ParquetFile(path).metadata.num_rows
        except Exception as exc:                              # noqa: BLE001 - reported
            print("  WARN cannot read parquet rows for %s: %s" % (path, exc))
            return None
    if how == "gzlines":
        import gzip
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    if how.startswith("json:"):
        return _rows_json(path, how.split(":", 1)[1])
    return None


def git_head() -> str | None:
    try:
        return subprocess.check_output(["git", "-C", REPO, "rev-parse", "HEAD"],
                                       text=True).strip()
    except Exception:                                          # noqa: BLE001
        return None


def build() -> dict:
    man = {
        "schema": "mediadb-artifact-manifest/1",
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": git_head(),
        "provenance": PROVENANCE,
        "artifacts": {},
    }
    for rel, gen, inputs, how in ARTIFACTS:
        p = os.path.join(REPO, rel)
        entry = {"generator": gen, "inputs": inputs}
        if rel.endswith("/"):
            if not os.path.isdir(p.rstrip("/")):
                entry |= {"present": False}
                man["artifacts"][rel] = entry
                continue
            entry |= {"present": True, "rows": count_rows(p.rstrip("/"), how),
                      "bytes": sum(os.path.getsize(f)
                                   for f in glob.glob(os.path.join(p, "*.json")))}
        elif not os.path.exists(p):
            entry |= {"present": False}
        else:
            entry |= {"present": True, "bytes": os.path.getsize(p),
                      "sha256": sha256(p), "rows": count_rows(p, how),
                      "mtime_utc": dt.datetime.fromtimestamp(
                          os.path.getmtime(p), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        man["artifacts"][rel] = entry

    # The consistency identity STALE-01 asks for, recorded with its denominators.
    counts = {rel: man["artifacts"][rel].get("rows")
              for rel in ("data/media/", "data/index.json", "data/stats.json",
                          "data/media_stats.json", "data/presence_matrix.json",
                          "data/api/manifest.json", "data/api/media.parquet")
              if rel in man["artifacts"]}
    present = {k: v for k, v in counts.items() if v is not None}
    man["catalog_count_identity"] = {
        "counts": present,
        "agree": len(set(present.values())) <= 1,
        "assertion": ("every catalogue-shaped artifact must report the same number of "
                      "media; a disagreement means an artifact was not rebuilt "
                      "(STALE-01: two endpoints were 1,128 media stale)"),
    }
    return man


# ------------------------------------------------------- generator attribution
# The manifest recorded tools/enrich_coverage.py as the generator of
# data/coverage.json long after `make derived` stopped running it and stage 39 took
# authorship of the numbers. Nothing noticed, because the attribution was prose. It
# is now checked: the named script must exist, and it (or a module it imports from
# this repository) must actually name the artifact it is credited with writing.

def _local_import_closure(script_rel: str, seen=None) -> list[str]:
    """Repo-local modules a script imports, transitively.

    Needed because entrypoints delegate: tools/build_web_payload.py credits itself
    with data/web/catalog.json, but the string 'catalog.json' lives in the module it
    imports, tools/web_payload.py. Following the import is the difference between a
    check that works and one that has to be switched off for five artifacts.
    """
    import ast
    seen = seen if seen is not None else set()
    path = os.path.join(REPO, script_rel)
    if script_rel in seen or not os.path.exists(path):
        return []
    seen.add(script_rel)
    with open(path, encoding="utf-8") as fh:
        try:
            tree = ast.parse(fh.read(), filename=path)
        except SyntaxError:
            return [script_rel]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    out = [script_rel]
    here = os.path.dirname(path)
    for n in sorted(names):
        for cand in (os.path.join(here, n + ".py"),
                     os.path.join(REPO, "tools", n + ".py"),
                     os.path.join(REPO, n + ".py")):
            if os.path.exists(cand):
                out += _local_import_closure(os.path.relpath(cand, REPO), seen)
                break
    return out


def _artifact_tokens(rel: str) -> list[str]:
    """Strings that would appear in the script that writes `rel`.

    Sharded and templated names are matched on their stem: media.jsonl.part01.gz is
    written by a `%02d` format string, so the literal filename is never in the
    source. Requiring the stem is still a real check — it fails if the credited
    script has nothing to do with the artifact.
    """
    base = os.path.basename(rel.rstrip("/"))
    toks = [base]
    m = re.match(r"^(.*?)\.?part\d+(\..*)$", base)
    if m:
        toks.append(m.group(1) + m.group(2))
        toks.append(m.group(1))
    if base.endswith(".gz"):
        toks.append(base[:-3])
    return toks


def check_attribution(man: dict) -> list[str]:
    problems = []
    for rel, e in man["artifacts"].items():
        gen = e.get("generator", "")
        if not gen.endswith(".py"):
            continue                       # 'frozen snapshot — generators are dead'
        if not os.path.exists(os.path.join(REPO, gen)):
            problems.append("%s: generator %s does not exist" % (rel, gen))
            continue
        sources = _local_import_closure(gen)
        blob = ""
        for s in sources:
            with open(os.path.join(REPO, s), encoding="utf-8", errors="replace") as fh:
                blob += fh.read()
        if not any(tok in blob for tok in _artifact_tokens(rel)):
            problems.append(
                "%s: the manifest credits %s, but neither it nor anything it imports "
                "(%s) names %s — the attribution is wrong or the generator changed"
                % (rel, gen, ", ".join(sources), os.path.basename(rel.rstrip("/"))))
    return problems


# --------------------------------------------------------- manifest vs the tree
# Finding (c): `make derived` rewrites all of data/web/*, the manifest sha256-hashes
# those five files, and the CI commit step did not stage them — so the first CI run
# would have committed a manifest describing a payload it did not commit, and
# nothing would have failed. This is the check that makes that class impossible: the
# manifest is compared against what is COMMITTED, not against the working tree.

def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)


def check_tree(man: dict, rev: str = "HEAD") -> int:
    problems, ignored = [], []
    for rel, e in man["artifacts"].items():
        if not e.get("present") or "sha256" not in e:
            continue
        if _git("check-ignore", "-q", rel).returncode == 0:
            ignored.append(rel)
            continue
        if _git("ls-files", "--error-unmatch", rel).returncode != 0:
            problems.append(
                "%s: the manifest describes it and it exists on disk, but it is NOT "
                "tracked by git — the published site would serve the previous "
                "payload while the manifest advertised this one" % rel)
            continue
        blob = subprocess.run(["git", "-C", REPO, "cat-file", "blob",
                               "%s:%s" % (rev, rel)], capture_output=True)
        if blob.returncode != 0:
            problems.append("%s: tracked, but not present in %s" % (rel, rev))
            continue
        got = hashlib.sha256(blob.stdout).hexdigest()
        if got != e["sha256"]:
            problems.append(
                "%s: committed blob sha256 %s but the manifest records %s — the "
                "manifest describes a payload that was not committed (regenerate and "
                "stage both, or the site and the manifest disagree)"
                % (rel, got[:16], e["sha256"][:16]))
    if ignored:
        print("not published from the repository (gitignored), digest not compared: %s"
              % ", ".join(sorted(ignored)))
    for p in problems:
        print("MANIFEST/TREE PROBLEM:", p)
    if not problems:
        print("manifest agrees with the committed tree at %s (%d hashed artifacts)"
              % (rev, sum(1 for e in man["artifacts"].values() if "sha256" in e)))
    return 1 if problems else 0


def artifact_paths(man: dict) -> list[str]:
    """The paths CI must stage: every artifact the manifest declares and git tracks.

    Derived from the manifest instead of hand-listed in the workflow, so relocating
    an artifact (or adding one) updates what CI commits automatically. The hand-list
    is how data/web went unstaged.
    """
    out = []
    for rel in man["artifacts"]:
        if rel.endswith("/"):
            # data/media/ — the corpus, an input, not something a build writes.
            # `make promote` is the only step allowed to change it, and the workflow
            # asserts `make derived` did not. CI must never stage it.
            continue
        p = rel.rstrip("/")
        if _git("check-ignore", "-q", p).returncode == 0:
            continue
        if not os.path.exists(os.path.join(REPO, p)):
            continue
        out.append(p)
    return sorted(set(out))


def check_complete(man: dict) -> list[str]:
    """Every published file in a payload directory must have a manifest row."""
    declared = {rel.rstrip("/") for rel in man["artifacts"]}
    problems = []
    for d in PAYLOAD_DIRS:
        root = os.path.join(REPO, d)
        if not os.path.isdir(root):
            continue
        for f in sorted(os.listdir(root)):
            rel = "%s/%s" % (d, f)
            if os.path.isdir(os.path.join(root, f)) or rel in declared:
                continue
            if _git("check-ignore", "-q", rel).returncode == 0:
                continue                     # deliberately not published
            problems.append(
                "%s is published but has no row in data/MANIFEST.json — it is "
                "unhashed, so nothing can tell a fresh copy from a stale one, and "
                "CI (which stages the manifest's own artifact list) will not commit "
                "it. Add it to ARTIFACTS in tools/build_manifest.py." % rel)
    return problems


def check(man: dict) -> int:
    """Re-verify the recorded digests and the count identity. Non-zero on drift."""
    problems = []
    for rel, e in man["artifacts"].items():
        if not e.get("present") or "sha256" not in e:
            continue
        p = os.path.join(REPO, rel)
        if not os.path.exists(p):
            problems.append("%s: recorded in the manifest but missing on disk" % rel)
            continue
        if sha256(p) != e["sha256"]:
            problems.append("%s: sha256 differs from the manifest — regenerate it "
                            "(make derived) or rebuild the manifest" % rel)
    if not man["catalog_count_identity"]["agree"]:
        problems.append("catalogue counts disagree: %s"
                        % man["catalog_count_identity"]["counts"])
    problems += check_attribution(man)
    problems += check_complete(man)
    for p in problems:
        print("MANIFEST PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed manifest against the artifacts on disk")
    ap.add_argument("--check-tree", action="store_true",
                    help="verify the manifest against what git has COMMITTED at --rev")
    ap.add_argument("--rev", default="HEAD", help="revision for --check-tree")
    ap.add_argument("--paths", action="store_true",
                    help="print the tracked artifact paths CI must stage, one per line")
    a = ap.parse_args()
    if a.check or a.check_tree or a.paths:
        if not os.path.exists(OUT):
            print("no manifest at %s — run `python3 tools/build_manifest.py`" % OUT)
            sys.exit(1)
        with open(OUT, encoding="utf-8") as fh:
            man = json.load(fh)
        if a.paths:
            print("\n".join(artifact_paths(man)))
            sys.exit(0)
        rc = check(man) if a.check else 0
        if a.check_tree:
            rc |= check_tree(man, a.rev)
        sys.exit(rc)
    m = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1)
    print("manifest -> %s" % os.path.relpath(OUT, REPO))
    for rel, e in m["artifacts"].items():
        print("  %-32s %-42s rows=%s" % (rel, e["generator"][:42], e.get("rows")))
    ident = m["catalog_count_identity"]
    print("catalogue count identity: agree=%s %s" % (ident["agree"], ident["counts"]))
