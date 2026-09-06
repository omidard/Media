#!/usr/bin/env python3
"""
What the published site weighs, measured the way GitHub publishes it.

GitHub Pages serves this repository's ROOT, so the published site is every
TRACKED file — not the working tree, not the git objects. Pages refuses a
published site over 1 GiB. The corpus cannot be unpublished: assets/media.js
fetches data/media/<id>.json at runtime.

This measures the sum of blob sizes in a git tree, which is exactly what gets
served, and prints the top-level breakdown and the margin. It is the same
measurement an external reviewer made on origin/main (522.0 MiB) and on the
remediation branch (1,597.8 MiB, over the limit), so the numbers are comparable.

  python3 tools/report_site_size.py [REV ...]     (default: HEAD, and the
                                                   working tree if it differs)
  make size
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

MIB = 1048576.0
LIMIT_MIB = 1024.0          # GitHub Pages published-site limit, 1 GiB
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tree_sizes(rev: str) -> dict:
    """{top-level key: bytes} for every blob in `rev`. data/ split one deeper."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "-l", "--full-tree", rev],
        cwd=REPO, capture_output=True, text=True, check=True).stdout
    agg: dict[str, int] = {}
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[3] == "-":       # submodule / non-blob
            continue
        size = int(parts[3])
        seg = path.split("/")
        key = "/".join(seg[:2]) if seg[0] == "data" and len(seg) > 1 else seg[0]
        agg[key] = agg.get(key, 0) + size
    return agg


def worktree_sizes() -> dict:
    """The same measurement over the tracked files as they are on disk now."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    agg: dict[str, int] = {}
    for path in out.split("\0"):
        if not path:
            continue
        try:
            size = os.path.getsize(os.path.join(REPO, path))
        except OSError:
            continue
        seg = path.split("/")
        key = "/".join(seg[:2]) if seg[0] == "data" and len(seg) > 1 else seg[0]
        agg[key] = agg.get(key, 0) + size
    return agg


def report(label: str, agg: dict, baseline: dict | None = None) -> float:
    total = sum(agg.values())
    print("%s  %.1f MiB" % (label, total / MIB))
    rows = sorted(agg.items(), key=lambda kv: -kv[1])
    for key, size in rows:
        if size < 0.05 * MIB and baseline is None:
            continue
        line = "   %9.1f MiB  %s" % (size / MIB, key)
        if baseline is not None:
            was = baseline.get(key, 0)
            if abs(size - was) > 0.05 * MIB:
                line += "   (was %.1f, %+.1f)" % (was / MIB, (size - was) / MIB)
        if size >= 0.05 * MIB:
            print(line)
    return total / MIB


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("revs", nargs="*", default=None,
                    help="git revisions to measure (default: origin/main and HEAD)")
    a = ap.parse_args(argv)

    revs = a.revs or []
    if not revs:
        for r in ("origin/main", "HEAD"):
            if subprocess.run(["git", "rev-parse", "--verify", "-q", r],
                              cwd=REPO, capture_output=True).returncode == 0:
                revs.append(r)

    base = None
    total = 0.0
    for rev in revs:
        agg = tree_sizes(rev)
        total = report("TRACKED %s" % rev, agg, base)
        base = agg
        print()

    wt = worktree_sizes()
    if base is None or wt != base:
        total = report("TRACKED working tree", wt, base)
        print()

    margin = LIMIT_MIB - total
    print("GitHub Pages published-site limit: %.0f MiB" % LIMIT_MIB)
    print("published site: %.1f MiB — %.1f MiB of headroom (%.0f%% of the limit used)"
          % (total, margin, 100.0 * total / LIMIT_MIB))
    if margin <= 0:
        sys.stderr.write("FAIL: the published site is over the GitHub Pages limit.\n")
        return 1
    if margin < 100:
        sys.stderr.write("WARNING: under 100 MiB of headroom.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
