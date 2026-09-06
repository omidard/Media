#!/usr/bin/env python3
"""
Universal corpus invariants, checked by run_stages.py after EVERY stage.

Each invariant declares `enforced_from`: the stage id after which it must hold.
Some invariants are violated by the frozen snapshot itself (that is why the audit
found them), so they only become enforceable once the stage that fixes them has
run. `enforced_from: null` means "always, including on the frozen input".

The pass is a single sweep over the output corpus producing a `summary` dict; the
checks then compare that summary against the previous stage's summary and against
the stage's declared allowances (may_change_record_count, adds_keys, ...). This
keeps the cost at one read per record per stage.
"""
from __future__ import annotations

import json
import os

from stagelib import corpus_ids, read_record  # noqa: E402

# Top-level keys every record must carry. Measured present on 13,515/13,515 in the
# frozen snapshot, so this is an observed floor, not an aspiration.
REQUIRED_TOP_KEYS = ("id", "name", "category", "components", "provenance",
                     "n_components", "n_mapped", "n_in_biggr")

# Category enum. `growth_medium` is a second-generation duplicate of `laboratory`
# (finding SCHEMA-06) and is normalized away by 10_normalize_schema, so it is
# accepted on input and rejected from that stage onwards.
CATEGORY_ENUM = ("laboratory", "food", "biospecimen")
CATEGORY_ENUM_LEGACY = CATEGORY_ENUM + ("growth_medium",)

# Fields where an empty string is a documented defect (absent must be null).
NULLABLE_STRING_FIELDS = ("food_group", "organism_scope", "oxygen_note", "defined",
                          "base_medium", "name_original")


def summarize(corpus_dir: str, limit: int | None = None) -> dict:
    """One pass over a corpus directory, producing everything the checks need."""
    ids = corpus_ids(corpus_dir, limit)
    s = {
        "dir": corpus_dir,
        "n_records": len(ids),
        "ids": ids,
        "key_universe": {},                 # top-level key -> count of records carrying it
        "component_key_universe": {},
        "empty_string": {},                 # key -> count of records with "" in it
        "n_components_total": 0,
        "id_filename_mismatch": [],
        "exchange_identity_bad": [],        # (id, bigg, exchange)
        "n_components_mismatch": [],        # (id, declared, actual)
        "n_mapped_mismatch": [],            # (id, declared, actual_with_bigg)
        "n_in_biggr_mismatch": [],          # (id, declared, actual_true)
        "version_non_string": [],
        "category_values": {},
        "components_with_bigg": 0,
        "json_errors": [],
    }
    for mid in ids:
        fp = os.path.join(corpus_dir, mid + ".json")
        try:
            rec = read_record(fp)
        except Exception as exc:                       # noqa: BLE001 - collected, then reported
            s["json_errors"].append("%s: %s" % (mid, exc))
            continue
        if rec.get("id") != mid:
            s["id_filename_mismatch"].append((mid, rec.get("id")))
        for k, v in rec.items():
            s["key_universe"][k] = s["key_universe"].get(k, 0) + 1
            if v == "":
                s["empty_string"][k] = s["empty_string"].get(k, 0) + 1
        s["category_values"][rec.get("category")] = \
            s["category_values"].get(rec.get("category"), 0) + 1
        if not isinstance(rec.get("version"), str) and "version" in rec:
            s["version_non_string"].append((mid, type(rec.get("version")).__name__))
        comps = rec.get("components") or []
        s["n_components_total"] += len(comps)
        n_bigg = 0
        n_inb = 0
        for c in comps:
            for k in c:
                s["component_key_universe"][k] = s["component_key_universe"].get(k, 0) + 1
            b = c.get("bigg_metabolite")
            if b:
                n_bigg += 1
                if c.get("exchange") != "EX_%s_e" % b:
                    if len(s["exchange_identity_bad"]) < 20:
                        s["exchange_identity_bad"].append((mid, b, c.get("exchange")))
            if c.get("in_biggr") is True:
                n_inb += 1
        s["components_with_bigg"] += n_bigg
        if rec.get("n_components") != len(comps):
            s["n_components_mismatch"].append((mid, rec.get("n_components"), len(comps)))
        if rec.get("n_mapped") != n_bigg:
            s["n_mapped_mismatch"].append((mid, rec.get("n_mapped"), n_bigg))
        if rec.get("n_in_biggr") != n_inb:
            s["n_in_biggr_mismatch"].append((mid, rec.get("n_in_biggr"), n_inb))
    return s


# --------------------------------------------------------------------- checks
# Each check: fn(prev, cur, entry) -> (passed, observed, expected, note)
# `prev` may be None (first stage of a run compares against the frozen input).


def _u1_record_count(prev, cur, entry):
    if prev is None or entry.get("may_change_record_count"):
        return True, cur["n_records"], "declared-variable", ""
    return (cur["n_records"] == prev["n_records"], cur["n_records"], prev["n_records"],
            "a stage that adds or drops media must declare may_change_record_count")


def _u2_id_set(prev, cur, entry):
    if cur["id_filename_mismatch"]:
        return False, cur["id_filename_mismatch"][:5], "id == filename stem", ""
    if prev is None or entry.get("may_change_id_set"):
        return True, len(cur["ids"]), "declared-variable", ""
    added = set(cur["ids"]) - set(prev["ids"])
    dropped = set(prev["ids"]) - set(cur["ids"])
    return (not added and not dropped,
            {"added": sorted(added)[:5], "dropped": sorted(dropped)[:5]},
            "id set unchanged", "")


