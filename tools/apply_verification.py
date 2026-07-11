#!/usr/bin/env python3
"""
Apply per-paper verification verdicts to the media files.

Input: a JSON array of verdicts (from the verify-media-formulations workflow), each
  {id, verdict, base_medium, oxygen, components:[{name,role,amount}], evidence,
   confidence, note}

Actions:
  confirmed  -> keep components; mark provenance.verification = "paper-verified (confirmed)".
  corrected  -> rebuild components from verdict.components (map names -> BiGG exchanges;
                unmapped -> uncovered), set oxygen, add mineral/O2 as needed, mark
                "paper-verified (corrected)".
  rejected /
  not_found  -> quarantine (remove file), log to data/_quarantine.json.

Usage:  python3 tools/apply_verification.py <verdicts.json> [--dry]
Then rerun: enrich_coverage.py, curate_oxygen.py, build_index.py, build_api_exports.py.
"""
import os, re, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")
sys.path.insert(0, HERE)
from map_metabolite import Mapper, norm            # noqa: E402
from enrich_coverage import recover, uncovered_entry, source_of  # noqa: E402

MAP = Mapper(); DICT = MAP.dict
MINERAL_BASE = ["pi", "so4", "nh4", "k", "na1", "cl", "mg2", "ca2", "fe2", "fe3",
                "mn2", "zn2", "cu2", "cobalt2", "h2o", "h"]
CARBON = {"glc__D","ac","glyc","fru","gal","succ","lac__L","malt","sucr","lcts","cit","etoh"}


def build_components(verdict):
    """Map the verdict's component names to BiGG exchanges; return (components, uncovered)."""
    comps = {}
    uncovered = []
    for c in verdict.get("components", []) or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        rec = recover(name, {})
        recs = rec if isinstance(rec, list) else ([rec] if rec else [])
        if recs:
            for comp in recs:
                bid = comp.get("bigg_metabolite")
                lb = -1000.0 if bid in ("pi","so4","nh4","k","na1","cl","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2","h2o","h") else (-10.0 if bid in CARBON else -1.0)
                comp["lower_bound"] = lb
                comp.setdefault("upper_bound", 1000.0)
                comps.setdefault(comp["exchange"], comp)
        else:
            uncovered.append(uncovered_entry(name, {}))
    return comps, uncovered


def apply(verdicts, dry=False):
    quarantine = []
    stats = {"confirmed": 0, "corrected": 0, "rejected": 0, "not_found": 0, "missing_file": 0, "skipped": 0}
    KNOWN = ("confirmed", "corrected", "rejected", "not_found")
    for v in verdicts:
        mid = v.get("id")
        if not mid:
            continue
        verdict = v.get("verdict")
        # "unavailable": paper cites an external reference for the full recipe, but often
        # DID verify the oxygen regime / carbon source. Apply only those paper-grounded
        # bits (never rebuild the component list) and keep the record flagged for review.
        if verdict == "unavailable":
            path = os.path.join(MEDIA, mid + ".json")
            if os.path.exists(path):
                d = json.load(open(path))
                ox = v.get("oxygen")
                if ox in ("aerobic", "anaerobic", "facultative"):
                    d["oxygen"] = ox
                    d["aerobic"] = (ox != "anaerobic")
                    if ox == "anaerobic":
                        d["components"] = [c for c in d.get("components", []) if c.get("exchange") != "EX_o2_e"]
                prov = d.setdefault("provenance", {})
                prov["verification"] = "auto-extracted; O2/carbon verified from paper, full recipe cited from an external reference (manual review)"
                if v.get("note"):
                    prov["verification_note"] = v["note"][:400]
                with open(path, "w") as fh:
                    json.dump(d, fh, ensure_ascii=False)
            stats["skipped"] += 1
            continue
        # any other unknown verdict -> leave untouched
        if verdict not in KNOWN:
            stats["skipped"] += 1
            continue
        path = os.path.join(MEDIA, mid + ".json")
        if not os.path.exists(path):
            stats["missing_file"] += 1
            continue
        d = json.load(open(path))
        prov = d.setdefault("provenance", {})
        if verdict in ("rejected", "not_found"):
            quarantine.append({"id": mid, "name": d.get("name"), "reason": "workflow:" + verdict,
                               "note": v.get("note", ""), "evidence": v.get("evidence", "")})
            stats[verdict] += 1
            if not dry:
                os.remove(path)
            continue
        # a paper verdict supersedes the earlier heuristic formulation_warning
        d.get("provenance", {}).pop("formulation_warning", None)
        # oxygen from verdict
        ox = v.get("oxygen")
        if ox in ("aerobic", "anaerobic", "facultative"):
            d["oxygen"] = ox
            d["aerobic"] = (ox != "anaerobic")
        if verdict == "corrected":
            comps, uncovered = build_components(v)
            if len(comps) >= 2:
                # add mineral base + O2 (unless anaerobic)
                for b in MINERAL_BASE:
                    ex = "EX_%s_e" % b
                    if ex not in comps and b in DICT:
                        r = DICT[b]
                        comps[ex] = {"name": r.get("name", b), "bigg_metabolite": b, "exchange": ex,
                                     "lower_bound": -1000.0, "upper_bound": 1000.0, "concentration_mM": None,
                                     "xref": r.get("xrefs", {}), "in_biggr": r.get("in_biggr", False),
                                     "exchange_source": "biggr" if r.get("in_biggr") else "bigg",
                                     "mapping_method": "mineral_base", "mapping_confidence": "convention"}
                if d.get("oxygen") != "anaerobic" and "EX_o2_e" not in comps and "o2" in DICT:
                    comps["EX_o2_e"] = {"name": "O2", "bigg_metabolite": "o2", "exchange": "EX_o2_e",
                                        "lower_bound": -10.0, "upper_bound": 1000.0, "concentration_mM": None,
                                        "xref": DICT["o2"].get("xrefs", {}), "in_biggr": DICT["o2"].get("in_biggr", False),
                                        "exchange_source": "biggr", "mapping_method": "mineral_base", "mapping_confidence": "convention"}
                d["components"] = sorted(comps.values(), key=lambda c: c["exchange"])
                d["uncovered"] = uncovered
                d["n_components"] = len(d["components"])
                d["n_mapped"] = len(d["components"])
                d["n_in_biggr"] = sum(1 for c in d["components"] if c.get("in_biggr"))
                stats["corrected"] += 1
            else:
                # correction produced too little -> treat as confirmed-with-warning, keep old
                prov["formulation_warning"] = "workflow correction sparse; kept original — " + (v.get("note", "") or "")
                stats["confirmed"] += 1
            prov["verification"] = "paper-verified (corrected via workflow)"
        else:  # confirmed
            prov["verification"] = "paper-verified (confirmed)"
            stats["confirmed"] += 1
        if v.get("evidence"):
            prov["verification_evidence"] = v["evidence"][:400]
        if v.get("confidence"):
            prov["verification_confidence"] = v["confidence"]
        if not dry:
            with open(path, "w") as fh:
                json.dump(d, fh, ensure_ascii=False)
    if not dry and quarantine:
        qpath = os.path.join(REPO, "data", "_quarantine.json")
        existing = json.load(open(qpath)) if os.path.exists(qpath) else []
        json.dump(existing + quarantine, open(qpath, "w"), indent=1)
    print("verification applied:", stats)
    print("quarantined:", len(quarantine))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    verdicts = json.load(open(args[0]))
    if isinstance(verdicts, dict):
        verdicts = verdicts.get("verdicts", [])
    apply(verdicts, dry=dry)


if __name__ == "__main__":
    main()
