#!/usr/bin/env python3
"""
run_stages — the stage-chain runner.

Composes the registered transform stages in their fixed, documented order over the
corpus and enforces the contract in tools/stages/README.md. This is the program
that makes the resource reproducible again: the frozen snapshot in data/media is
the sole surviving copy of the inputs (PIPE-01), so the chain of stages *is* the
build.

    data/media (read-only)
      -> data/_rebuild/stages/00_baseline/media
      -> data/_rebuild/stages/10_normalize_schema/media
      -> ...
      -> data/_rebuild/media  (symlink to the last stage's output)

What it enforces, on top of each stage's own assertions:
  * every file in tools/stages/ that looks like a stage is registered (--check);
    an unregistered stage is a hard error, never a silent skip
  * declared ordering (`after`) is respected by the registry order
  * the universal invariants in invariants.py after EVERY stage
  * the input corpus is not mutated by the stage that read it
  * idempotence: on sample runs each stage is re-run on its own output and the
    bytes must be identical

Exit code is non-zero on the first failure; nothing is ever promoted to data/media
by this program (see `make promote`).

Usage:
  python3 tools/stages/run_stages.py --check
  python3 tools/stages/run_stages.py --sample            # chain over the sample corpus
  python3 tools/stages/run_stages.py                     # chain over all 13,515 media
  python3 tools/stages/run_stages.py --only 10_normalize_schema --sample
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from invariants import check_all, summarize          # noqa: E402
from stagelib import REPO, load_registry             # noqa: E402

STAGE_FILE_RE = re.compile(r"^(\d{2}_[a-z0-9_]+)\.py$")
NON_STAGE_FILES = {"stagelib.py", "run_stages.py", "invariants.py", "make_sample.py"}
FROZEN = os.path.join(REPO, "data", "media")


# ----------------------------------------------------------------- registry check


def discover_stage_files() -> tuple[list[str], list[str], list[str]]:
    """-> (stage ids, helper modules, files that look like an unnamed stage).

    A .py file whose name matches NN_snake_case.py is a stage. Anything else is a
    helper module, which is fine (siblings share code that way) — unless it calls
    stagelib.run_stage(), which means it is a stage wearing a helper's name and
    would never be executed by the chain. That is reported as a problem.
    """
    stages, helpers, suspect = [], [], []
    for f in sorted(os.listdir(HERE)):
        if not f.endswith(".py") or f in NON_STAGE_FILES:
            continue
        m = STAGE_FILE_RE.match(f)
        if m:
            stages.append(m.group(1))
            continue
        with open(os.path.join(HERE, f), "r", encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        (suspect if "run_stage(" in body else helpers).append(f)
    return stages, helpers, suspect


def check_registry(verbose=True) -> list[str]:
    """Return a list of problems; empty means the registry and disk agree."""
    reg = load_registry()
    problems = []
    registered = [s["id"] for s in reg["stages"]]
    on_disk, helpers, suspect = discover_stage_files()

    for f in suspect:
        problems.append(
            "tools/stages/%s calls run_stage() but is not named NN_snake_case.py, so the "
            "chain would never execute it. Rename it to its ordering prefix and register "
            "it in stages.json." % f)
    for f in on_disk:
        if f not in registered:
            problems.append(
                "tools/stages/%s.py exists but is NOT registered in stages.json — an "
                "unregistered stage would silently never run. Add a registry entry." % f)
    for sid in registered:
        if sid not in on_disk and next(s for s in reg["stages"] if s["id"] == sid).get("enabled", True):
            problems.append("stages.json registers %r but tools/stages/%s.py is missing" % (sid, sid))

    # ordering: numeric prefix must be non-decreasing, and every `after` must precede
    seen = []
    last_num = -1
    for s in reg["stages"]:
        num = int(s["id"][:2])
        if num < last_num:
            problems.append("stages.json is out of order at %r (prefix %02d after %02d)"
                            % (s["id"], num, last_num))
        last_num = num
        for dep in s.get("after", []):
            if dep not in seen:
                problems.append("stage %r declares after=%r but %r does not precede it"
                                % (s["id"], dep, dep))
        seen.append(s["id"])

    # range ownership
    ranges = []
    for r in reg.get("reserved_ranges", []):
        lo, hi = r["range"].split("-")
        ranges.append((int(lo), int(hi), r["owner"]))
    for s in reg["stages"]:
        num = int(s["id"][:2])
        owner = next((o for lo, hi, o in ranges if lo <= num <= hi), None)
        if owner and s.get("owner") and s["owner"] != owner:
            problems.append("stage %r is owned by %r but %02d is in the %r range"
                            % (s["id"], s["owner"], num, owner))

    if verbose:
        if helpers:
            print("helper modules (not stages, not executed by the chain): %s"
                  % ", ".join(helpers))
        if problems:
            for p in problems:
                print("REGISTRY PROBLEM:", p)
        else:
            print("registry OK: %d stage(s) registered, %d on disk, order and ranges consistent"
                  % (len(registered), len(on_disk)))
    return problems


# --------------------------------------------------------------------- utilities


def dir_fingerprint(d: str, n: int = 40) -> str:
    """sha256 over the first n records (sorted), used to prove input immutability."""
    h = hashlib.sha256()
    for f in sorted(os.listdir(d))[:n]:
        if not f.endswith(".json"):
            continue
        h.update(f.encode())
        with open(os.path.join(d, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def dirs_identical(a: str, b: str) -> tuple[bool, list[str]]:
    fa = sorted(x for x in os.listdir(a) if x.endswith(".json"))
    fb = sorted(x for x in os.listdir(b) if x.endswith(".json"))
    if fa != fb:
        return False, ["file list differs: %d vs %d" % (len(fa), len(fb))]
    diffs = []
    for f in fa:
        with open(os.path.join(a, f), "rb") as fh1, open(os.path.join(b, f), "rb") as fh2:
            if fh1.read() != fh2.read():
                diffs.append(f)
                if len(diffs) >= 5:
                    break
    return not diffs, diffs


# ------------------------------------------------------------------- the chain


def run_chain(args) -> int:
    problems = check_registry(verbose=False)
    if problems:
        for p in problems:
            print("REGISTRY PROBLEM:", p)
        print("\nrefusing to run the chain with an inconsistent registry.")
        return 2

    reg = load_registry()
    stages = [s for s in reg["stages"] if s.get("enabled", True)]
    if args.only:
        stages = [s for s in stages if s["id"] in args.only]
        if not stages:
            print("no enabled stage matches --only %s" % args.only)
            return 2
    if args.from_stage:
        idx = [i for i, s in enumerate(stages) if s["id"] == args.from_stage]
        stages = stages[idx[0]:] if idx else stages
    if args.to_stage:
        idx = [i for i, s in enumerate(stages) if s["id"] == args.to_stage]
        stages = stages[:idx[0] + 1] if idx else stages

    in_dir = os.path.abspath(args.in_dir)
    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)
    stages_root = os.path.join(work, "stages")
    os.makedirs(stages_root, exist_ok=True)

    print("chain: %d stage(s) | input %s (%d records) | work %s"
          % (len(stages), os.path.relpath(in_dir, REPO),
             len([f for f in os.listdir(in_dir) if f.endswith('.json')]),
             os.path.relpath(work, REPO)))

    chain = {
        "started_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_corpus": os.path.relpath(in_dir, REPO),
        "sample": bool(args.sample),
        "stages": [],
        "ok": True,
    }
    prev_summary = summarize(in_dir)
    chain["input_summary"] = {k: v for k, v in prev_summary.items()
                              if k not in ("ids", "dir")}
    run_so_far: list[str] = []
    cur_in = in_dir

    for entry in stages:
        sid = entry["id"]
        out_dir = os.path.join(stages_root, sid, "media")
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)            # regenerated artifact, never source data
        os.makedirs(out_dir, exist_ok=True)
        report_path = os.path.join(stages_root, sid, "report.json")
        script = os.path.join(HERE, sid + ".py")
        cmd = [sys.executable, script, "--in", cur_in, "--out", out_dir,
               "--report", report_path]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        fp_before = dir_fingerprint(cur_in)
        print("\n>> %s" % sid)
        rc = subprocess.call(cmd)
        rec = {"stage": sid, "rc": rc, "out_dir": os.path.relpath(out_dir, REPO)}

        if os.path.exists(report_path):
            with open(report_path) as fh:
                rec["report"] = json.load(fh)
        if rc != 0:
            rec["fatal"] = "stage exited %d" % rc
            chain["stages"].append(rec)
            chain["ok"] = False
            break

        # input immutability
        if dir_fingerprint(cur_in) != fp_before:
            rec["fatal"] = "stage mutated its input corpus %s" % cur_in
            chain["stages"].append(rec)
            chain["ok"] = False
            break

        # universal invariants
        cur_summary = summarize(out_dir)
        run_so_far.append(sid)
        inv = check_all(prev_summary, cur_summary, entry, run_so_far)
        rec["invariants"] = inv
        failed = [i for i in inv if i["enforced"] and not i["passed"]]
        for i in failed:
            print("INVARIANT FAILED %s %s observed=%s expected=%s  %s"
                  % (i["id"], i["name"], i["observed"], i["expected"], i["note"]))
        # idempotence (sample runs only: it doubles the work)
        if args.sample and not args.skip_idempotence:
            idem_dir = os.path.join(stages_root, sid, "media_idem")
            if os.path.isdir(idem_dir):
                shutil.rmtree(idem_dir)
            os.makedirs(idem_dir, exist_ok=True)
            rc2 = subprocess.call([sys.executable, script, "--in", out_dir, "--out", idem_dir,
                                   "--report", os.path.join(stages_root, sid, "report_idem.json")])
            same, diffs = dirs_identical(out_dir, idem_dir)
            rec["idempotent"] = bool(same and rc2 == 0)
            if not rec["idempotent"]:
                print("IDEMPOTENCE FAILED %s: rc=%d differing=%s" % (sid, rc2, diffs))
                failed.append({"id": "IDEM", "name": "idempotent"})
        chain["stages"].append(rec)
        if failed:
            chain["ok"] = False
            break
        prev_summary = cur_summary
        cur_in = out_dir

    # publish the chain result
    if chain["ok"] and not args.only:
        final = os.path.join(work, "media")
        if os.path.islink(final):
            os.unlink(final)
        elif os.path.isdir(final):
            shutil.rmtree(final)
        os.symlink(os.path.relpath(cur_in, work), final)
        chain["final_corpus"] = os.path.relpath(final, REPO)
        print("\nfinal corpus -> %s (symlink to %s)"
              % (os.path.relpath(final, REPO), os.path.relpath(cur_in, REPO)))

    chain_path = os.path.join(work, "chain_report.json")
    with open(chain_path, "w") as fh:
        json.dump(chain, fh, indent=1)
    print("chain report: %s | ok=%s" % (os.path.relpath(chain_path, REPO), chain["ok"]))
    return 0 if chain["ok"] else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="run_stages", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true",
                   help="verify registry <-> filesystem consistency and exit")
    p.add_argument("--sample", action="store_true",
                   help="run over data/_rebuild/sample/media (build it with make sample)")
    p.add_argument("--in", dest="in_dir", default=None, help="input corpus directory")
    p.add_argument("--work", default=None, help="staging root")
    p.add_argument("--only", nargs="*", default=None, help="run only these stage ids")
    p.add_argument("--from", dest="from_stage", default=None)
    p.add_argument("--to", dest="to_stage", default=None)
    p.add_argument("--limit", type=int, default=None, help="first N records only")
    p.add_argument("--skip-idempotence", action="store_true")
    args = p.parse_args(argv)

    if args.check:
        return 1 if check_registry() else 0

    if args.sample:
        args.in_dir = args.in_dir or os.path.join(REPO, "data", "_rebuild", "sample", "media")
        args.work = args.work or os.path.join(REPO, "data", "_rebuild", "sample_run")
        if not os.path.isdir(args.in_dir):
            print("sample corpus %s does not exist — run `make sample` first"
                  % os.path.relpath(args.in_dir, REPO))
            return 2
    else:
        args.in_dir = args.in_dir or FROZEN
        args.work = args.work or os.path.join(REPO, "data", "_rebuild")
    return run_chain(args)


if __name__ == "__main__":
    sys.exit(main())
