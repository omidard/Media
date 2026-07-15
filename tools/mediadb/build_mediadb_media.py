#!/usr/bin/env python3
"""Build media records from MediaDB (ISB) defined media -> repo/data/media/mdb_<id>.json.

Mapping order per compound:
  1) MediaDB's own bigg_id (old-format single-underscore/dash normalised to current)
  2) cleaned name (strip hydrate/anhydrous/HCl) -> explicit salt dissociation table
  3) cleaned name / xref -> shared recover() ladder (name, salt, KEGG/ChEBI fallback)
  4) known buffers/chelators -> uncovered (non_nutrient)
  5) else uncovered (needs_manual_curation), keeping KEGG/ChEBI/PubChem/SEED xrefs
Concentrations (mM) and reference links (MediaDB page + PubMed) are retained.
"""
import os, re, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "repo")
sys.path.insert(0, os.path.join(REPO, "tools"))
import enrich_coverage as EC   # recover(), MAP

DICT = json.load(open(os.path.join(REPO, "tools", "bigg_metabolite_dict.json")))
KEYS = set(DICT.keys())
def valid(b): return b in KEYS

MINERAL = {"na1","cl","k","pi","so4","mg2","ca2","fe2","fe3","mn2","zn2","cu2","cobalt2",
           "mobd","ni2","nh4","h2o","h","o2","hco3","co2","no3","no2","so3","tsul","slnt",
           "sel","cd2","hg2","wo4","glcn","cit","ac"}

# explicit salt dissociation (cleaned lower-case name -> ion BiGG ids); Al/Sn/W dropped if absent
_SALTS = {
 "magnesium sulfate":["mg2","so4"], "calcium chloride":["ca2","cl"], "ammonium chloride":["nh4","cl"],
 "potassium dihydrogen phosphate":["k","pi"], "potassium phosphate monobasic":["k","pi"],
 "monopotassium phosphate":["k","pi"], "sodium chloride":["na1","cl"],
 "potassium dibasic phosphate":["k","pi"], "potassium phosphate dibasic":["k","pi"],
 "dipotassium phosphate":["k","pi"], "ferrous sulfate":["fe2","so4"], "iron(ii) sulfate":["fe2","so4"],
 "zinc sulfate":["zn2","so4"], "sodium molybdate":["na1","mobd"], "manganese sulfate":["mn2","so4"],
 "manganese chloride":["mn2","cl"], "manganese(ii) chloride":["mn2","cl"], "cupric sulfate":["cu2","so4"],
 "copper sulfate":["cu2","so4"], "copper(ii) sulfate":["cu2","so4"], "magnesium chloride":["mg2","cl"],
 "dibasic sodium phosphate":["na1","pi"], "sodium phosphate dibasic":["na1","pi"], "disodium phosphate":["na1","pi"],
 "sodium dihydrogen phosphate":["na1","pi"], "sodium phosphate monobasic":["na1","pi"], "monosodium phosphate":["na1","pi"],
 "potassium chloride":["k","cl"], "cobalt chloride":["cobalt2","cl"], "cobaltous chloride":["cobalt2","cl"],
 "cobalt(ii) chloride":["cobalt2","cl"], "nickel chloride":["ni2","cl"], "nickel(ii) chloride":["ni2","cl"],
 "ammonium sulfate":["nh4","so4"], "cupric chloride":["cu2","cl"], "copper chloride":["cu2","cl"],
 "iron(iii) chloride":["fe3","cl"], "ferric chloride":["fe3","cl"], "sodium bicarbonate":["na1","hco3"],
 "zinc chloride":["zn2","cl"], "cobaltous sulfate":["cobalt2","so4"], "cobalt sulfate":["cobalt2","so4"],
 "cobalt(ii) sulfate":["cobalt2","so4"], "ferrous chloride":["fe2","cl"], "iron(ii) chloride":["fe2","cl"],
 "sodium sulfate":["na1","so4"], "potassium sulfate":["k","so4"], "sodium citrate":["na1","cit"],
 "trisodium citrate":["na1","cit"], "sodium selenite":["na1","slnt"], "sodium nitrate":["na1","no3"],
 "potassium nitrate":["k","no3"], "sodium acetate":["na1","ac"], "sodium ammonium phosphate":["na1","nh4","pi"],
 "sodium glutamate":["na1","glu__L"], "monosodium glutamate":["na1","glu__L"], "potassium gluconate":["k","glcn"],
 "calcium pantothenate":["ca2","pnto__R"], "aluminum potassium sulfate":["k","so4"],
 "nickel(ii) ammonium sulfate":["ni2","nh4","so4"], "nickel ammonium sulfate":["ni2","nh4","so4"],
 "molybdic acid ammonium salt":["mobd","nh4"], "ammonium molybdate":["mobd","nh4"],
 "ammonium heptamolybdate":["mobd","nh4"], "ammonium paramolybdate":["mobd","nh4"],
 "cobalt nitrate":["cobalt2","no3"], "cobaltous nitrate":["cobalt2","no3"], "cobalt(ii) nitrate":["cobalt2","no3"],
 "ferric nitrate":["fe3","no3"], "iron(iii) nitrate":["fe3","no3"], "potassium hydroxide":["k"],
 "sodium hydroxide":["na1"], "ferric oxide":["fe3"], "iron(iii) oxide":["fe3"],
 "ferrous ammonium sulfate":["fe2","nh4","so4"], "ferric ammonium citrate":["fe3","nh4","cit"],
 "sodium selenate":["na1","sel"], "sodium phosphite":["na1","pi"], "nickel sulfate":["ni2","so4"],
 "nickel(ii) sulfate":["ni2","so4"], "manganese(iv) oxide":["mn2"], "sodium tungstate":["na1"],
 "potassium iodide":["k"], "zinc acetate":["zn2","ac"], "cobalt acetate":["cobalt2","ac"],
 "magnesium acetate":["mg2","ac"], "potassium acetate":["k","ac"], "ammonium acetate":["nh4","ac"],
 "calcium acetate":["ca2","ac"], "ammonium ferric citrate":["fe3","nh4","cit"],
 "ammonium iron(iii) citrate":["fe3","nh4","cit"], "sodium sulfide":["na1"], "diammonium phosphate":["nh4","pi"],
 "ammonium phosphate":["nh4","pi"], "calcium carbonate":["ca2","hco3"], "sodium carbonate":["na1","hco3"],
 "potassium carbonate":["k","hco3"], "magnesium carbonate":["mg2","hco3"], "sodium thiosulfate":["na1","tsul"],
 "sodium pantothenate":["na1","pnto__R"], "calcium d-pantothenate":["ca2","pnto__R"],
}
# buffers / chelators / non-metabolite additives -> uncovered (not an exchange)
_NONNUTRIENT = {"hepes","mops","pipes","tricine","tromethamine","tris","tris base","bis-tris",
 "edta","nitrilotriacetic acid","nitrilotriacetate","boric acid","ethylene glycol","resazurin",
 "agar","agarose","tween 80","tween 20","antifoam","phenol red","bromothymol blue","tes",
 "3-(n-morpholino)propanesulfonic acid","piperazine-n,n'-bis(2-ethanesulfonic acid)"}

