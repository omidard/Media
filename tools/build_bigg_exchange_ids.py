#!/usr/bin/env python3
"""Which EX_<met>_e reactions actually exist in BiGG.

THE DEFECT THIS EXISTS FOR
--------------------------
The browser payload partitioned components into "reaches a BiGG exchange",
"carries a non-BiGG fallback id" and "reaches none" by testing the STRING SHAPE of
the exchange id: anything not tagged `non_bigg_fallback` was counted as a real BiGG
reaction. An id can be shaped exactly like a BiGG exchange and name a reaction BiGG
does not have, and 12,228 components do:

    EX_choles_e       4,438   BiGG has choles_c only; the cholesterol exchange is EX_chsterol_e
    EX_behen_e        1,669   behen_c and behen_x only
    EX_hepedecacid_e  1,548
    EX_bcryptox_e       929
    EX_f_e              589   Fluoride: f_e exists, and no EX_f_e reaction does
    EX_lycop_e          429
    ... 305 distinct exchanges in all, across 13,515 media

so the hero sentence "664,000 of 665,582 components reach a BiGG exchange; 1,364
carry a fallback id no BiGG model will accept" understated the unusable set by 9x.
The documented adoption path (`model.medium = {c["exchange"]: ...}`) silently drops
every one of them, because the reaction is in no model.

AND THE DEFECT IN THE FIRST FIX
-------------------------------
The first correction tested the wrong thing: it asked whether the METABOLITE has an
`_e` form and let that stand in for whether the REACTION exists. That is a proxy
presented as the observation, and it is falsified by its own largest case. BiGG
metabolite `f` is Fluoride, with compartments c, e and p; the only reaction in the
dump touching `f_e` is Ftex (f_p <-> f_e), a transport. So `f_e` genuinely exists
and no `EX_f_e` does. Screening the 838 distinct ids the proxy called existing
against BiGG's own reaction dump, then confirming each candidate against the live
API, found 11 that are not BiGG reactions at all:

    EX_f_e 589, EX_gtocophe_e 187, EX_pb_e 39, EX_glc__aD_e 10, EX_psuri_e 7,
    EX_2hydog_e 5, EX_M02035_e 3, EX_meglyxyl_e 3, EX_26dmani_e 2,
    EX_selmeth_e 2, EX_C03958_e 1

= 848 components across 740 media, published as usable. 168 of those records
showed no caution at all, because every unusable id they carry was one of these.

WHAT THIS WRITES
----------------
`tools/bigg_exchange_ids.json`: the EXCHANGE REACTION IDS BiGG has, taken from
BiGG's reaction list rather than inferred from its metabolite list. The membership
test is then the question itself, with no premise in between.

Current ids and retired ones are UNIONED. 3,686 EX_ ids appear only in the
`old_bigg_ids` column, and they still resolve: EX_2ameph_e is absent from the
`bigg_id` column, returns HTTP 200 from the API, and is the current EX_AEP_e under
its old name. A current-ids-only screen would have condemned it and three other
components' worth of ids. Where an id resolves only as an old name, the current one
is published beside it in `renamed_exchanges` so a record can tell the reader the
modern name rather than silently accepting the retired one.

WHY A COMMITTED ARTIFACT RATHER THAN READING THE DUMP
-----------------------------------------------------
`data/_sources/**` is gitignored (large and licence-encumbered), so a builder that
read it directly could not run in CI or from a fresh clone, and the check would
quietly become a no-op there. This is the same pattern the repo already uses for
tools/bigg_metabolite_dict.json: a small reviewed vocabulary, committed, rebuilt
deliberately.

    python3 tools/build_bigg_exchange_ids.py [--check]
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DUMP = os.path.join(REPO, "data", "_sources", "bigg", "bigg_models_reactions.txt")
OUT = os.path.join(HERE, "bigg_exchange_ids.json")
SCHEMA = "mediadb-bigg-exchange-ids/2"


def exchange_reactions(dump_path: str):
    """Every EX_ reaction id BiGG serves, current or under a retired name.

    Returns (ids, renamed) where `renamed` maps a retired EX_ id to the current
    one that carries it, for the ids that are reachable only as old names.
    """
    ids = set()
    renamed = {}
    with open(dump_path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        i_id = header.index("bigg_id")
        i_old = header.index("old_bigg_ids")
        current = set()
        old = {}
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= i_id:
                continue
            bigg_id = parts[i_id]
            if bigg_id.startswith("EX_"):
                current.add(bigg_id)
            if len(parts) > i_old:
                for name in parts[i_old].split(";"):
                    name = name.strip()
                    if name.startswith("EX_"):
                        old.setdefault(name, bigg_id)
    ids = current | set(old)
    renamed = {k: v for k, v in old.items() if k not in current}
    return ids, renamed


def load() -> set[str]:
    """The committed set. Callers must not fall back to an empty set on failure:
    an absent vocabulary would silently reclassify every component as unusable."""
    with open(OUT, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != SCHEMA:
        raise RuntimeError(
            "%s carries schema %r, not %r. Version 1 held METABOLITE stems and "
            "answered a different question (does the metabolite have an _e form), "
            "which misclassified 848 components. Rebuild it: "
            "python3 tools/build_bigg_exchange_ids.py"
            % (OUT, payload.get("schema"), SCHEMA))
    return set(payload["exchange_reactions"])


def load_renamed() -> dict:
    with open(OUT, encoding="utf-8") as fh:
        return json.load(fh).get("renamed_exchanges") or {}


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
    warn about 1,364 unusable ids when the figure was 13,592.

    The test is membership of BiGG's own exchange-reaction list. It is not a test
    of the metabolite (that premise is false: f_e exists and EX_f_e does not), and
    it is not `in_biggr`, which was measured against this vocabulary and misses
    1,725 of these while falsely condemning 2,600 whose exchange does exist,
    because it records membership of the local BiGGr prokaryote reactome and that
    is a different question.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = load()
    ex = comp.get("exchange")
    if not ex:
        return "n_no_exchange"
    if comp.get("evidence_tier") == "non_bigg_fallback":
        return "n_nonbigg_fallback"
    if ex in _CACHE:
        return "n_bigg_exchange"
    return "n_bigg_shaped_no_such_exchange"


def main(argv):
    check = "--check" in argv
    if not os.path.exists(DUMP):
        print("BiGG reaction dump not found: %s\n"
              "  what: the exchange-reaction list this vocabulary IS\n"
              "  fix:  python3 tools/fetch_sources.py bigg  (data/_sources is gitignored)"
              % DUMP, file=sys.stderr)
        return 2
    ids, renamed = exchange_reactions(DUMP)
    if not ids:
        print("refusing to write an empty vocabulary from %s" % DUMP, file=sys.stderr)
        return 2
    payload = {
        "schema": SCHEMA,
        "doc": ("BiGG exchange REACTION ids, read from BiGG's reaction list. An "
                "exchange id outside this set is BiGG-shaped and names no BiGG "
                "reaction; the documented COBRApy adoption path drops it silently. "
                "Version 1 of this file held metabolite stems and asked whether the "
                "metabolite has an extracellular form, which is a proxy, not the "
                "question: f_e exists in BiGG and EX_f_e does not."),
        "source": "BiGG Models, bigg_models_reactions.txt",
        "n_exchange_reactions": len(ids),
        "n_reachable_only_as_a_retired_name": len(renamed),
        "exchange_reactions": sorted(ids),
        "renamed_exchanges": dict(sorted(renamed.items())),
    }
    if check:
        if not os.path.exists(OUT):
            print("%s is missing; run without --check" % OUT, file=sys.stderr)
            return 1
        try:
            current = load()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        if current != ids:
            print("%s is stale: %d ids on disk, %d in the dump"
                  % (OUT, len(current), len(ids)), file=sys.stderr)
            return 1
        print("bigg_exchange_ids.json is current (%d exchange reactions)" % len(ids))
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
        fh.write("\n")
    print("wrote %s (%d exchange reactions, %d reachable only as a retired name)"
          % (OUT, len(ids), len(renamed)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
