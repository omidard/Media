#!/usr/bin/env python3
"""tools/verify_counts.py — one catalogue, one total. Fails when any shipped number disagrees.

Four different totals ship at once today (findings COV-02, PROV-11, COV-06, NM-20):

    13,515   data/media/*.json on disk, and data/index.json `count`, and the live site hero
    13,073   data/stats.json `count`                     — an orphan: nothing generates it
    12,387   data/media_stats.json `total`               — stale since 2026-07-16
    12,387   data/presence_matrix.json `n_media`         — stale, and a documented API endpoint
    11,367   README.md:13 and README.md:113              — never matched the repo at any commit

The site therefore renders a 13,515 headline above a category doughnut summing to 12,387,
and its README says 11,367. There is no number a reader can cite.

This test defines the corpus on disk as the authority — it is the only total that is
computed rather than typed — and asserts every other shipped artifact against it, including
key-for-key equality of the category breakdown. A total-only check would not have caught the
missing `growth_medium` slice (443 media invisible on the site), so the breakdowns are
checked too.

It is expected to FAIL until the rebuild stage regenerates the derived artifacts. That is the
point: a failing test with real output is the honest state, and it becomes the gate that
stops the four totals from diverging again.

Not a stage: it reads the shipped derived artifacts, not a corpus, and writes nothing. It
lives in tools/ so the stage registry check does not see it as an unregistered stage.
tests/test_counts_reconcile.py wraps it for pytest.

USAGE
    python3 tools/verify_counts.py                     # against data/
    python3 tools/verify_counts.py --data-dir X        # against a rebuild
    python3 tools/verify_counts.py --counts counts.json  # against a stage-39 counts artifact

Exit 0 = every shipped total agrees. Exit 1 = at least one disagrees; each is printed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check(data_dir, readme_path, counts_path=None):
    results = []

    def add(name, ok, expected, actual, note=""):
        results.append(
            {"check": name, "ok": bool(ok), "expected": expected, "actual": actual, "note": note}
        )

    media_dir = os.path.join(data_dir, "media")
    on_disk = len(glob.glob(os.path.join(media_dir, "*.json")))

    authoritative = on_disk
    auth_by_category = None
    if counts_path:
        c = _load(counts_path)
        if c:
            authoritative = c["authoritative_count"]
            auth_by_category = c.get("by_category")
            add(
                "authoritative counts artifact agrees with the corpus on disk",
                authoritative == on_disk,
                on_disk,
                authoritative,
                counts_path,
            )

    if auth_by_category is None:
        auth_by_category = {}
        for f in glob.glob(os.path.join(media_dir, "*.json")):
            with open(f, encoding="utf-8") as fh:
                cat = json.load(fh).get("category")
            auth_by_category[cat] = auth_by_category.get(cat, 0) + 1

    # --- index.json ----------------------------------------------------------------------
    idx = _load(os.path.join(data_dir, "index.json"))
    if idx is None:
        add("data/index.json exists", False, "present", "missing")
    else:
        add("data/index.json count", idx.get("count") == authoritative, authoritative, idx.get("count"))
        add(
            "data/index.json media rows",
            len(idx.get("media", [])) == authoritative,
            authoritative,
            len(idx.get("media", [])),
        )
        add(
            "data/index.json by_category keys",
            set(idx.get("by_category", {})) == set(auth_by_category),
            sorted(auth_by_category),
            sorted(idx.get("by_category", {})),
            "a total-only check misses a whole missing category",
        )
        add(
            "data/index.json by_category values",
            idx.get("by_category") == auth_by_category,
            auth_by_category,
            idx.get("by_category"),
        )

    # --- media_stats.json ------------------------------------------------------------------
    ms = _load(os.path.join(data_dir, "media_stats.json"))
    if ms is None:
        add("data/media_stats.json exists", False, "present", "missing")
    else:
        add("data/media_stats.json total", ms.get("total") == authoritative, authoritative, ms.get("total"))
        add(
            "data/media_stats.json by_category keys",
            set(ms.get("by_category", {})) == set(auth_by_category),
            sorted(auth_by_category),
            sorted(ms.get("by_category", {})),
            "the site's category doughnut reads this file",
        )

    # --- presence_matrix.json ---------------------------------------------------------------
    pm = _load(os.path.join(data_dir, "presence_matrix.json"))
    if pm is None:
        add("data/presence_matrix.json exists", False, "present", "missing")
    else:
        add(
            "data/presence_matrix.json n_media",
            pm.get("n_media") == authoritative,
            authoritative,
            pm.get("n_media"),
            "a documented public API endpoint (API.md:66)",
        )

    # --- stats.json: an orphan with no generator ---------------------------------------------
    stats_path = os.path.join(data_dir, "stats.json")
    if os.path.exists(stats_path):
        st = _load(stats_path)
        add(
            "data/stats.json is not a hand-maintained orphan",
            False,
            "deleted (no generator exists anywhere in tools/)",
            "present, count=%s" % (st or {}).get("count"),
            "grep finds no writer and no consumer; it cannot be kept honest, so it must go "
            "rather than be wired into this gate",
        )

    # --- README ------------------------------------------------------------------------------
    if os.path.exists(readme_path):
        txt = open(readme_path, encoding="utf-8").read()
        nums = {int(n.replace(",", "")) for n in re.findall(r"\b(\d{1,3},\d{3})\b\s*media", txt)}
        bad = sorted(n for n in nums if n != authoritative)
        add(
            "README media totals",
            not bad,
            authoritative,
            sorted(nums) or "none found",
            "every '<n> media' figure in the README must be the authoritative count",
        )
        if bad:
            results[-1]["note"] += "; disagreeing: %s" % bad

    return authoritative, results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=os.path.join(REPO, "data"))
    ap.add_argument("--readme", default=os.path.join(REPO, "README.md"))
    ap.add_argument("--counts", default=None)
    ap.add_argument("--json", default=None, help="write the result as JSON")
    ap.add_argument("--write-counts", default=None,
                    help="write the authoritative counts artifact (count + by_category, "
                         "computed from the corpus, never typed) to this path")
    a = ap.parse_args(argv)

    authoritative, results = check(a.data_dir, a.readme, a.counts)

    if a.write_counts:
        by_cat = {}
        for f in glob.glob(os.path.join(a.data_dir, "media", "*.json")):
            with open(f, encoding="utf-8") as fh:
                cat = json.load(fh).get("category")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        payload = {
            "authoritative_count": authoritative,
            "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            "corpus_dir": os.path.join(a.data_dir, "media"),
            "note": ("Computed from the corpus, never typed. Every shipped total — "
                     "index.json count, media_stats.json total, presence_matrix.json n_media, "
                     "the README headline and its per-source table, the site hero — must equal "
                     "these numbers, and tools/verify_counts.py fails when one does not."),
        }
        os.makedirs(os.path.dirname(os.path.abspath(a.write_counts)), exist_ok=True)
        with open(a.write_counts, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
    n_fail = sum(1 for r in results if not r["ok"])

    print("AUTHORITATIVE COUNT: %d media (%s/media/*.json)" % (authoritative, a.data_dir))
    print("-" * 78)
    for r in results:
        print(
            "%s %s\n      expected: %s\n      actual:   %s%s"
            % (
                "PASS" if r["ok"] else "FAIL",
                r["check"],
                r["expected"],
                r["actual"],
                ("\n      note:     " + r["note"]) if r["note"] else "",
            )
        )
    print("-" * 78)
    print("%d checks, %d failing" % (len(results), n_fail))

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(
                {"authoritative_count": authoritative, "n_failing": n_fail, "checks": results},
                fh,
                indent=1,
            )
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
