#!/usr/bin/env python3
"""
stagelib — the shared runtime every MediaDB transform stage uses.

A stage reads a corpus directory of per-medium JSON files and writes a corrected
corpus directory. This module supplies the argv contract, deterministic IO,
copy-through, the provenance stamp, and the JSON report, so that a stage author
writes only the transform.

See tools/stages/README.md for the full contract. The rules this module enforces
mechanically:

  * --in and --out are required and must differ; --out is never data/media/
  * every input record appears in the output (copy-through)
  * output bytes are deterministic (indent=1, ensure_ascii=False, key order kept)
  * a stage that raises exits non-zero; a failed assertion exits non-zero
  * a report is always written, including on failure

Usage from a stage:

    from stagelib import run_stage, stamp, Report
    def transform(rec, rep): ...      # return True iff rec changed
    if __name__ == "__main__":
        run_stage("30_label_derived", "1.0.0", transform)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
FROZEN_CORPUS = os.path.join(REPO, "data", "media")

__all__ = [
    "Report", "StageError", "run_stage", "stamp", "read_record", "write_record",
    "iter_corpus", "corpus_ids", "load_registry", "REPO", "TOOLS", "FROZEN_CORPUS",
]


class StageError(RuntimeError):
    """Raised when a stage's own contract is violated. Always fatal."""


def _utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- IO


def read_record(path: str) -> dict:
    """Load one medium record. A non-object or unparseable file is fatal."""
    with open(path, "r", encoding="utf-8") as fh:
        rec = json.load(fh)
    if not isinstance(rec, dict):
        raise StageError("%s: record is %s, expected object" % (path, type(rec).__name__))
    return rec


