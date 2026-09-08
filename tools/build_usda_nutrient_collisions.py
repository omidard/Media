#!/usr/bin/env python3
"""Both measurements, for every USDA nutrient pair that collides on one exchange.

THE DEFECT THIS EXISTS FOR
--------------------------
tools/build_usda_media_v2.py maps USDA nutrient names onto BiGG metabolites with
NMAP_RAW, and five BiGG ids are reachable from two distinct nutrient names each
(arachd, cys__L, lnlc, lnlnca, ocdcea). The per-nutrient loop then does

    comps[ex] = {...}

keyed on the exchange, so when a food reports both names the SECOND one
encountered overwrites the first. There is no detection, no accumulation and no
record of the loser.

2,025 collisions across 1,918 foods; 1,930 reach a shipped record, and 1,434 of
those disagree by more than 1%. The worst is usda_172353 / EX_ocdcea_e, where
"MUFA 18:1 c" reports 0.01 g and "MUFA 18:1" reports 0.178 g -- a factor of 17.8.
Replaying both source zips confirms the mechanism exactly: of the 1,930 shipped
values, 1,930 equal the LAST nutrient in the source array and 0 equal a discarded
one. The winner is the broad class on 962 of them and the cis subset on 968, so
the amount column is not comparable between USDA records.

The discarded measurement exists nowhere in the shipped data, and
data/api/components.parquet -- the route API.md documents for DuckDB -- carries no
note column at all, so a programmatic consumer gets the last-wins number with no
warning available.

WHAT THIS WRITES
----------------
`tools/usda_nutrient_collisions.json`: for every (medium id, exchange) that
collides, every measurement the source reports, with its nutrient name, amount and
unit, plus the choice this project makes and why.

WHY A COMMITTED ARTIFACT
------------------------
`data/_sources/**` is gitignored (the two zips are 6 MB and 211 MB), so a stage
that read them directly could not run in CI or from a fresh clone and would
quietly become a no-op there. Same pattern as tools/bigg_exchange_ids.json: a
small reviewed vocabulary, committed, rebuilt deliberately.

    python3 tools/build_usda_nutrient_collisions.py [--check]
"""
from __future__ import annotations

import collections
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
USDA = os.path.join(REPO, "data", "_sources", "usda")
OUT = os.path.join(HERE, "usda_nutrient_collisions.json")
SCHEMA = "mediadb-usda-nutrient-collisions/1"

sys.path.insert(0, HERE)

# The nutrient names that map onto one BiGG id, most specific first. This is a
# CURATION DECISION and it is written down rather than inferred, because the two
# names are not two measurements of one quantity: "MUFA 18:1" is total C18:1
# including trans, "MUFA 18:1 c" is the cis subset, and the BiGG target ocdcea IS
# cis-9-octadecenoate. Last-wins produced the broad-class total about half the
# time, which is the reverse of the defensible answer on those foods.
PREFERENCE = {
    "ocdcea": (["MUFA 18:1 c", "MUFA 18:1"],
               "ocdcea is cis-9-octadecenoate, so the cis measurement is the one "
               "that names the target; 'MUFA 18:1' is the total including trans"),
    "lnlc": (["PUFA 18:2 n-6 c,c", "PUFA 18:2 c"],
             "lnlc is linoleate, 18:2 n-6 cis,cis; the n-6 c,c figure names it and "
             "'PUFA 18:2 c' is the broader cis total"),
    "lnlnca": (["PUFA 18:3 n-3 c,c,c (ALA)", "PUFA 18:3 c"],
               "lnlnca is alpha-linolenate, 18:3 n-3; the ALA figure names it and "
               "'PUFA 18:3 c' is the broader cis total"),
    "arachd": (["PUFA 20:4c", "PUFA 20:4"],
               "arachd is arachidonate, all-cis; the cis figure names it"),
    "cys__L": (["Cystine", "Cysteine"],
               "no USDA food reports both (4,826 report Cystine, 24 report "
               "Cysteine, 0 report both), so this preference never fires. It is "
               "recorded so the pair is not silently resolved by array order if a "
               "future source does report both. Separately, Cystine is the "
               "disulfide dimer and cys__L is the monomer: that mis-target is a "
               "different defect, stated in the component's own mapping note"),
}

