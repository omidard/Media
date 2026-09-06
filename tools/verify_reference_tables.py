#!/usr/bin/env python3
"""
Prove that data/refs.json and data/media are in step, on the shipped state.

Stage 60 moved every repeated cross-reference block and every repeated note out
of the 13,515 per-medium records and into one table. That is only safe while the
two agree, and they are written by different steps at different times: the corpus
is promoted by `make promote`, the table travels with it. A corpus referring to a
key the table does not hold would render a blank cross-reference cell on the site
and a column of nulls in the parquet, with no error anywhere. This is the check
that turns that into a failure.

It asserts, over the whole corpus and not a sample:

  1. every components[].xref_id resolves in refs["xrefs"]
  2. every components[].mapping_note_id and xref_note_id resolves in refs["notes"]
  3. no table entry is unreferenced (an orphan means the table was built from a
     different corpus than the one on disk)
  4. no component still carries an inline `xref` / `target_xref` / `mapping_note`
     / `target_xref_note` — a half-migrated corpus is worse than either state
  5. the tables are non-trivial: an empty refs.json against a keyed corpus is the
     exact failure this exists to catch

  python3 tools/verify_reference_tables.py [--media DIR] [--refs PATH] [--quiet]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import refs as R                                       # noqa: E402

#: Taken from refs.py rather than restated here. A hardcoded copy is how this check
#: came to flag `amount_basis` — a field stage 60 deliberately does NOT remove — as
#: half-migrated residue, which would have blocked a correct corpus.
INLINE_FIELDS = tuple(R.XREF_FIELDS_REMOVED) + tuple(R.DERIVED_FROM_QUANTITY)


def verify(media_dir: str, refs_path: str) -> dict:
    tables = R.load_refs(refs_path)
    xrefs = tables.get("xrefs") or {}
    notes = tables.get("notes") or {}

    seen_x, seen_n = set(), set()
    n_comp = n_rec = 0
    missing_x, missing_n, inline = [], [], []

    for fn in sorted(os.listdir(media_dir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(media_dir, fn), encoding="utf-8") as fh:
            rec = json.load(fh)
        n_rec += 1
        for c in rec.get("components") or []:
            n_comp += 1
            xid = c.get("xref_id")
            if xid is not None:
                seen_x.add(xid)
                if xid not in xrefs and len(missing_x) < 20:
                    missing_x.append((rec.get("id"), c.get("name"), xid))
            for key in ("mapping_note_id", "xref_note_id"):
                nid = c.get(key)
                if nid is not None:
                    seen_n.add(nid)
                    if nid not in notes and len(missing_n) < 20:
                        missing_n.append((rec.get("id"), c.get("name"), key, nid))
            for f in INLINE_FIELDS:
                if f in c and len(inline) < 20:
                    inline.append((rec.get("id"), c.get("name"), f))

    orphan_x = sorted(set(xrefs) - seen_x)
    orphan_n = sorted(set(notes) - seen_n)

    return {
        "media_dir": os.path.relpath(media_dir, REPO),
        "refs": os.path.relpath(refs_path, REPO),
        "n_records": n_rec,
        "n_components": n_comp,
        "n_xref_keys": len(xrefs),
        "n_xref_keys_referenced": len(seen_x),
        "n_note_keys": len(notes),
        "n_note_keys_referenced": len(seen_n),
        "unresolved_xref_ids": missing_x,
        "unresolved_note_ids": missing_n,
        "orphan_xref_keys": orphan_x[:20],
        "n_orphan_xref_keys": len(orphan_x),
        "orphan_note_keys": orphan_n[:20],
        "n_orphan_note_keys": len(orphan_n),
        "components_still_inline": inline,
        "tables_non_trivial": bool(xrefs) and bool(notes),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--media", default=os.path.join(REPO, "data", "media"))
    ap.add_argument("--refs", default=os.path.join(REPO, "data", R.REFS_FILENAME))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    r = verify(os.path.abspath(a.media), os.path.abspath(a.refs))
    failures = []
    if r["unresolved_xref_ids"]:
        failures.append("%d component(s) carry an xref_id the table does not hold, "
                        "e.g. %s" % (len(r["unresolved_xref_ids"]),
                                     r["unresolved_xref_ids"][:3]))
    if r["unresolved_note_ids"]:
        failures.append("%d component(s) carry a note id the table does not hold, "
                        "e.g. %s" % (len(r["unresolved_note_ids"]),
                                     r["unresolved_note_ids"][:3]))
    if r["n_orphan_xref_keys"] or r["n_orphan_note_keys"]:
        failures.append("%d xref and %d note table entries are referenced by no "
                        "component: the table was built from a different corpus"
                        % (r["n_orphan_xref_keys"], r["n_orphan_note_keys"]))
    if r["components_still_inline"]:
        failures.append("%d component(s) still carry a field stage 60 removes, "
                        "e.g. %s — the corpus is half migrated"
                        % (len(r["components_still_inline"]),
                           r["components_still_inline"][:3]))
    if not r["tables_non_trivial"]:
        failures.append("data/refs.json holds no cross-references or no notes")

    if not a.quiet:
        print("refs verify: %d records, %d components" % (r["n_records"], r["n_components"]))
        print("  xref keys %d, all referenced: %s"
              % (r["n_xref_keys"], r["n_orphan_xref_keys"] == 0))
        print("  note keys %d, all referenced: %s"
              % (r["n_note_keys"], r["n_orphan_note_keys"] == 0))
    for f in failures:
        sys.stderr.write("FAIL refs: %s\n" % f)
    if failures:
        return 1
    if not a.quiet:
        print("  OK: every key resolves, no orphans, no inline residue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
