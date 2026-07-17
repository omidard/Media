#!/usr/bin/env python3
"""Apply the food-excellence curation results (_foodcurate/results/food_*.json).

Rebuild each food medium from the agent's GROWTH-RELEVANT composition: map every
compound name -> BiGG exchange (salt dissociation + recover ladder), carry the
concentration (mM), keep genuine phytochemicals / unmappable compounds in uncovered,
and DROP the flagged noise (trace heavy metals, predicted/implausible compounds) that
FooDB had padded in. Provenance records the sources chased, what was added, and what
was removed. Never fabricates. --apply to write.
"""
import os, re, sys, json, glob, datetime
REPO = "/data/media_curate"
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools", "mediadb"))
import build_mediadb_media as B
RESULTS = os.path.join(REPO, "_foodcurate", "results")
TODAY = datetime.date.today().isoformat()

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def parse_mM(c):
    v = c.get("concentration_mM")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    return None

def map_components(components):
    comps = {}; uncovered = []
    for c in components or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        clean = re.sub(r"\s*\(.*?\)\s*", " ", name).strip() or name
        mM = parse_mM(c)
        got, unc = B.map_compound({"name": clean, "mM": mM, "bigg": None,
                                   "kegg": c.get("kegg"), "chebi": c.get("chebi")})
        for x in got:
            x["role"] = c.get("role", "")
            if c.get("source"):
                x["evidence_source"] = c["source"]
            if c.get("amount") is not None and c.get("unit"):
                x["amount"] = f"{c['amount']} {c['unit']}"
            comps.setdefault(x["exchange"], x)
        if unc:
            unc["role"] = c.get("role", "")
            unc["recovered_name"] = name
            if c.get("amount") is not None and c.get("unit"):
                unc["amount"] = f"{c['amount']} {c['unit']}"
            if c.get("source"):
                unc["source"] = c["source"]
            uncovered.append(unc)
    return comps, uncovered

def main():
    apply = "--apply" in sys.argv
    files = sorted(glob.glob(os.path.join(RESULTS, "*.json")))
    print(f"result files: {len(files)}  ({'APPLY' if apply else 'dry-run'})")
    stats = {"media": 0, "rebuilt": 0, "skipped_thin": 0, "missing_file": 0}
    tot_removed = 0; tot_added = 0
    for rf in files:
        try:
            R = json.load(open(rf))
        except Exception as e:
            print("  BAD json:", os.path.basename(rf), e); continue
        mid = R.get("id")
        f = os.path.join(REPO, "data", "media", mid + ".json") if mid else None
        if not f or not os.path.exists(f):
            stats["missing_file"] += 1; continue
        stats["media"] += 1
        comps, uncovered = map_components(R.get("components"))
        if len(comps) < 5:                       # too thin -> don't wipe the existing record
            stats["skipped_thin"] += 1; continue
        # genuine phytochemicals the agent flagged to keep (unmappable) -> uncovered
        seen = {u.get("recovered_name", "").lower() for u in uncovered}
        for k in R.get("keep_uncovered", []) or []:
            kn = k if isinstance(k, str) else (k.get("name") if isinstance(k, dict) else "")
            if kn and kn.lower() not in seen:
                uncovered.append({"name": kn, "reason": "genuine phytochemical (no BiGG metabolite)",
                                  "curation": "no_bigg_exchange", "recovered_name": kn})
        d = json.load(open(f))
        before = len(d.get("components") or [])
        d["components"] = list(comps.values())
        d["uncovered"] = uncovered
        d["n_components"] = len(d["components"])
        if R.get("basis"):
            d["basis"] = R["basis"]
        p = d.setdefault("provenance", {})
        p["verification"] = "expert-curated (multi-source food composition; growth-relevant profile completed, FooDB noise removed)"
        p["curation_date"] = TODAY
        p["curation_sources"] = R.get("sources", [])
        p["curation_notes"] = (R.get("notes") or "")[:500]
        p["curation_added"] = R.get("missing_added", [])
        p["curation_removed"] = [{"name": (x.get("name") if isinstance(x, dict) else x),
                                  "reason": (x.get("reason", "") if isinstance(x, dict) else "")}
                                 for x in (R.get("remove") or [])]
        p["curation_confidence"] = R.get("confidence", "medium")
        stats["rebuilt"] += 1
        tot_removed += len(R.get("remove") or [])
        tot_added += max(0, len(comps) - before)
        if apply:
            json.dump(d, open(f, "w"), ensure_ascii=False)
    print("stats:", stats)
    print(f"noise compounds removed (agent-flagged): {tot_removed} | net exchanges added: {tot_added}")

if __name__ == "__main__":
    main()
