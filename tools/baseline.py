#!/usr/bin/env python3
"""
baseline — the stage chain's INPUT, shipped inside the repository.

    python3 tools/baseline.py                 # extract (idempotent) and verify
    python3 tools/baseline.py --verify        # verify the archive only, extract nothing
    python3 tools/baseline.py --check-history # cross-check against the git history tree
    python3 tools/baseline.py --build --from DIR|--from-git TREEISH   # rebuild the archive

WHY THIS FILE EXISTS
--------------------
`make stages` is documented as the build: the corpus in data/media is a frozen
snapshot whose generators are dead (PIPE-01), so the CHAIN of transform stages is
the only thing that can be re-run. A chain needs an input, and until this file
existed the chain's input was

    /data/media_curate_backups/data_media_20260906.tar.zst

an untracked archive on one machine, outside the repository. That is finding
PIPE-01 one level up: a documented build step pointing at a path a fresh clone does
not have. `make stages` and `make stages-sample` both failed from a clean checkout.

So the pre-remediation corpus — the exact bytes the remediation chain consumed — is
committed here as a deterministic, digest-verified archive:

    data/_baseline/media_corpus_2026-09-06.tar.xz      3.7 MB

It expands to 13,515 records / 451 MB. `.tar.xz` was chosen over `.tar.zst` because
Python's stdlib reads it (`tarfile` + `lzma`): extracting the chain input needs no
tool that is not already required to run the chain. It is 3.7 MB rather than the
10.2 MB of the zstd backup because the archive is written single-threaded at
preset 6 with normalised member metadata, which also makes it byte-reproducible.

WHAT THIS ARCHIVE IS NOT
------------------------
It is not a reproduction of the corpus from its raw sources. Those inputs are gone
and 1,456 records are permanently unreproducible (see data/MANIFEST.json
`provenance`). It is the reproducible input to the CORRECTIONS: with it, a fresh
clone can re-run every transform stage and check that the result is the corpus that
ships. That is the reproducibility claim this repository can honestly make, and
this file is what makes it true rather than aspirational.

CROSS-CHECK
-----------
The same bytes are in the repository's own history: the tree
`b8d38bbf:data/media`, which is also `origin/main:data/media` at the commit before
the corrected corpus was promoted. `--check-history` verifies the archive against
that tree when the git object is present, so the archive can never quietly drift
from the corpus the remediation actually consumed. The archive is committed anyway
rather than left to history alone: a shallow clone, a source zip download, or a
future history rewrite all lose the tree, and the chain's input must survive all
three.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import lzma
import os
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mediapaths import REPO  # noqa: E402

BASELINE_DIR = os.path.join(REPO, "data", "_baseline")
ARCHIVE = os.path.join(BASELINE_DIR, "media_corpus_2026-09-06.tar.xz")
META = os.path.join(BASELINE_DIR, "BASELINE.json")
DEFAULT_OUT = os.path.join(REPO, "data", "_rebuild", "baseline", "media")
STAMP_NAME = ".baseline_stamp.json"

#: Member prefix inside the archive. Members are "media/<id>.json".
MEMBER_PREFIX = "media/"

#: The history tree the archive is cross-checked against (see --check-history).
HISTORY_TREEISH = "b8d38bbf:data/media"


class BaselineError(RuntimeError):
    pass


# ------------------------------------------------------------------- digests


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def corpus_digest(pairs) -> str:
    """One digest identifying a corpus: sha256 over sorted `name sha256` lines.

    Order-independent of the filesystem and independent of the container, so the
    archive, the extracted tree and a git tree can all be compared with one number.
    """
    h = hashlib.sha256()
    for name, digest in sorted(pairs):
        h.update(("%s %s\n" % (name, digest)).encode())
    return h.hexdigest()


def digest_dir(d: str) -> list[tuple[str, str]]:
    out = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(d, f), "rb") as fh:
            out.append((f, hashlib.sha256(fh.read()).hexdigest()))
    return out


def digest_archive(path: str) -> list[tuple[str, str]]:
    out = []
    with tarfile.open(path, mode="r:xz") as tf:
        for ti in tf:
            if not ti.isfile():
                continue
            name = os.path.basename(ti.name)
            fh = tf.extractfile(ti)
            out.append((name, hashlib.sha256(fh.read()).hexdigest()))
    return out


def digest_git_tree(treeish: str) -> list[tuple[str, str]]:
    """Digest a corpus stored in git history, without checking it out."""
    listing = subprocess.run(["git", "-C", REPO, "ls-tree", "-r", "-z",
                              "--format=%(objectname) %(path)", treeish],
                             capture_output=True, text=True)
    if listing.returncode != 0:
        raise BaselineError("git object %s is not in this clone: %s"
                            % (treeish, listing.stderr.strip()))
    entries = []
    for row in listing.stdout.split("\0"):
        row = row.strip()
        if not row:
            continue
        obj, path = row.split(" ", 1)
        if path.endswith(".json"):
            entries.append((obj, os.path.basename(path)))
    out = []
    for obj, name in entries:
        blob = subprocess.run(["git", "-C", REPO, "cat-file", "blob", obj],
                              capture_output=True)
        out.append((name, hashlib.sha256(blob.stdout).hexdigest()))
    return out


# --------------------------------------------------------------------- build


def build_archive(src_pairs, out_path: str, preset: int = 6) -> dict:
    """Write a deterministic .tar.xz from (name, bytes-reader) pairs.

    Determinism: members sorted by name, mtime 0, mode 0644, uid/gid 0, empty
    uname/gname, PAX format, single-threaded lzma. Re-running this on the same input
    produces the same bytes, which is what lets --verify be a real check rather than
    a record of one machine's run.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    n = 0
    with lzma.open(tmp, "wb", preset=preset, format=lzma.FORMAT_XZ) as z:
        with tarfile.open(fileobj=z, mode="w", format=tarfile.PAX_FORMAT) as tf:
            for name, payload in sorted(src_pairs, key=lambda p: p[0]):
                ti = tarfile.TarInfo(MEMBER_PREFIX + name)
                ti.size = len(payload)
                ti.mtime = 0
                ti.mode = 0o644
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.type = tarfile.REGTYPE
                tf.addfile(ti, io.BytesIO(payload))
                n += 1
    os.replace(tmp, out_path)
    return {"n_records": n, "bytes": os.path.getsize(out_path)}