def norm_bigg(b):
    if not b: return None
    if b in KEYS: return b
    for cand in (b.replace("-","__"), re.sub(r"[-_]([A-Za-z]+)$", r"__\1", b), b.replace("_","__")):
        if cand in KEYS: return cand
    return None

def clean(n):
    s = n
    s = re.sub(r"\s*[·.\*]\s*\d*\s*h2o.*$", "", s, flags=re.I)                 # hydrate ·7H2O
    s = re.sub(r"\b(?:mono|di|tri|tetra|penta|hexa|hepta|octa)?hydrate\b", "", s, flags=re.I)
    s = re.sub(r"\banhydrous\b", "", s, flags=re.I)
    s = re.sub(r"[\s-]*(?:hydrochloride|dihydrochloride|hcl)\b", "", s, flags=re.I)   # X HCl -> X
    s = re.sub(r"^\s*dl-", "", s, flags=re.I)                                   # racemic -> base (->L)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def bound(bid): return -1000.0 if bid in MINERAL else -10.0

def mk(bid, name, mM, method, conf):
    return {"name": name, "bigg_metabolite": bid, "exchange": f"EX_{bid}_e",
            "lower_bound": bound(bid), "upper_bound": 1000.0, "concentration_mM": mM,
            "in_biggr": DICT.get(bid, {}).get("in_biggr", False),
            "mapping_method": method, "mapping_confidence": conf,
            "exchange_source": "biggr" if DICT.get(bid, {}).get("in_biggr") else "bigg"}

def _xref(c):
    return {k: v for k, v in {"kegg": c.get("kegg"), "chebi": c.get("chebi"),
            "seed": c.get("seed"), "pubchem": c.get("pubchem")}.items() if v}

