#!/usr/bin/env python3
"""
Coverage enrichment for the Media repo (idempotent, re-runnable).

For every medium this:
  1. Tags each mapped component with `exchange_source`
     (biggr | bigg | modelseed | kegg | metanetx) — where its exchange id came from.
  2. Tries to RECOVER previously-unmapped components:
       name -> BiGG (Mapper: index, ion/water aliases, deformula, acid heuristic)
       -> salt dissociation (NaHCO3 -> na1 + hco3, ...)
       -> ModelSEED / KEGG / MetaNetX fallback via MetaNetX (only when an xref exists)
     Recovered components move into components[] with their source recorded.
  3. Rebuilds a structured `uncovered[]`: the components we still cannot give an
     exchange, each with a reason, a curation flag, any external ids we have, and
     (for plausible nutrients) a proposed flux to be curated manually.
  4. Writes a per-medium `coverage` block {n_compounds, n_covered, n_uncovered,
     pct_covered, by_source{...}}.

The legacy `unmapped[]` list is consumed and replaced by `uncovered[]`. Re-running
is safe: recovered items are already in components[], so they are not re-processed.

Rebuild:  python3 tools/enrich_coverage.py [--limit N] [--dry]
"""
import os
import re
import sys
import glob
import json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")
sys.path.insert(0, HERE)
from map_metabolite import Mapper, norm  # noqa: E402
from complex_ingredients import decompose  # noqa: E402

MAP = Mapper()
DICT = MAP.dict


def valid(bid):
    return bid in DICT


# --- salt dissociation: name -> list of BiGG ids (filtered to existing) ---
_SALTS_RAW = {
    "sodiumbicarbonate": ["na1", "hco3"], "nahco3": ["na1", "hco3"],
    "sodiumhydroxide": ["na1", "oh1"], "naoh": ["na1", "oh1"],
    "potassiumhydroxide": ["k", "oh1"], "koh": ["k", "oh1"],
    "sodiumbromide": ["na1", "br"], "nabr": ["na1", "br"],
    "potassiumbromide": ["k", "br"], "kbr": ["k", "br"],
    "sodiumchloride": ["na1", "cl"], "nacl": ["na1", "cl"],
    "potassiumchloride": ["k", "cl"], "kcl": ["k", "cl"],
    "calciumcarbonate": ["ca2", "co3"], "caco3": ["ca2", "co3"],
    "sodiumcarbonate": ["na1", "co3"], "na2co3": ["na1", "co3"],
    "sodiumsulfate": ["na1", "so4"], "na2so4": ["na1", "so4"],
    "magnesiumsulfate": ["mg2", "so4"], "mgso4": ["mg2", "so4"],
    "sodiumnitrate": ["na1", "no3"], "nano3": ["na1", "no3"],
    "sodiumselenite": ["na1", "slnt"], "na2seo3": ["na1", "slnt"],
    "sodiumthiosulfate": ["na1", "tsul"], "na2s2o3": ["na1", "tsul"],
    "sodiumfluoride": ["na1", "fluor"], "naf": ["na1", "fluor"],
}
SALTS = {k: [b for b in v if valid(b)] for k, v in _SALTS_RAW.items()}
SALTS = {k: v for k, v in SALTS.items() if v}

# --- reason classification for still-uncovered components ---
_UNDEFINED = re.compile(
    r"extract|hydrolysate|peptone|tryptone|trypticase|casamino|casein|pancreatic|"
    r"agar|gelatin|broth|infusion|digest|bactopeptone|proteose|lab-?lemco", re.I)
_NONNUTRIENT = re.compile(
    r"resazurin|edta|nitrilotriacetic|nta\b|tris\b|hepes|mops\b|pipes|bicine|"
    r"phenol\s*red|bromothymol|indicator|\bdye\b|antifoam|tween|agarose|"
    r"cycloheximide|antibiotic|penicillin|streptomycin|kanamycin|ampicillin|vancomycin", re.I)
_INORGANIC = re.compile(r"h3bo3|boric|borate|selen|tungst|wo4|vanad|silic", re.I)


def classify(name):
    n = name or ""
    if _UNDEFINED.search(n):
        return "undefined_complex", "no_defined_exchange"
    if _NONNUTRIENT.search(n):
        return "non_nutrient", "no_exchange"
    if _INORGANIC.search(n):
        return "not_in_bigg", "needs_manual_curation"
    return "unmatched", "needs_manual_curation"


