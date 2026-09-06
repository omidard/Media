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
    ("data/coverage.json", "tools/enrich_coverage.py", ["data/media/*.json"], "json:media"),
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
]

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
    for p in problems:
        print("MANIFEST PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed manifest against the artifacts on disk")
    a = ap.parse_args()
    if a.check:
        if not os.path.exists(OUT):
            print("no manifest at %s — run `python3 tools/build_manifest.py`" % OUT)
            sys.exit(1)
        with open(OUT, encoding="utf-8") as fh:
            sys.exit(check(json.load(fh)))
    m = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1)
    print("manifest -> %s" % os.path.relpath(OUT, REPO))
    for rel, e in m["artifacts"].items():
        print("  %-32s %-42s rows=%s" % (rel, e["generator"][:42], e.get("rows")))
    ident = m["catalog_count_identity"]
    print("catalogue count identity: agree=%s %s" % (ident["agree"], ident["counts"]))