def _u3_required_keys(prev, cur, entry):
    missing = {k: cur["n_records"] - cur["key_universe"].get(k, 0)
               for k in REQUIRED_TOP_KEYS
               if cur["key_universe"].get(k, 0) != cur["n_records"]}
    if cur["json_errors"]:
        return False, cur["json_errors"][:5], "all records parse", ""
    return not missing, missing, {}, "required top-level keys present on every record"


def _u4_exchange_identity(prev, cur, entry):
    return (not cur["exchange_identity_bad"], cur["exchange_identity_bad"][:5],
            "EX_<bigg_metabolite>_e",
            "held in 664,218/664,218 components in the frozen snapshot; a stage that "
            "rewrites a metabolite id must rewrite its exchange in the same operation")


def _u5_n_components(prev, cur, entry):
    return (not cur["n_components_mismatch"], cur["n_components_mismatch"][:5], [], "")


def _u6_no_new_empty_strings(prev, cur, entry):
    if prev is None:
        return True, cur["empty_string"], "baseline", ""
    worse = {k: (prev["empty_string"].get(k, 0), v) for k, v in cur["empty_string"].items()
             if v > prev["empty_string"].get(k, 0)}
    return not worse, worse, {}, "absent is null, never an empty string"


def _u7_key_universe(prev, cur, entry):
    if prev is None:
        return True, len(cur["key_universe"]), "baseline", ""
    added = set(cur["key_universe"]) - set(prev["key_universe"])
    removed = set(prev["key_universe"]) - set(cur["key_universe"])
    declared_add = {k.split(".")[0] for k in entry.get("adds_keys", [])}
    declared_rm = {k.split(".")[0] for k in entry.get("removes_keys", [])}
    undeclared_add = added - declared_add
    undeclared_rm = removed - declared_rm
    return (not undeclared_add and not undeclared_rm,
            {"undeclared_added": sorted(undeclared_add),
             "undeclared_removed": sorted(undeclared_rm)},
            {}, "declare every key you add or remove in stages.json")


def _u8_n_mapped(prev, cur, entry):
    return (not cur["n_mapped_mismatch"], len(cur["n_mapped_mismatch"]), 0,
            "n_mapped must count components with a non-null bigg_metabolite, not all "
            "components (SCHEMA-01)")


def _u9_n_in_biggr(prev, cur, entry):
    return (not cur["n_in_biggr_mismatch"], len(cur["n_in_biggr_mismatch"]), 0, "")


def _u10_version_string(prev, cur, entry):
    return (not cur["version_non_string"], cur["version_non_string"][:5], [], "")


def _u11_category_enum(prev, cur, entry):
    bad = {k: v for k, v in cur["category_values"].items() if k not in CATEGORY_ENUM}
    return bad == {}, bad, {}, "category enum: %s" % (CATEGORY_ENUM,)


INVARIANTS = [
    {"id": "U1", "name": "record_count_stable", "enforced_from": None, "fn": _u1_record_count},
    {"id": "U2", "name": "id_set_stable_and_matches_filename", "enforced_from": None, "fn": _u2_id_set},
    {"id": "U3", "name": "required_top_keys_present", "enforced_from": None, "fn": _u3_required_keys},
    {"id": "U4", "name": "exchange_equals_EX_met_e", "enforced_from": None, "fn": _u4_exchange_identity},
    {"id": "U5", "name": "n_components_equals_len_components", "enforced_from": None, "fn": _u5_n_components},
    {"id": "U6", "name": "no_new_empty_strings", "enforced_from": None, "fn": _u6_no_new_empty_strings},
    {"id": "U7", "name": "key_universe_changes_declared", "enforced_from": None, "fn": _u7_key_universe},
    {"id": "U8", "name": "n_mapped_counts_bigg_mapped", "enforced_from": "10_normalize_schema", "fn": _u8_n_mapped},
    {"id": "U9", "name": "n_in_biggr_counts_in_biggr", "enforced_from": None, "fn": _u9_n_in_biggr},
    {"id": "U10", "name": "version_is_string", "enforced_from": "10_normalize_schema", "fn": _u10_version_string},
    {"id": "U11", "name": "category_in_enum", "enforced_from": "10_normalize_schema", "fn": _u11_category_enum},
]


def check_all(prev, cur, entry, stages_run_so_far) -> list[dict]:
    """Run every invariant that is enforceable at this point in the chain."""
    out = []
    for inv in INVARIANTS:
        ef = inv["enforced_from"]
        enforced = ef is None or ef in stages_run_so_far
        if not enforced:
            out.append({"id": inv["id"], "name": inv["name"], "enforced": False,
                        "passed": None, "note": "not enforced until %s has run" % ef})
            continue
        passed, observed, expected, note = inv["fn"](prev, cur, entry)
        out.append({"id": inv["id"], "name": inv["name"], "enforced": True,
                    "passed": bool(passed), "observed": observed,
                    "expected": expected, "note": note})
    return out


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "media")
    s = summarize(d)
    s.pop("ids")
    print(json.dumps(s, indent=1)[:4000])