def write_record(path: str, rec: dict) -> None:
    """Write one medium record with deterministic bytes.

    indent=1 + ensure_ascii=False + preserved key order matches the shipped
    corpus's formatting, so a stage that changes nothing produces a zero diff.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, ensure_ascii=False, sort_keys=False)
    os.replace(tmp, path)


def corpus_ids(d: str, limit: int | None = None) -> list[str]:
    """Sorted medium ids in a corpus directory (filename stem == id)."""
    ids = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
    return ids[:limit] if limit else ids


def iter_corpus(d: str, limit: int | None = None):
    for mid in corpus_ids(d, limit):
        yield mid, read_record(os.path.join(d, mid + ".json"))


# ---------------------------------------------------------------------- report


class Report:
    """A stage's structured account of what it did.

    Counts always carry their denominator. Assertions are the stage's own
    post-conditions; a failed one is fatal. `unresolved` is how the stage stays
    honest about what it could not determine — never fill an unknown with a guess.
    """

    def __init__(self, stage: str, version: str, in_dir: str, out_dir: str,
                 sample: bool = False, inputs=None):
        self.stage = stage
        self.version = version
        self.in_dir = in_dir
        self.out_dir = out_dir
        self.sample = sample
        self.inputs = list(inputs or [])
        self.started_utc = _utc()
        self._t0 = time.time()
        self.n_in = 0
        self.n_out = 0
        self.n_changed = 0
        self.counters: dict[str, dict] = {}
        self.assertions: list[dict] = []
        self._unresolved: dict[str, dict] = {}
        self.errors: list[str] = []
        self.examples: dict[str, list] = {}

    # -- counting ----------------------------------------------------------
    def count(self, name: str, n: int = 1, of: int | None = None) -> None:
        """Increment a named counter. `of` records the denominator."""
        c = self.counters.setdefault(name, {"n": 0, "of": None})
        c["n"] += n
        if of is not None:
            c["of"] = of

    def set_denominator(self, name: str, of: int) -> None:
        self.counters.setdefault(name, {"n": 0, "of": None})["of"] = of

    def example(self, name: str, value, cap: int = 5) -> None:
        """Record up to `cap` worked examples so a reviewer can spot-check."""
        lst = self.examples.setdefault(name, [])
        if len(lst) < cap:
            lst.append(value)

    def unresolved(self, name: str, n: int, of: int, why: str) -> None:
        self._unresolved[name] = {"n": n, "of": of, "why": why}

    # -- assertions --------------------------------------------------------
    def assert_true(self, name: str, ok: bool, observed=None, expected=None) -> None:
        self.assertions.append({"name": name, "passed": bool(ok),
                                "observed": observed, "expected": expected})

    def assert_eq(self, name: str, observed, expected) -> None:
        self.assert_true(name, observed == expected, observed, expected)

    def assert_le(self, name: str, observed, expected) -> None:
        self.assert_true(name, observed <= expected, observed, expected)

    @property
    def failed_assertions(self) -> list[dict]:
        return [a for a in self.assertions if not a["passed"]]

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "version": self.version,
            "started_utc": self.started_utc,
            "duration_s": round(time.time() - self._t0, 2),
            "sample": self.sample,
            "in_dir": os.path.relpath(self.in_dir, REPO),
            "out_dir": os.path.relpath(self.out_dir, REPO),
            "n_in": self.n_in,
            "n_out": self.n_out,
            "n_changed": self.n_changed,
            "inputs": self.inputs,
            "counters": self.counters,
            "assertions": self.assertions,
            "unresolved": self._unresolved,
            "examples": self.examples,
            "errors": self.errors,
        }

    def write(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1, ensure_ascii=False)


# ------------------------------------------------------------------ provenance


def stamp(rec: dict, stage: str, version: str, changes) -> None:
    """Append this stage's transform record to the medium's provenance.

    Idempotent by construction: re-running a stage on its own output produces no
    `changes`, so `transform()` returns False and stamp() is never called again.
    """
    prov = rec.setdefault("provenance", {})
    if not isinstance(prov, dict):
        raise StageError("provenance is %s, expected object" % type(prov).__name__)
    tr = prov.setdefault("transforms", [])
    if not isinstance(tr, list):
        raise StageError("provenance.transforms is %s, expected list" % type(tr).__name__)
    tr.append({
        "stage": stage,
        "version": version,
        "date": _dt.date.today().isoformat(),
        "changes": sorted(set(changes)) if not isinstance(changes, str) else [changes],
    })


# -------------------------------------------------------------------- registry


def load_registry() -> dict:
    with open(os.path.join(HERE, "stages.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def registry_entry(stage: str) -> dict:
    for s in load_registry()["stages"]:
        if s["id"] == stage:
            return s
    raise StageError(
        "stage %r is not registered in tools/stages/stages.json — register it or the "
        "runner will refuse to run the chain (an unregistered stage is a silent skip)"
        % stage)


# ------------------------------------------------------------------- the runner


def _parse_args(stage: str, argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=stage,
        description="MediaDB transform stage. Reads a corpus directory, writes a "
                    "corrected corpus directory. See tools/stages/README.md.")
    p.add_argument("--in", dest="in_dir", required=True,
                   help="input corpus directory (read-only)")
    p.add_argument("--out", dest="out_dir", required=True,
                   help="output corpus directory (created; must not be data/media)")
    p.add_argument("--report", dest="report", default=None,
                   help="path for the JSON report (default: <out>/../report.json)")
    p.add_argument("--limit", type=int, default=None,
                   help="process only the first N ids (sample runs)")
    p.add_argument("--dry-run", action="store_true",
                   help="compute and report, write no corpus")
    return p.parse_args(argv)


def run_stage(stage: str, version: str, transform, finalize=None, inputs=None,
              argv=None) -> int:
    """Execute a stage end to end. Returns the process exit code.

    `transform(rec, report) -> bool` mutates a record in place and returns True
    iff it changed it. `finalize(report)` runs once after the corpus, and is where
    the stage declares its own post-conditions.
    """
    args = _parse_args(stage, argv)
    in_dir = os.path.abspath(args.in_dir)
    out_dir = os.path.abspath(args.out_dir)

    if not os.path.isdir(in_dir):
        sys.stderr.write("FATAL %s: --in %s is not a directory\n" % (stage, in_dir))
        return 2
    if in_dir == out_dir:
        sys.stderr.write("FATAL %s: --in and --out must differ (a stage never "
                         "rewrites its input)\n" % stage)
        return 2
    if os.path.abspath(out_dir) == os.path.abspath(FROZEN_CORPUS):
        sys.stderr.write("FATAL %s: refusing to write to the frozen corpus %s. "
                         "Stages write to a staging tree; promotion is a separate, "
                         "backed-up step (make promote).\n" % (stage, FROZEN_CORPUS))
        return 2

    report_path = args.report or os.path.join(os.path.dirname(out_dir), "report.json")
    rep = Report(stage, version, in_dir, out_dir, sample=bool(args.limit),
                 inputs=inputs)

    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    ids = corpus_ids(in_dir, args.limit)
    rep.n_in = len(ids)

    try:
        for mid in ids:
            rec = read_record(os.path.join(in_dir, mid + ".json"))
            if rec.get("id") != mid:
                raise StageError(
                    "%s: record id %r does not match filename stem %r — the corpus "
                    "keys records by filename, so this must be fixed before any "
                    "stage runs" % (mid, rec.get("id"), mid))
            changed = bool(transform(rec, rep))
            if changed:
                rep.n_changed += 1
            if not args.dry_run:
                write_record(os.path.join(out_dir, mid + ".json"), rec)
                rep.n_out += 1
        if finalize is not None:
            finalize(rep)
    except Exception as exc:                      # noqa: BLE001 - reported, then re-raised as exit
        rep.errors.append("%s: %s" % (type(exc).__name__, exc))
        rep.write(report_path)
        sys.stderr.write("FATAL %s: %s\n%s\n" % (stage, exc, traceback.format_exc()))
        return 1

    if not args.dry_run and rep.n_out != rep.n_in:
        rep.errors.append("copy-through violated: n_in=%d n_out=%d" % (rep.n_in, rep.n_out))

    rep.write(report_path)

    bad = rep.failed_assertions
    for a in bad:
        sys.stderr.write("ASSERTION FAILED %s.%s observed=%r expected=%r\n"
                         % (stage, a["name"], a["observed"], a["expected"]))
    if rep.errors:
        for e in rep.errors:
            sys.stderr.write("ERROR %s: %s\n" % (stage, e))

    print("%-28s in=%d out=%d changed=%d  assertions=%d/%d  report=%s"
          % (stage, rep.n_in, rep.n_out, rep.n_changed,
             len(rep.assertions) - len(bad), len(rep.assertions),
             os.path.relpath(report_path, REPO)))
    return 1 if (bad or rep.errors) else 0


def main_guard(stage, version, transform, finalize=None, inputs=None):
    sys.exit(run_stage(stage, version, transform, finalize=finalize, inputs=inputs))