def map_compound(c):
    """Return (list_of_components, uncovered_or_None)."""
    nm = c["name"]; mM = c.get("mM")
    bid = norm_bigg(c.get("bigg"))
    if bid:
        return [mk(bid, nm, mM, "mediadb_bigg", "curated")], None
    cl = clean(nm); low = cl.lower()
    if low in _NONNUTRIENT:
        return [], {"name": nm, "reason": "non_nutrient", "curation": "no_exchange",
                    "xref": _xref(c), "note": "buffer/chelator/additive — not a metabolite exchange"}
    if low in _SALTS:
        ions = [b for b in _SALTS[low] if valid(b)]
        if ions:
            return [mk(b, nm, mM, "mediadb_salt_dissociation", "inferred") for b in ions], None
    xref = {k: c.get(k) for k in ("kegg", "chebi") if c.get(k)}
    r = EC.recover(cl, xref)
    recs = r if isinstance(r, list) else ([r] if r else [])
    if recs:
        out = []
        for x in recs:
            x.setdefault("name", nm)
            if mM is not None: x["concentration_mM"] = mM
            x["lower_bound"] = bound(x.get("bigg_metabolite", ""))
            out.append(x)
        return out, None
    return [], {"name": nm, "reason": "unmatched", "curation": "needs_manual_curation",
                "xref": _xref(c), "note": "MediaDB compound with no BiGG mapping"}

def build_one(mid, rec, sources):
    comps = {}; uncovered = []; ncomp = 0
    for c in rec["compounds"]:
        ncomp += 1
        got, unc = map_compound(c)
        for x in got:
            comps.setdefault(x["exchange"], x)
        if unc:
            uncovered.append(unc)
    srcs = [sources.get(str(s)) or sources.get(s) for s in rec["source_ids"]]
    srcs = [s for s in srcs if s]
    cites = "; ".join(s["citation"] for s in srcs) or "MediaDB (Institute for Systems Biology)"
    pmids = [s["pubmed"] for s in srcs if s.get("pubmed")]
    mdb_url = f"https://mediadb.systemsbiology.net/defined_media/media/{mid}/"
    refs = [{"citation": s["citation"],
             "url": (f"https://pubmed.ncbi.nlm.nih.gov/{s['pubmed']}/" if s.get("pubmed") else mdb_url),
             "pmid": s.get("pubmed")} for s in srcs] or [{"citation": cites, "url": mdb_url, "pmid": None}]
    prov = {"source_type": "MediaDB (ISB defined media)",
            "citation": cites[:240], "url": mdb_url, "doi": None,
            "pmid": (pmids[0] if pmids else None), "references": refs,
            "notes": f"Defined medium curated by MediaDB (Institute for Systems Biology); "
                     f"formulation page {mdb_url}. Original reference: {cites}. Concentrations in mM from MediaDB.",
            "verification": "reference-database (MediaDB, ISB)"}
    nmap = len(comps)
    nm = rec["name"]; nm = (nm[0].upper() + nm[1:]) if nm else nm
    return {"id": f"mdb_{mid}", "name": nm, "category": "laboratory", "organism_scope": "",
            "aerobic": True, "oxygen": "facultative", "defined": True,
            "description": f"Defined medium from MediaDB (ISB), formulation {mid}.",
            "namespace": "bigg", "components": sorted(comps.values(), key=lambda x: x["exchange"]),
            "uncovered": uncovered, "n_components": nmap, "n_mapped": nmap,
            "n_in_biggr": sum(1 for x in comps.values() if x.get("in_biggr")),
            "provenance": prov,
            "coverage": {"n_compounds": ncomp, "n_covered": nmap, "n_uncovered": len(uncovered),
                         "pct_covered": round(100*nmap/max(ncomp,1), 1)}}

def main():
    raw = json.load(open(os.path.join(HERE, "mediadb_raw.json")))
    sources = raw["sources"]; dry = "--dry" in sys.argv
    out_dir = os.path.join(REPO, "data", "media")
    written = tot_c = tot_map = tot_unc = 0
    import collections; unc_c = collections.Counter()
    for mid, rec in raw["media"].items():
        m = build_one(mid, rec, sources)
        tot_c += m["coverage"]["n_compounds"]; tot_map += m["n_mapped"]; tot_unc += m["coverage"]["n_uncovered"]
        for u in m["uncovered"]: unc_c[u["name"]] += 1
        if not dry:
            json.dump(m, open(os.path.join(out_dir, m["id"] + ".json"), "w"), ensure_ascii=False)
        written += 1
    print(f"media built: {written} | compounds {tot_c} | mapped {tot_map} | uncovered {tot_unc} "
          f"({100*tot_unc//max(tot_c,1)}% uncovered)")
    print("top remaining uncovered:", unc_c.most_common(12))
    print("dry run (nothing written)" if dry else f"wrote {written} mdb_*.json")

if __name__ == "__main__":
    main()
