#!/usr/bin/env python3
"""
compare_corpora — is corpus A the same corpus as corpus B?

    python3 tools/compare_corpora.py A_DIR B_DIR [--show 10] [--json PATH]
    python3 tools/compare_corpora.py --stamp-date DIR

This is the measuring end of `make reproduce`: it compares the chain's output
against the corpus that ships and says, in one exit code, whether a fresh clone
reproduces what is published.

It reports three separable facts rather than one verdict, because they fail for
different reasons and a single "differs" hides which:

  1. the id sets                — a stage that added or dropped a record
  2. byte identity per record   — a transform that produced different output
  3. byte identity IGNORING provenance.transforms[].date — the same output built on
     a different day. A reproduction that differs ONLY here is a reproduction; set
     MEDIADB_STAMP_DATE (see tools/stages/stagelib.stamp_date) to remove even that
     difference, which is what `make reproduce` does.

`--stamp-date DIR` prints the transform date a corpus carries, so the Makefile can
feed the shipped corpus's own date back into the chain instead of hardcoding one.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys


def ids_of(d: str) -> set:
    return {f[:-5] for f in os.listdir(d) if f.endswith(".json")}


def _strip_dates(obj):
    """Return the record with every provenance.transforms[].date removed."""
    prov = obj.get("provenance")
    if isinstance(prov, dict) and isinstance(prov.get("transforms"), list):
        obj = dict(obj)
        obj["provenance"] = dict(prov)
        obj["provenance"]["transforms"] = [
            {k: v for k, v in t.items() if k != "date"} if isinstance(t, dict) else t
            for t in prov["transforms"]]
    return obj


def canonical(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    return hashlib.sha256(json.dumps(_strip_dates(obj), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def key_diff(a_path: str, b_path: str) -> dict:
    with open(a_path, encoding="utf-8") as fh:
        a = json.load(fh)
    with open(b_path, encoding="utf-8") as fh:
        b = json.load(fh)
    ka, kb = set(a), set(b)
    changed = sorted(k for k in ka & kb if a[k] != b[k])
    return {"only_in_a": sorted(ka - kb), "only_in_b": sorted(kb - ka),
            "values_differ": changed[:12]}


def compare(a_dir: str, b_dir: str, show: int = 10) -> dict:
    ia, ib = ids_of(a_dir), ids_of(b_dir)
    res = {"a": a_dir, "b": b_dir, "n_a": len(ia), "n_b": len(ib),
           "only_in_a": sorted(ia - ib)[:show], "only_in_b": sorted(ib - ia)[:show],
           "n_only_in_a": len(ia - ib), "n_only_in_b": len(ib - ia)}
    common = sorted(ia & ib)
    byte_diff, canon_diff = [], []
    for mid in common:
        pa = os.path.join(a_dir, mid + ".json")
        pb = os.path.join(b_dir, mid + ".json")
        with open(pa, "rb") as fh1, open(pb, "rb") as fh2:
            if fh1.read() == fh2.read():
                continue
        byte_diff.append(mid)
        if canonical(pa) != canonical(pb):
            canon_diff.append(mid)
    res["n_common"] = len(common)
    res["n_byte_identical"] = len(common) - len(byte_diff)
    res["n_byte_differing"] = len(byte_diff)
    res["n_differing_beyond_transform_dates"] = len(canon_diff)
    res["byte_differing_examples"] = byte_diff[:show]
    res["substantive_examples"] = canon_diff[:show]
    res["key_diffs"] = {mid: key_diff(os.path.join(a_dir, mid + ".json"),
                                      os.path.join(b_dir, mid + ".json"))
                        for mid in canon_diff[:show]}
    res["identical"] = (not byte_diff and not (ia ^ ib))
    res["identical_ignoring_transform_dates"] = (not canon_diff and not (ia ^ ib))
    return res


def stamp_date_of(d: str, sample: int = 500) -> str | None:
    c = collections.Counter()
    for f in sorted(os.listdir(d))[:sample]:
        if not f.endswith(".json"):
            continue
        with open(os.path.join(d, f), encoding="utf-8") as fh:
            rec = json.load(fh)
        for t in (rec.get("provenance") or {}).get("transforms") or []:
            if isinstance(t, dict) and t.get("date"):
                c[t["date"]] += 1
    return c.most_common(1)[0][0] if c else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", nargs="?", help="corpus A (e.g. the chain output)")
    ap.add_argument("b", nargs="?", help="corpus B (e.g. data/media)")
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--stamp-date", default=None,
                    help="print the transform date this corpus carries, and exit")
    a = ap.parse_args(argv)

    if a.stamp_date:
        d = stamp_date_of(os.path.abspath(a.stamp_date))
        if not d:
            print("no provenance.transforms[].date in %s" % a.stamp_date,
                  file=sys.stderr)
            return 1
        print(d)
        return 0

    if not a.a or not a.b:
        ap.error("two corpus directories are required")
    res = compare(os.path.abspath(a.a), os.path.abspath(a.b), a.show)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)

    print("A %s  %d records" % (res["a"], res["n_a"]))
    print("B %s  %d records" % (res["b"], res["n_b"]))
    print("ids only in A: %d %s" % (res["n_only_in_a"], res["only_in_a"] or ""))
    print("ids only in B: %d %s" % (res["n_only_in_b"], res["only_in_b"] or ""))
    print("byte-identical records:            %d of %d"
          % (res["n_byte_identical"], res["n_common"]))
    print("byte-differing records:            %d %s"
          % (res["n_byte_differing"], res["byte_differing_examples"] or ""))
    print("differing beyond transform dates:  %d %s"
          % (res["n_differing_beyond_transform_dates"],
             res["substantive_examples"] or ""))
    for mid, kd in res["key_diffs"].items():
        print("  %s: only_in_A=%s only_in_B=%s values_differ=%s"
              % (mid, kd["only_in_a"], kd["only_in_b"], kd["values_differ"]))
    if res["identical"]:
        print("VERDICT: identical — the chain reproduces this corpus byte for byte.")
        return 0
    if res["identical_ignoring_transform_dates"]:
        print("VERDICT: identical except for the provenance transform date (the day "
              "the chain ran). Set MEDIADB_STAMP_DATE to make the comparison exact.")
        return 0
    print("VERDICT: the corpora differ.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