def source_of(comp):
    """Where a mapped component's exchange id comes from."""
    if comp.get("exchange_source"):
        return comp["exchange_source"]
    ex = comp.get("exchange", "") or ""
    if comp.get("in_biggr"):
        return "biggr"
    if re.match(r"^EX_cpd\d+_e$", ex):
        return "modelseed"
    if ex.endswith("_kegg_e"):
        return "kegg"
    ns = comp.get("namespace")
    if ns in ("modelseed", "kegg", "metanetx"):
        return ns
    return "bigg"


def new_component(hit, name, method):
    """Build a component dict from a Mapper BiGG hit."""
    bid = hit["bigg_metabolite"]
    rec = DICT.get(bid, {})
    src = "biggr" if rec.get("in_biggr") else "bigg"
    return {
        "name": name or hit.get("name", bid),
        "bigg_metabolite": bid,
        "exchange": hit["exchange"],
        "lower_bound": -1.0, "upper_bound": 1000.0, "concentration_mM": None,
        "xref": rec.get("xrefs", {}), "in_biggr": rec.get("in_biggr", False),
        "exchange_source": src,
        "mapping_method": method, "mapping_confidence": hit.get("mapping_confidence", "inferred"),
    }


def fallback_component(fb, name):
    """Build a component from a ModelSEED/KEGG/MetaNetX fallback exchange."""
    return {
        "name": name, "bigg_metabolite": None, "exchange": fb["exchange"],
        "lower_bound": -1.0, "upper_bound": 1000.0, "concentration_mM": None,
        "xref": {"mnx": fb.get("mnx"), "ref_id": fb.get("ref_id")},
        "in_biggr": False, "exchange_source": fb["namespace"],
        "mapping_method": fb["mapping_method"], "mapping_confidence": fb["mapping_confidence"],
    }


def _name_variants(name):
    """Candidate strings to try for a component name.
    'HCO3- (bicarbonate)' -> ['HCO3- (bicarbonate)', 'HCO3-', 'bicarbonate'];
    'glucose/fructose' -> [..., 'glucose', 'fructose']."""
    name = name or ""
    out, seen = [], set()
    def add(s):
        s = (s or "").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower()); out.append(s)
    add(name)
    add(re.sub(r"\s*\([^)]*\)", "", name))          # drop parenthetical qualifier
    m = re.findall(r"\(([^)]*)\)", name)              # the parenthetical content itself
    for x in m:
        add(x)
    base = re.sub(r"\s*\([^)]*\)", "", name)
    for tok in re.split(r"\s*[/,;]\s*|\s+or\s+", base):  # split combined names
        add(tok)
    return out


def decomposition_components(name):
    """If name is a complex ingredient, expand it into labelled approximate constituents."""
    d = decompose(name, valid=valid)
    if not d:
        return None
    key, ids = d
    out = []
    for b in ids:
        rec = DICT.get(b, {})
        out.append({
            "name": rec.get("name", b), "bigg_metabolite": b, "exchange": "EX_%s_e" % b,
            "lower_bound": -1.0, "upper_bound": 1000.0, "concentration_mM": None,
            "xref": rec.get("xrefs", {}), "in_biggr": rec.get("in_biggr", False),
            "exchange_source": ("biggr" if rec.get("in_biggr") else "bigg"),
            "mapping_method": "complex_decomposition", "mapping_confidence": "approximation",
            "derived_from": name,
        })
    return out


def recover(name, xref):
    """Try to give a still-unmapped component an exchange. Returns a component dict or None."""
    xk = {k: xref.get(k) for k in ("inchikey", "chebi", "kegg", "hmdb") if xref.get(k)}
    # 1) BiGG via name variants (index, ion/water aliases, deformula, acid heuristic)
    for cand in _name_variants(name):
        hit = MAP.map(name=cand, **xk)
        if hit:
            return new_component(hit, name, (hit["mapping_method"] + "_remap"))
        xk = {}  # xrefs only apply to the primary name
    # 1b) complex ingredient (yeast extract, tryptone, ...) -> decompose into constituents
    dc = decomposition_components(name)
    if dc:
        return dc
    # 2) salt dissociation -> possibly several ions; return the list marker
    n = norm(re.sub(r"\s*\([^)]*\)", "", name))
    if n in SALTS:
        return [new_component({"bigg_metabolite": b, "exchange": f"EX_{b}_e",
                               "in_biggr": DICT.get(b, {}).get("in_biggr", False),
                               "mapping_confidence": "inferred"}, name, "salt_dissociation_remap")
                for b in SALTS[n]]
    # 3) ModelSEED / KEGG / MetaNetX fallback (only possible when an xref exists)
    fb = MAP.fallback_exchange(chebi=xref.get("chebi"), kegg=xref.get("kegg"), name=name)
    if fb:
        return fallback_component(fb, name)
    return None