NAME_TO_BIGG = {}
for _bigg, (_names, _why) in PREFERENCE.items():
    for _n in _names:
        NAME_TO_BIGG[_n] = _bigg


def _foods():
    for zname, member in (("ff.zip", None), ("sr_legacy.zip", None)):
        path = os.path.join(USDA, zname)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with zipfile.ZipFile(path) as zf:
            name = member or zf.namelist()[0]
            with zf.open(name) as fh:
                blob = json.load(fh)
        for key in ("FoundationFoods", "SRLegacyFoods"):
            for food in blob.get(key, []) or []:
                yield food


def collect():
    """-> {medium_id: {exchange: {"measurements": [...], ...}}}"""
    out = {}
    for food in _foods():
        fdc = food.get("fdcId")
        if fdc is None:
            continue
        seen = collections.defaultdict(list)
        for x in food.get("foodNutrients", []) or []:
            amt = x.get("amount")
            if not amt or amt <= 0:
                continue
            nutrient = (x.get("nutrient") or {})
            name = nutrient.get("name")
            bigg = NAME_TO_BIGG.get(name)
            if not bigg:
                continue
            seen[bigg].append({"source_name": name, "value": amt,
                               "unit": nutrient.get("unitName", "")})
        for bigg, rows in seen.items():
            if len(rows) < 2:
                continue
            order, why = PREFERENCE[bigg]
            rows.sort(key=lambda r: order.index(r["source_name"]))
            out.setdefault("usda_%s" % fdc, {})["EX_%s_e" % bigg] = {
                "measurements": rows,
                "chosen": rows[0]["source_name"],
                "chose_by": "most_specific_nutrient_names_the_bigg_target",
                "why": why,
            }
    return out


def load():
    with open(OUT, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != SCHEMA:
        raise RuntimeError("%s carries schema %r, not %r" % (OUT, payload.get("schema"),
                                                             SCHEMA))
    return payload["collisions"]


def main(argv):
    check = "--check" in argv
    try:
        collisions = collect()
    except FileNotFoundError as e:
        print("USDA source zip not found: %s\n"
              "  fix: python3 tools/fetch_sources.py usda  (data/_sources is gitignored)"
              % e, file=sys.stderr)
        return 2
    n_pairs = sum(len(v) for v in collisions.values())
    if not n_pairs:
        print("refusing to write an empty collision table", file=sys.stderr)
        return 2
    payload = {
        "schema": SCHEMA,
        "doc": ("Every USDA nutrient measurement that a name-to-BiGG map collapsed "
                "onto one exchange, with the choice this project makes and why. "
                "Keyed by medium id, then exchange. Built from the USDA source zips "
                "by tools/build_usda_nutrient_collisions.py."),
        "source": "USDA FoodData Central foundation + SR Legacy JSON",
        "preference": {k: {"order": v[0], "why": v[1]} for k, v in PREFERENCE.items()},
        "n_foods_with_a_collision": len(collisions),
        "n_colliding_exchanges": n_pairs,
        "collisions": collisions,
    }
    if check:
        if not os.path.exists(OUT):
            print("%s is missing; run without --check" % OUT, file=sys.stderr)
            return 1
        if load() != collisions:
            print("%s is stale against the source zips" % OUT, file=sys.stderr)
            return 1
        print("usda_nutrient_collisions.json is current (%d foods, %d exchanges)"
              % (len(collisions), n_pairs))
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False)
        fh.write("\n")
    print("wrote %s (%d foods, %d colliding exchanges)" % (OUT, len(collisions), n_pairs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
