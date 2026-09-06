#!/usr/bin/env python3
"""
verify_derived — rebuild the derived artifacts into a temp tree and report how they
differ from the shipped ones.

    make verify
    python3 tools/verify_derived.py [--keep]

This is deliberately a REPORT, not a byte-identity assertion. The audit's proposed
"rebuild and diff against shipped data" can never pass here: the shipped corpus is
builder output plus in-place curation passes whose order no file records, several
artifacts embed a build date, and the upstream databases have moved. A pass/fail on
byte identity would therefore be either permanently red or quietly meaningless.

What it does assert is the thing that was actually broken (STALE-01): every
catalogue-shaped artifact must describe the same corpus. A count or id-set
disagreement is a hard failure, because that is how two published endpoints came to
be 1,128 media stale while the manifest pointing at them was fresh.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mediapaths import REPO  # noqa: E402

DATA = os.path.join(REPO, "data")


def _count(path, key):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get(key)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the temp rebuild tree")
    a = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="mediadb-verify-")
    print("rebuilding the catalogue into %s" % tmp)
    rc = subprocess.call([sys.executable, os.path.join(REPO, "build_index.py"),
                          "--media", os.path.join(DATA, "media"), "--out", tmp])
    if rc != 0:
        print("rebuild failed")
        return rc
    rc = subprocess.call([sys.executable, os.path.join(HERE, "build_media_stats.py"),
                          "--media", os.path.join(DATA, "media"),
                          "--out", os.path.join(tmp, "media_stats.json")])
    if rc != 0:
        return rc

    n_media = len(glob.glob(os.path.join(DATA, "media", "*.json")))
    fresh = {"index.json": _count(os.path.join(tmp, "index.json"), "count"),
             "stats.json": _count(os.path.join(tmp, "stats.json"), "count"),
             "media_stats.json": _count(os.path.join(tmp, "media_stats.json"), "total")}
    shipped = {"index.json": _count(os.path.join(DATA, "index.json"), "count"),
               "stats.json": _count(os.path.join(DATA, "stats.json"), "count"),
               "media_stats.json": _count(os.path.join(DATA, "media_stats.json"), "total"),
               "presence_matrix.json": _count(os.path.join(DATA, "presence_matrix.json"),
                                              "n_media"),
               "api/manifest.json": _count(os.path.join(DATA, "api", "manifest.json"),
                                           "catalog_count")}

    print("\ncorpus on disk: %d media" % n_media)
    print("%-24s %10s %10s" % ("artifact", "shipped", "fresh"))
    stale = []
    for k in sorted(set(shipped) | set(fresh)):
        s, f = shipped.get(k), fresh.get(k)
        print("%-24s %10s %10s%s" % (k, s, f if f is not None else "-",
                                     "   STALE" if s not in (None, n_media) else ""))
        if s is not None and s != n_media:
            stale.append((k, s, n_media))

    # id-set check where both artifacts carry ids
    with open(os.path.join(tmp, "index.json"), encoding="utf-8") as fh:
        fresh_ids = {r["id"] for r in json.load(fh)["media"]}
    disk_ids = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(DATA, "media", "*.json"))}
    missing = disk_ids - fresh_ids
    ghosts = fresh_ids - disk_ids
    if missing or ghosts:
        print("\nid-set disagreement: %d on disk but not indexed, %d indexed but not on disk"
              % (len(missing), len(ghosts)))
        stale.append(("index id set", len(missing), len(ghosts)))

    if not a.keep:
        shutil.rmtree(tmp)
    if stale:
        print("\nFAIL: %d artifact(s) do not describe the current corpus: %s"
              % (len(stale), [s[0] for s in stale]))
        print("run `make derived` to regenerate them.")
        return 1
    print("\nOK: every catalogue-shaped artifact describes the same %d media." % n_media)
    return 0


if __name__ == "__main__":
    sys.exit(main())
