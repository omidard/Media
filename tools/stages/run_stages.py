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


def stage_file(entry: dict) -> str:
    """The script a registry entry points at (defaults to <id>.py)."""
    return entry.get("file") or (entry["id"] + ".py")


def discover_stage_files(registered_files=()) -> tuple[list[str], list[str], list[str]]:
    """-> (stage ids from filenames, helper modules, files that look like an unnamed stage).

    A .py file whose name matches NN_snake_case.py is a stage. Anything else is a
    helper module, which is fine (agents share code that way) — unless it looks like
    a stage (it calls stagelib.run_stage()/main_guard(), or its docstring opens with
    STAGE:) AND no registry entry names it via `file`. Then it is a stage wearing a
    helper's name, which the chain would never execute, and that is a problem.
    """
    stages, helpers, suspect = [], [], []
    for f in sorted(os.listdir(HERE)):
        if not f.endswith(".py") or f in NON_STAGE_FILES:
            continue
        m = STAGE_FILE_RE.match(f)
        if m:
            stages.append(m.group(1))
            continue
        if f in registered_files:
            continue                      # registered explicitly by `file`
        with open(os.path.join(HERE, f), "r", encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        looks_like_a_stage = ("run_stage(" in body or "main_guard(" in body
                              or body.lstrip().startswith('"""STAGE')
                              or '"""STAGE:' in body[:400])
        (suspect if looks_like_a_stage else helpers).append(f)
    return stages, helpers, suspect


def check_registry(verbose=True) -> list[str]:
    """Return a list of problems; empty means the registry and disk agree."""
    reg = load_registry()
    problems = []
    registered = [s["id"] for s in reg["stages"]]
    registered_files = {stage_file(s) for s in reg["stages"]}
    on_disk, helpers, suspect = discover_stage_files(registered_files)

    for f in suspect:
        problems.append(
            "tools/stages/%s looks like a stage (it calls run_stage()/main_guard() or its "
            "docstring opens with STAGE:) but is neither named NN_snake_case.py nor "
            "registered in stages.json with an explicit \"file\". The chain would never "
            "execute it — a silent skip. Register it or rename it." % f)
    for f in on_disk:
        if f not in registered:
            problems.append(
                "tools/stages/%s.py exists but is NOT registered in stages.json — an "
                "unregistered stage would silently never run. Add a registry entry." % f)
    for entry in reg["stages"]:
        if entry.get("enabled", True) and not os.path.exists(os.path.join(HERE, stage_file(entry))):
            problems.append("stages.json registers %r but tools/stages/%s is missing"
                            % (entry["id"], stage_file(entry)))

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
        off = [s for s in reg["stages"] if not s.get("enabled", True)]
        for s_ in off:
            print("DISABLED (registered but WILL NOT RUN): %s — %s"
                  % (s_["id"], s_.get("disabled_reason", "no reason recorded")))
    return problems


def register_missing(verbose=True) -> int:
    """Add a registry entry for every NN-named stage file that has none.

    Four agents are writing stages concurrently, so a stage file usually appears
    before its registry row. This fills in a minimal, honest entry — owner inferred
    from the reserved range, findings scraped from the file's own `FINDINGS:` line —
    and marks it `registered_by` the harness so the owning agent knows to confirm it.
    It never enables a stage whose CLI cannot be driven by the runner.
    """
    reg = load_registry()
    have = {s["id"] for s in reg["stages"]}
    on_disk, _helpers, _suspect = discover_stage_files({stage_file(s) for s in reg["stages"]})
    ranges = []
    for r in reg.get("reserved_ranges", []):
        lo, hi = r["range"].split("-")
        ranges.append((int(lo), int(hi), r["owner"]))
    added = []
    for sid in on_disk:
        if sid in have:
            continue
        path = os.path.join(HERE, sid + ".py")
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        m = re.search(r"FINDINGS?:\s*([A-Z0-9\-, /()]+)", body)
        findings = sorted({f.strip() for f in re.findall(r"[A-Z]+-\d+", m.group(1))}) if m \
            else sorted(set(re.findall(r"\b(?:MAP|NM|PROV|PIPE|COV|SCHEMA|STALE|UX|NAME|MEDIA-WEB)-\d+", body)))[:12]
        num = int(sid[:2])
        owner = next((o for lo, hi, o in ranges if lo <= num <= hi), None)
        flags = supported_flags(path)
        ok_cli = {"--in", "--out"} <= flags
        title = (body.split('"""', 2)[1].strip().splitlines()[0] if '"""' in body else sid)
        entry = {"id": sid, "title": title[:160], "owner": owner, "findings": findings,
                 "reads": ["corpus"], "writes": ["corpus"],
                 "after": [s["id"] for s in reg["stages"] if int(s["id"][:2]) < num][-1:],
                 "may_change_record_count": False, "may_change_id_set": False,
                 "adds_keys": ["provenance.transforms"], "removes_keys": [],
                 "enabled": bool(ok_cli),
                 "registered_by": "pipeline harness --register-missing; the owning agent "
                                  "must confirm findings, adds_keys and ordering"}
        if not ok_cli:
            entry["disabled_reason"] = ("CLI does not accept --in/--out, so the runner "
                                        "cannot drive it (tools/stages/README.md section 3)")
        pos = next((k for k, st in enumerate(reg["stages"]) if int(st["id"][:2]) > num),
                   len(reg["stages"]))
        reg["stages"].insert(pos, entry)
        added.append((sid, owner, entry["enabled"], findings))
    if added:
        with open(os.path.join(HERE, "stages.json"), "w", encoding="utf-8") as fh:
            json.dump(reg, fh, indent=1)
    if verbose:
        for sid, owner, en, fnd in added:
            print("registered %s (owner=%s enabled=%s findings=%s)" % (sid, owner, en, fnd))
        if not added:
            print("nothing to register: every stage file already has an entry")
    return len(added)


# --------------------------------------------------------------------- utilities


def supported_flags(script: str) -> set:
    """Which CLI flags a stage accepts, read from its own --help.

    Stages written before the report/limit part of the contract still plug in: the
    runner passes only what they accept and records the difference, instead of
    failing on an unrecognised argument.
    """
    try:
        out = subprocess.run([sys.executable, script, "--help"], capture_output=True,
                             text=True, timeout=120).stdout
    except Exception as exc:                                # noqa: BLE001 - reported
        print("  WARN could not read --help from %s: %s" % (script, exc))
        return {"--in", "--out", "--report"}
    return set(re.findall(r"--[a-z][a-z0-9-]*", out))


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
        script = os.path.join(HERE, stage_file(entry))
        flags = supported_flags(script)
        missing = {"--in", "--out"} - flags
        if missing:
            print("STAGE %s does not accept %s — see tools/stages/README.md section 3"
                  % (sid, ", ".join(sorted(missing))))
            chain["stages"].append({"stage": sid, "rc": None,
                                    "fatal": "CLI does not accept %s" % sorted(missing)})
            chain["ok"] = False
            break
        cmd = [sys.executable, script, "--in", cur_in, "--out", out_dir]
        # A stage may predate the report/limit part of the contract; pass only what it
        # accepts, and record that its report was synthesised rather than pretend it
        # produced one.
        if "--report" in flags:
            cmd += ["--report", report_path]
        if args.limit and "--limit" in flags:
            cmd += ["--limit", str(args.limit)]
        fp_before = dir_fingerprint(cur_in)
        print("\n>> %s" % sid)
        rc = subprocess.call(cmd)
        rec = {"stage": sid, "rc": rc, "out_dir": os.path.relpath(out_dir, REPO)}

        if os.path.exists(report_path):
            with open(report_path) as fh:
                rec["report"] = json.load(fh)
        else:
            rec["report_source"] = ("stage produced no report; the runner's invariant "
                                    "pass is the only record of what it did")
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
    p.add_argument("--register-missing", action="store_true",
                   help="add a minimal registry entry for every unregistered stage file")
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

    if args.register_missing:
        register_missing()
        return 1 if check_registry() else 0
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
