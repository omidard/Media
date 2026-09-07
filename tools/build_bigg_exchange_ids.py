#!/usr/bin/env python3
"""Which EX_<met>_e reactions actually exist in BiGG.

THE DEFECT THIS EXISTS FOR
--------------------------
The browser payload partitioned components into "reaches a BiGG exchange",
"carries a non-BiGG fallback id" and "reaches none" by testing the STRING SHAPE of
the exchange id: anything not tagged `non_bigg_fallback` was counted as a real BiGG
reaction. An id can be shaped exactly like a BiGG exchange and name a reaction BiGG
does not have, and 11,380 components did:

    EX_choles_e       4,438   BiGG has choles_c only; the cholesterol exchange is EX_chsterol_e
    EX_behen_e        1,669   behen_c and behen_x only
    EX_hepedecacid_e  1,548
    EX_bcryptox_e       929
    EX_lycop_e          429
    ... 294 distinct exchanges in all, across 5,942 of 13,515 media

so the hero sentence "664,000 of 665,582 components reach a BiGG exchange; 1,364
carry a fallback id no BiGG model will accept" understated the unusable set by 8.3x.
The documented adoption path (`model.medium = {c["exchange"]: ...}`) silently drops
every one of them, because the reaction is in no model.

WHAT THIS WRITES
----------------
`tools/bigg_exchange_ids.json`: the universal metabolite ids that HAVE an
extracellular form in BiGG, so `EX_<id>_e` is a reaction that can exist. Derived
from the same BiGG namespace dump as tools/bigg_metabolite_dict.json.

WHY A COMMITTED ARTIFACT RATHER THAN READING THE DUMP
-----------------------------------------------------
`data/_sources/**` is gitignored (large and licence-encumbered), so a builder that
read it directly could not run in CI or from a fresh clone, and the check would
quietly become a no-op there. This is the same pattern the repo already uses for
tools/bigg_metabolite_dict.json: a small reviewed vocabulary, committed, rebuilt
deliberately.

VALIDATION OF THE PREMISE
-------------------------
"No <met>_e metabolite in BiGG implies no EX_<met>_e reaction" was checked against
the live BiGG API rather than assumed: 25 of 25 sampled ids with no _e form return
404 for their exchange reaction, and 30 of 30 sampled ids with one return 200.
EX_choles_e is 404 while EX_chsterol_e is 200.

    python3 tools/build_bigg_exchange_ids.py [--check]
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DUMP = os.path.join(REPO, "data", "_sources", "bigg", "bigg_models_metabolites.txt")
OUT = os.path.join(HERE, "bigg_exchange_ids.json")


def extracellular_ids(dump_path: str) -> set[str]:
    """Universal ids carrying an `_e` compartment form in the BiGG namespace."""
    ids = set()
    with open(dump_path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        col = header.index("bigg_id")
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= col:
                continue
            bigg_id = parts[col]
            if bigg_id.endswith("_e"):
                ids.add(bigg_id[:-2])
    return ids


def load() -> set[str]:
    """The committed set. Callers must not fall back to an empty set on failure:
    an absent vocabulary would silently reclassify every component as unusable."""
    with open(OUT, encoding="utf-8") as fh:
        return set(json.load(fh)["extracellular_metabolites"])


_CACHE = None

# The four states, in the order they are published. Named here rather than in each
# builder, because three separate builders computed this partition and any two of
# them could have drifted.
STATES = ("n_bigg_exchange", "n_bigg_shaped_no_such_exchange",
          "n_nonbigg_fallback", "n_no_exchange")


def exchange_state(comp) -> str:
    """Which of the FOUR states one component's exchange id is in.

    Four, not three. An id can be shaped exactly like a BiGG exchange and name no
    BiGG reaction; the documented adoption path drops those silently because the
    reaction is in no model, and counting them as successes is what let the site
    warn about 1,364 unusable ids when the figure was 12,744.

    `in_biggr` is NOT the test, and this was measured rather than assumed: it
    misses 1,103 of the 11,380 and would falsely condemn 2,826 components whose
    exchange does exist, because it records membership of the local BiGGr
    prokaryote reactome, which is a different question.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = load()
    ex = comp.get("exchange")
    if not ex:
        return "n_no_exchange"
    if comp.get("evidence_tier") == "non_bigg_fallback":
        return "n_nonbigg_fallback"
    met = ex[3:-2] if ex.startswith("EX_") and ex.endswith("_e") else None
    if met is not None and met in _CACHE:
        return "n_bigg_exchange"
    return "n_bigg_shaped_no_such_exchange"


def main(argv):
    check = "--check" in argv
    if not os.path.exists(DUMP):
        print("BiGG namespace dump not found: %s\n"
              "  what: the metabolite list this vocabulary is derived from\n"
              "  fix:  python3 tools/fetch_sources.py  (data/_sources is gitignored)"
              % DUMP, file=sys.stderr)
        return 2
    ids = extracellular_ids(DUMP)
    if not ids:
        print("refusing to write an empty vocabulary from %s" % DUMP, file=sys.stderr)
        return 2
    payload = {
        "schema": "mediadb-bigg-exchange-ids/1",
        "doc": ("Universal BiGG metabolite ids that have an extracellular (_e) form, "
                "so EX_<id>_e is a reaction BiGG can have. Derived from the BiGG "
                "namespace dump by tools/build_bigg_exchange_ids.py. An exchange id "
                "outside this set is BiGG-shaped and names no BiGG reaction; the "
                "documented COBRApy adoption path drops it silently."),
        "source": "BiGG Models, bigg_models_metabolites.txt",
        "n_extracellular_metabolites": len(ids),
        "extracellular_metabolites": sorted(ids),
    }
    if check:
        if not os.path.exists(OUT):
            print("%s is missing; run without --check" % OUT, file=sys.stderr)
            return 1
        current = load()
        if current != ids:
            print("%s is stale: %d ids on disk, %d in the dump"
                  % (OUT, len(current), len(ids)), file=sys.stderr)
            return 1
        print("bigg_exchange_ids.json is current (%d metabolites)" % len(ids))
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
        fh.write("\n")
    print("wrote %s (%d extracellular metabolites)" % (OUT, len(ids)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
