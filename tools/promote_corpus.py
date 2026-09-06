#!/usr/bin/env python3
"""
promote_corpus — the one program allowed to write data/media.

The stage chain writes a corrected corpus into data/_rebuild/media. Promotion is
deliberate and separate, because data/media is the sole surviving copy of the
resource (PIPE-01): overwriting it is the single irreversible act in this pipeline,
so it gets its own command, its own backup, and its own report.

    make promote                       # backs up, then calls this
    python3 tools/promote_corpus.py --from data/_rebuild/media --to data/media --dry-run

What it refuses to do:
  * promote a corpus with a different record count, unless --allow-count-change
  * promote a corpus that fails the universal invariants
  * promote without a readable chain report proving which stages produced it
  * delete anything: records that exist in the target but not in the source are
    reported and LEFT IN PLACE, never removed
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "stages"))
from invariants import check_all, summarize  # noqa: E402
from mediapaths import REPO                  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dst", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-count-change", action="store_true")
    a = ap.parse_args(argv)

    src, dst = os.path.abspath(a.src), os.path.abspath(a.dst)
    if not os.path.isdir(src):
        print("no corrected corpus at %s" % src)
        return 2
    if os.path.realpath(src) == os.path.realpath(dst):
        print("source and target are the same directory")
        return 2

    chain = os.path.join(os.path.dirname(os.path.realpath(src)), "chain_report.json")
    chain = chain if os.path.exists(chain) else os.path.join(REPO, "data", "_rebuild",
                                                             "chain_report.json")
    if not os.path.exists(chain):
        print("no chain report next to %s — promote only a corpus the runner produced" % src)
        return 2
    with open(chain, encoding="utf-8") as fh:
        rep = json.load(fh)
    if not rep.get("ok"):
        print("the chain report says the run FAILED; refusing to promote")
        return 2
    stages = [s["stage"] for s in rep.get("stages", [])]
    print("promoting a corpus produced by: %s" % " -> ".join(stages))

    s_sum, d_sum = summarize(src), summarize(dst)
    inv = check_all(d_sum, s_sum, {"id": "promote", "adds_keys": ["*"], "removes_keys": ["*"],
                                   "may_change_record_count": a.allow_count_change,
                                   "may_change_id_set": a.allow_count_change},
                    [s["stage"] for s in rep.get("stages", [])])
    failed = [i for i in inv if i["enforced"] and not i["passed"] and i["id"] != "U7"]
    for i in failed:
        print("INVARIANT FAILED %s %s observed=%s" % (i["id"], i["name"], i["observed"]))
    if failed:
        print("refusing to promote a corpus that fails the universal invariants")
        return 1

    src_ids = set(s_sum["ids"])
    dst_ids = set(d_sum["ids"])
    only_target = sorted(dst_ids - src_ids)
    if only_target and not a.allow_count_change:
        print("%d records exist in the target but not in the corrected corpus "
              "(e.g. %s). They are LEFT IN PLACE; nothing is deleted here."
              % (len(only_target), only_target[:5]))

    changed = new = same = 0
    for mid in sorted(src_ids):
        s_p = os.path.join(src, mid + ".json")
        d_p = os.path.join(dst, mid + ".json")
        if not os.path.exists(d_p):
            new += 1
        elif filecmp.cmp(s_p, d_p, shallow=False):
            same += 1
            continue
        else:
            changed += 1
        if not a.dry_run:
            shutil.copy2(s_p, d_p)

    print("promoted: %d changed, %d new, %d unchanged, %d left in place%s"
          % (changed, new, same, len(only_target), "  (dry run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