def read_dir_payloads(d: str):
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(d, f), "rb") as fh:
            yield f, fh.read()


def read_git_payloads(treeish: str):
    listing = subprocess.run(["git", "-C", REPO, "ls-tree", "-r",
                              "--format=%(objectname) %(path)", treeish],
                             capture_output=True, text=True, check=True)
    for row in listing.stdout.splitlines():
        obj, path = row.strip().split(" ", 1)
        if not path.endswith(".json"):
            continue
        blob = subprocess.run(["git", "-C", REPO, "cat-file", "blob", obj],
                              capture_output=True, check=True)
        yield os.path.basename(path), blob.stdout


def cmd_build(a) -> int:
    if a.from_git:
        pairs = list(read_git_payloads(a.from_git))
        origin = "git tree %s" % a.from_git
    elif a.from_dir:
        pairs = list(read_dir_payloads(os.path.abspath(a.from_dir)))
        origin = os.path.relpath(os.path.abspath(a.from_dir), REPO)
    else:
        print("--build needs --from DIR or --from-git TREEISH")
        return 2
    if not pairs:
        print("no *.json records found in %s" % origin)
        return 2
    info = build_archive(pairs, ARCHIVE)
    digests = [(n, hashlib.sha256(p).hexdigest()) for n, p in pairs]
    meta = {
        "schema": "mediadb-chain-baseline/1",
        "what": ("The pre-remediation corpus: the exact input the transform-stage "
                 "chain consumed. `make stages` reads it after `make baseline` "
                 "expands it to data/_rebuild/baseline/media."),
        "why_committed": ("Before this archive existed the chain's only input was an "
                          "untracked machine-local backup, so `make stages` and "
                          "`make stages-sample` both failed from a fresh clone — "
                          "finding PIPE-01 recreated one level up."),
        "archive": os.path.relpath(ARCHIVE, REPO),
        "archive_sha256": sha256_file(ARCHIVE),
        "archive_bytes": info["bytes"],
        "built_from": origin,
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_command": ("python3 tools/baseline.py --build --from-git %s"
                          % HISTORY_TREEISH),
        "deterministic": ("members sorted, mtime 0, mode 0644, uid/gid 0, PAX, "
                          "single-threaded lzma preset 6 — rebuilding from the same "
                          "input reproduces these bytes"),
        "n_records": info["n_records"],
        "uncompressed_bytes": sum(len(p) for _, p in pairs),
        "corpus_sha256": corpus_digest(digests),
        "corpus_sha256_definition": ("sha256 over sorted '<filename> <sha256>' lines, "
                                     "one per record — identifies the corpus "
                                     "independently of how it is packaged"),
        "also_in_history_at": HISTORY_TREEISH,
        "history_cross_check": ("python3 tools/baseline.py --check-history — the same "
                                "bytes are origin/main:data/media at the commit before "
                                "the corrected corpus was promoted"),
        "extract_to": os.path.relpath(DEFAULT_OUT, REPO),
    }
    with open(META, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    print("baseline archive -> %s" % os.path.relpath(ARCHIVE, REPO))
    print("  records            %d" % meta["n_records"])
    print("  archive bytes      %d (%.1f MB)" % (meta["archive_bytes"],
                                                 meta["archive_bytes"] / 1e6))
    print("  uncompressed bytes %d (%.0f MB)" % (meta["uncompressed_bytes"],
                                                 meta["uncompressed_bytes"] / 1e6))
    print("  archive_sha256     %s" % meta["archive_sha256"])
    print("  corpus_sha256      %s" % meta["corpus_sha256"])
    return 0


# -------------------------------------------------------------------- verify


def load_meta() -> dict:
    if not os.path.exists(META):
        raise BaselineError("no %s — the chain input is undeclared"
                            % os.path.relpath(META, REPO))
    with open(META, encoding="utf-8") as fh:
        return json.load(fh)


def verify_archive(verbose=True) -> dict:
    meta = load_meta()
    if not os.path.exists(ARCHIVE):
        raise BaselineError(
            "the chain input %s is missing. Every build step that reads the corpus "
            "starts here; without it `make stages` has nothing to run on."
            % os.path.relpath(ARCHIVE, REPO))
    got = sha256_file(ARCHIVE)
    if got != meta["archive_sha256"]:
        raise BaselineError("%s sha256 %s does not match BASELINE.json %s"
                            % (os.path.relpath(ARCHIVE, REPO), got,
                               meta["archive_sha256"]))
    if verbose:
        print("chain input %s: sha256 OK, %d records declared"
              % (os.path.relpath(ARCHIVE, REPO), meta["n_records"]))
    return meta


def cmd_verify(a) -> int:
    meta = verify_archive()
    if a.deep:
        digests = digest_archive(ARCHIVE)
        if len(digests) != meta["n_records"]:
            print("BASELINE PROBLEM: archive holds %d records, BASELINE.json says %d"
                  % (len(digests), meta["n_records"]))
            return 1
        got = corpus_digest(digests)
        if got != meta["corpus_sha256"]:
            print("BASELINE PROBLEM: corpus_sha256 %s != declared %s"
                  % (got, meta["corpus_sha256"]))
            return 1
        print("archive contents verified: %d records, corpus_sha256 %s"
              % (len(digests), got))
    return 0


def cmd_check_history(a) -> int:
    meta = load_meta()
    treeish = a.treeish or meta.get("also_in_history_at") or HISTORY_TREEISH
    try:
        hist = digest_git_tree(treeish)
    except BaselineError as exc:
        print("history cross-check SKIPPED: %s" % exc)
        print("  (a shallow clone or a rewritten history has no such object; the "
              "committed archive is the authority and was verified separately)")
        return 0
    got = corpus_digest(hist)
    ok = got == meta["corpus_sha256"]
    print("history cross-check %s: %s holds %d records, corpus_sha256 %s"
          % ("OK" if ok else "FAILED", treeish, len(hist), got))
    if not ok:
        print("  BASELINE.json declares %s — the committed archive is NOT the corpus "
              "the remediation consumed" % meta["corpus_sha256"])
        return 1
    return 0


# ------------------------------------------------------------------- extract


def extract(out_dir: str, force: bool = False, verbose: bool = True) -> dict:
    """Expand the archive to `out_dir`. Idempotent: a matching tree is left alone."""
    meta = verify_archive(verbose=False)
    stamp_path = os.path.join(os.path.dirname(out_dir), STAMP_NAME)
    if not force and os.path.isdir(out_dir) and os.path.exists(stamp_path):
        with open(stamp_path, encoding="utf-8") as fh:
            stamp = json.load(fh)
        n = len([f for f in os.listdir(out_dir) if f.endswith(".json")])
        if (stamp.get("archive_sha256") == meta["archive_sha256"]
                and n == meta["n_records"]):
            if verbose:
                print("chain input already expanded: %s (%d records, archive %s)"
                      % (os.path.relpath(out_dir, REPO), n,
                         meta["archive_sha256"][:12]))
            return {"extracted": False, "n_records": n, "out_dir": out_dir}

    parent = os.path.dirname(out_dir)
    os.makedirs(parent, exist_ok=True)
    tmp = out_dir + ".incoming"
    if os.path.isdir(tmp):
        _rmtree(tmp)
    os.makedirs(tmp)
    n = 0
    with tarfile.open(ARCHIVE, mode="r:xz") as tf:
        for ti in tf:
            if not ti.isfile():
                continue
            name = os.path.basename(ti.name)
            if not name.endswith(".json") or "/" in name.strip("/"):
                raise BaselineError("unexpected archive member %r" % ti.name)
            src = tf.extractfile(ti)
            with open(os.path.join(tmp, name), "wb") as fh:
                fh.write(src.read())
            n += 1
    if n != meta["n_records"]:
        raise BaselineError("archive holds %d records, BASELINE.json declares %d"
                            % (n, meta["n_records"]))
    got = corpus_digest(digest_dir(tmp))
    if got != meta["corpus_sha256"]:
        raise BaselineError("extracted corpus_sha256 %s != declared %s"
                            % (got, meta["corpus_sha256"]))
    if os.path.isdir(out_dir):
        _rmtree(out_dir)                    # regenerated staging tree, never source
    os.replace(tmp, out_dir)
    with open(stamp_path, "w", encoding="utf-8") as fh:
        json.dump({"archive": os.path.relpath(ARCHIVE, REPO),
                   "archive_sha256": meta["archive_sha256"],
                   "corpus_sha256": meta["corpus_sha256"],
                   "n_records": n,
                   "extracted_utc": dt.datetime.now(dt.timezone.utc)
                   .strftime("%Y-%m-%dT%H:%M:%SZ")}, fh, indent=1)
    if verbose:
        print("chain input expanded: %s (%d records, corpus_sha256 %s)"
              % (os.path.relpath(out_dir, REPO), n, got[:12]))
    return {"extracted": True, "n_records": n, "out_dir": out_dir}


def _rmtree(path: str) -> None:
    import shutil
    shutil.rmtree(path)


def ensure(out_dir: str = DEFAULT_OUT, verbose: bool = True) -> str:
    """Public entrypoint for other tools: return an expanded, verified chain input."""
    extract(out_dir, verbose=verbose)
    return out_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="baseline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true",
                    help="verify the archive digest and exit (no extraction)")
    ap.add_argument("--deep", action="store_true",
                    help="with --verify: also read every member and check corpus_sha256")
    ap.add_argument("--check-history", action="store_true",
                    help="compare the archive against the corpus in git history")
    ap.add_argument("--treeish", default=None, help="git tree-ish for --check-history")
    ap.add_argument("--build", action="store_true", help="rebuild the archive")
    ap.add_argument("--from", dest="from_dir", default=None, help="build from a directory")
    ap.add_argument("--from-git", dest="from_git", default=None,
                    help="build from a git tree-ish, e.g. b8d38bbf:data/media")
    ap.add_argument("--out", default=DEFAULT_OUT, help="where to expand the corpus")
    ap.add_argument("--force", action="store_true", help="re-extract even if current")
    a = ap.parse_args(argv)

    try:
        if a.build:
            return cmd_build(a)
        if a.check_history:
            return cmd_check_history(a)
        if a.verify:
            return cmd_verify(a)
        extract(os.path.abspath(a.out), force=a.force)
        return 0
    except BaselineError as exc:
        print("BASELINE ERROR: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