def uncovered_entry(name, xref):
    reason, curation = classify(name)
    e = {"name": name, "reason": reason, "curation": curation, "xref": {k: v for k, v in (xref or {}).items() if v}}
    if curation == "needs_manual_curation":
        e["proposed_lower_bound"] = -1.0
        e["note"] = "no exchange auto-assigned; propose uptake -1.0 pending manual curation"
    elif curation == "no_defined_exchange":
        e["note"] = "undefined/complex ingredient; represented elsewhere as an in-silico approximation, no single exchange"
    else:
        e["note"] = "not a metabolite exchange (buffer/indicator/chelator/antibiotic)"
    return e


def enrich(med):
    comps = med.get("components", []) or []
    for c in comps:
        c["exchange_source"] = source_of(c)
    seen_ex = {c.get("exchange") for c in comps}

    uncovered = []
    # read BOTH the legacy unmapped[] and any prior uncovered[] so re-runs are
    # idempotent (and can recover more if the mapper has since improved).
    legacy = (med.get("unmapped") or []) + (med.get("uncovered") or [])
    for u in legacy:
        name = (u.get("name") if isinstance(u, dict) else str(u)) or ""
        if not name.strip():
            continue
        xref = (u.get("xref") if isinstance(u, dict) else None) or {}
        rec = recover(name, xref)
        recs = rec if isinstance(rec, list) else ([rec] if rec else [])
        added = False
        for comp in recs:
            if comp["exchange"] not in seen_ex:
                comps.append(comp); seen_ex.add(comp["exchange"]); added = True
        if not added and not recs:
            uncovered.append(uncovered_entry(name, xref))

    by_source = {}
    for c in comps:
        s = c.get("exchange_source", "bigg")
        by_source[s] = by_source.get(s, 0) + 1
    n_cov, n_unc = len(comps), len(uncovered)
    total = n_cov + n_unc
    med["components"] = comps
    med["uncovered"] = uncovered
    med.pop("unmapped", None)
    med["n_components"] = n_cov
    med["n_mapped"] = n_cov
    med["n_in_biggr"] = sum(1 for c in comps if c.get("in_biggr"))
    med["coverage"] = {
        "n_compounds": total, "n_covered": n_cov, "n_uncovered": n_unc,
        "pct_covered": round(100.0 * n_cov / total, 1) if total else 100.0,
        "by_source": by_source,
    }
    return med


def main():
    dry = "--dry" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    files = sorted(glob.glob(os.path.join(MEDIA, "*.json")))
    if limit:
        files = files[:limit]
    tot_recovered = 0
    tot_uncovered = 0
    src_tally = {}
    cov_index = {}
    for f in files:
        med = json.load(open(f))
        before_comps = len(med.get("components", []) or [])
        before_unc = len(med.get("unmapped", []) or []) + len(med.get("uncovered", []) or [])
        enrich(med)
        recovered = len(med["components"]) - before_comps
        tot_recovered += max(0, recovered)
        tot_uncovered += med["coverage"]["n_uncovered"]
        for s, n in med["coverage"]["by_source"].items():
            src_tally[s] = src_tally.get(s, 0) + n
        cov_index[med["id"]] = {
            "category": med.get("category"),
            **{k: med["coverage"][k] for k in ("n_compounds", "n_covered", "n_uncovered", "pct_covered")},
            "by_source": med["coverage"]["by_source"],
        }
        if not dry:
            with open(f, "w") as fh:
                json.dump(med, fh, ensure_ascii=False)

    if not dry and not limit:
        with open(os.path.join(REPO, "data", "coverage.json"), "w") as fh:
            json.dump({"media": cov_index,
                       "totals": {"exchange_sources": src_tally,
                                  "n_uncovered": tot_uncovered}},
                      fh, separators=(",", ":"))
        print("wrote data/coverage.json (%d media)" % len(cov_index))
    print(f"media processed: {len(files)}  (written: {0 if dry else len(files)})")
    print(f"components recovered from unmapped -> exchanges: {tot_recovered}")
    print(f"still uncovered (kept structured): {tot_uncovered}")
    print("exchange sources across all components:")
    for s, n in sorted(src_tally.items(), key=lambda x: -x[1]):
        print(f"  {n:>8}  {s}")


if __name__ == "__main__":
    main()
