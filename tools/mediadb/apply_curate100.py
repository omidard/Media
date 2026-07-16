#!/usr/bin/env python3
"""Apply the deep-recuration results (_curate/results/PMC*.json) to media records.

Each recovered compound name -> BiGG exchange via the shared MediaDB mapper
(salt dissociation + recover ladder). Concentrations from concentration_mM or a
parsed concentration string. Oxygen set from the agent verdict. Undefined complex
ingredients / named stocks -> uncovered[] (never fabricated; the enrich pass
decomposes yeast extract/peptone etc. downstream). Provenance records every chased
source + the compounds that were missing before.

Full component replacement only when >=3 compounds map; otherwise annotate-only so a
thin/failed extraction never wipes a record. status rejected/not_found -> flag for
review, never delete. Run with --apply to write; default is a dry run.
"""
import os, re, sys, json, glob, datetime
REPO = "/data/media_curate"
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools", "mediadb"))
import build_mediadb_media as B
RESULTS = os.path.join(REPO, "_curate", "results")
TODAY = datetime.date.today().isoformat()

def parse_mM(c):
    v = c.get("concentration_mM")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    s = str(c.get("concentration") or "")
    m = re.match(r"\s*~?([\d.]+)\s*(mmol/l|umol/l|nmol/l|mm|µm|um|μm|nm|m)\b", s, re.I)
    if m:
        val = float(m.group(1)); u = m.group(2).lower()
        if u in ("mm", "mmol/l"): return val
        if u in ("µm", "um", "μm", "umol/l"): return val / 1000.0
        if u in ("nm", "nmol/l"): return val / 1e6
        if u == "m": return val * 1000.0
    return None

STOCK_WORDS = re.compile(r"(vitamin solution|trace[- ]element|trace mineral|mineral solution|wolfe|wolin|balch|sl-?\d|se/?w|selenite-?tungstate|elixir|stock)", re.I)

def map_recipe(components):
    comps = {}; uncovered = []
    for c in components or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        clean = re.sub(r"\s*\(.*?\)\s*", " ", name).strip() or name  # drop "(in component A)"
        mM = parse_mM(c)
        got, unc = B.map_compound({"name": clean, "mM": mM, "bigg": None,
                                   "kegg": c.get("kegg"), "chebi": c.get("chebi")})
        for x in got:
            x["role"] = c.get("role", "")
            src = c.get("source")
            if src:
                x["evidence_source"] = src
            comps.setdefault(x["exchange"], x)
        if unc:
            unc["role"] = c.get("role", "")
            unc["recovered_name"] = name
            if c.get("concentration"): unc["stated_amount"] = c["concentration"]
            if c.get("source"): unc["source"] = c["source"]
            uncovered.append(unc)
    return comps, uncovered

def set_oxygen(d, comps, oxygen):
    oxygen = (oxygen or "facultative").strip().lower()
    if oxygen not in ("aerobic", "anaerobic", "facultative"):
        oxygen = "facultative"
    d["oxygen"] = oxygen
    d["aerobic"] = (oxygen == "aerobic")
    if oxygen == "anaerobic":
        comps.pop("EX_o2_e", None)
    else:
        comps.setdefault("EX_o2_e", {"name": "O2", "bigg_metabolite": "o2",
                                     "exchange": "EX_o2_e", "lower_bound": -10.0,
                                     "upper_bound": 1000.0, "concentration_mM": None,
                                     "mapping_method": "oxygen_regime", "mapping_confidence": "high",
                                     "role": "electron acceptor"})
    return oxygen

def main():
    apply = "--apply" in sys.argv
    files = sorted(glob.glob(os.path.join(RESULTS, "*.json")))
    print(f"result files: {len(files)}  ({'APPLY' if apply else 'dry-run'})")
    stats = {"media": 0, "full": 0, "annotate": 0, "review": 0, "missing_file": 0}
    added_total = 0; review_log = []
    for rf in files:
        try:
            R = json.load(open(rf))
        except Exception as e:
            print("  BAD json:", os.path.basename(rf), e); continue
        pmc = R.get("pmc", os.path.basename(rf).replace(".json", ""))
        for m in R.get("media", []):
            mid = m.get("id")
            if not mid:
                continue
            f = os.path.join(REPO, "data", "media", mid + ".json")
            if not os.path.exists(f):
                stats["missing_file"] += 1; continue
            stats["media"] += 1
            d = json.load(open(f))
            before = len(d.get("components") or [])
            p = d.setdefault("provenance", {})
            status = (m.get("status") or "").lower()
            conf = (m.get("confidence") or "medium").lower()
            recur = {"date": TODAY, "round": "complete-recipe (cited+supplementary chased)",
                     "status": status, "confidence": conf,
                     "sources_chased": m.get("sources_chased", []),
                     "missing_before": m.get("missing_before", []),
                     "corrections": m.get("corrections", []),
                     "notes": (m.get("notes") or "")[:600]}
            if status in ("rejected", "not_found"):
                p["recuration"] = recur
                p["verification"] = ("under review — paper does not define a chemically explicit medium"
                                     if status == "rejected" else "under review — source not found")
                stats["review"] += 1
                review_log.append({"id": mid, "pmc": pmc, "status": status, "notes": recur["notes"]})
                if apply:
                    json.dump(d, open(f, "w"), ensure_ascii=False)
                continue
            comps, uncovered = map_recipe(m.get("components"))
            oxygen = set_oxygen(d, comps, m.get("oxygen"))
            full = len(comps) >= 3
            if full:
                d["components"] = list(comps.values())
                d["uncovered"] = uncovered
                d["n_components"] = len(d["components"])
                d["defined"] = d.get("defined", False)
                p["verification"] = "paper-verified (complete recipe; cited + supplementary sources chased)"
                # best evidence quote
                ev = next((c.get("evidence") for c in (m.get("components") or []) if c.get("evidence")), "")
                if ev:
                    p["verification_evidence"] = ev[:500]
                if m.get("base_medium"): p["base_medium"] = m["base_medium"]
                if m.get("base_medium_reference"): p["base_medium_reference"] = m["base_medium_reference"]
                p["recuration"] = recur
                stats["full"] += 1
                added_total += max(0, len(comps) - before)
            else:
                p["recuration"] = recur
                p["verification"] = "recuration attempted — recipe not confidently re-mappable (see notes)"
                stats["annotate"] += 1
            if apply:
                json.dump(d, open(f, "w"), ensure_ascii=False)
    print("stats:", stats, "| net exchanges added (full):", added_total)
    json.dump(review_log, open(os.path.join(REPO, "_curate", "review_log.json"), "w"), indent=1)
    if review_log:
        print("flagged for review:", [r["id"] for r in review_log])

if __name__ == "__main__":
    main()
