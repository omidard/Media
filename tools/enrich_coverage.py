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
from complex_ingredients import (decompose, REFS, ingredient_key, reference_link,  # noqa: E402
                                 COMPOSITION_MG_PER_G, MINERAL_IDS)

# ---- molecular weights (from BiGG formula) for molar-weighting quantitative decompositions ----
_AW = {"H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999, "S": 32.06, "P": 30.974,
       "K": 39.098, "Na": 22.990, "Mg": 24.305, "Ca": 40.078, "Fe": 55.845, "Zn": 65.38,
       "Mn": 54.938, "Cu": 63.546, "Co": 58.933, "Ni": 58.693, "Mo": 95.95, "Cl": 35.45,
       "Se": 78.97, "B": 10.811}
_ELEM_OF = {"k": "K", "na1": "Na", "mg2": "Mg", "ca2": "Ca", "fe2": "Fe", "zn2": "Zn",
            "mn2": "Mn", "cu2": "Cu", "cobalt2": "Co", "pi": "P", "so4": "S"}

def _formula_mw(formula):
    if not formula:
        return None
    tot = 0.0
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        if el not in _AW:
            return None
        tot += _AW[el] * (int(n) if n else 1)
    return tot or None

def _mw(bid):
    if bid in _ELEM_OF:                      # minerals: use the element weight
        return _AW[_ELEM_OF[bid]]
    return _formula_mw((DICT.get(bid, {}).get("xrefs") or {}).get("formula"))

def _ingredient_amounts(mg_table):
    """{bigg_id: {mg_per_g, mmol_per_g, lower_bound}} — organics molar-weighted, minerals -1000."""
    out = {}
    for b, mg in mg_table.items():
        if not valid(b):
            continue
        mw = _mw(b)
        mmol = (mg / mw) if mw else None       # raw (unrounded) mmol per g
        out[b] = {"mg_per_g": mg, "_mmol": mmol,
                  "mmol_per_g": (round(mmol, 5) if mmol else None), "mw": mw}
    # molar-weighted bound for organics: most-abundant organic -> -10, floor -0.1
    org = [v["_mmol"] for b, v in out.items() if b not in MINERAL_IDS and v["_mmol"]]
    mx = max(org) if org else 1.0
    for b, v in out.items():
        if b in MINERAL_IDS:
            v["lower_bound"] = -1000.0
        elif v["_mmol"]:
            v["lower_bound"] = round(min(max(-10.0 * v["_mmol"] / mx, -10.0), -0.1), 3)
        else:
            v["lower_bound"] = -1.0
        v.pop("_mmol", None)
    return out

_AMOUNTS_CACHE = {}
def ingredient_amounts(key):
    """Cached per-ingredient quantitative amounts, {} if the ingredient has no mg/g table."""
    if key not in _AMOUNTS_CACHE:
        _AMOUNTS_CACHE[key] = _ingredient_amounts(COMPOSITION_MG_PER_G.get(key, {}))
    return _AMOUNTS_CACHE[key]

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
    # phosphate salts -> cation + inorganic phosphate (pi)
    "kh2po4": ["k", "pi"], "monopotassiumphosphate": ["k", "pi"], "potassiumdihydrogenphosphate": ["k", "pi"],
    "k2hpo4": ["k", "pi"], "dipotassiumphosphate": ["k", "pi"], "potassiumphosphatedibasic": ["k", "pi"],
    "k3po4": ["k", "pi"], "na2hpo4": ["na1", "pi"], "disodiumphosphate": ["na1", "pi"],
    "sodiumphosphatedibasic": ["na1", "pi"], "nah2po4": ["na1", "pi"], "monosodiumphosphate": ["na1", "pi"],
    "sodiumphosphatemonobasic": ["na1", "pi"], "na3po4": ["na1", "pi"], "nh42hpo4": ["nh4", "pi"],
    "diammoniumphosphate": ["nh4", "pi"], "nh4h2po4": ["nh4", "pi"],
    # chloride salts
    "nh4cl": ["nh4", "cl"], "ammoniumchloride": ["nh4", "cl"], "cacl2": ["ca2", "cl"], "calciumchloride": ["ca2", "cl"],
    "mgcl2": ["mg2", "cl"], "magnesiumchloride": ["mg2", "cl"], "fecl3": ["fe3", "cl"], "ferricchloride": ["fe3", "cl"],
    "fecl2": ["fe2", "cl"], "ferrouschloride": ["fe2", "cl"], "mncl2": ["mn2", "cl"], "manganesechloride": ["mn2", "cl"],
    "zncl2": ["zn2", "cl"], "cucl2": ["cu2", "cl"], "cocl2": ["cobalt2", "cl"], "cobaltchloride": ["cobalt2", "cl"],
    "nicl2": ["ni2", "cl"], "cocl26h2o": ["cobalt2", "cl"],
    # sulfate salts
    "nh42so4": ["nh4", "so4"], "ammoniumsulfate": ["nh4", "so4"], "feso4": ["fe2", "so4"], "ferroussulfate": ["fe2", "so4"],
    "fe2so43": ["fe3", "so4"], "mnso4": ["mn2", "so4"], "manganesesulfate": ["mn2", "so4"], "znso4": ["zn2", "so4"],
    "zincsulfate": ["zn2", "so4"], "cuso4": ["cu2", "so4"], "coppersulfate": ["cu2", "so4"], "caso4": ["ca2", "so4"],
    "k2so4": ["k", "so4"], "coso4": ["cobalt2", "so4"], "niso4": ["ni2", "so4"],
    # nitrate / molybdate / iodide / other
    "kno3": ["k", "no3"], "potassiumnitrate": ["k", "no3"], "nh4no3": ["nh4", "no3"], "cano32": ["ca2", "no3"],
    "mgno32": ["mg2", "no3"], "na2moo4": ["na1", "mobd"], "sodiummolybdate": ["na1", "mobd"],
    "nh46mo7o24": ["nh4", "mobd"], "ki": ["k", "iodine"], "potassiumiodide": ["k", "iodine"], "nai": ["na1", "iodine"],
    "na2seo4": ["na1", "slnt"], "kh2po4monopotassiumphosphate": ["k", "pi"],
    # sodium/potassium salts of organic acids -> ion + organic anion
    "sodiumformate": ["na1", "for"], "potassiumformate": ["k", "for"],
    "sodiumacetate": ["na1", "ac"], "potassiumacetate": ["k", "ac"],
    "sodiumpyruvate": ["na1", "pyr"], "sodiumlactate": ["na1", "lac__L"],
    "sodiumsuccinate": ["na1", "succ"], "sodiumcitrate": ["na1", "cit"],
    "tripotassiumcitrate": ["k", "cit"], "sodiumgluconate": ["na1", "glcn"],
    "sodiumpropionate": ["na1", "ppa"], "sodiumbutyrate": ["na1", "but"],
    "sodiummalate": ["na1", "mal__L"], "sodiumfumarate": ["na1", "fum"],
    # sulfides / misc
    "sodiumsulfide": ["na1", "h2s"], "sodiumsulphide": ["na1", "h2s"], "na2s": ["na1", "h2s"],
    "potassiumsulfide": ["k", "h2s"], "ammoniumsulfide": ["nh4", "h2s"],
    "ferricammoniumcitrate": ["fe3", "nh4", "cit"], "ironiiiammoniumcitrate": ["fe3", "nh4", "cit"],
    "ammoniumironiiisulfate": ["fe3", "nh4", "so4"], "ammoniumferricsulfate": ["fe3", "nh4", "so4"],
    "ferrousammoniumsulfate": ["fe2", "nh4", "so4"], "ammoniumironiisulfate": ["fe2", "nh4", "so4"],
    "sodiumtungstate": ["na1", "tungs"], "na2wo4": ["na1", "tungs"],
}
# strip a trailing hydrate (·7H2O, .2H2O, x6H2O, " 7H2O") before matching
_HYDRATE = re.compile(r"[·.x*]\s*\d*\s*h2o$|\s+\d*\s*h2o$", re.I)
def _dehydrate(s):
    return _HYDRATE.sub("", (s or "").strip())
SALTS = {k: [b for b in v if valid(b)] for k, v in _SALTS_RAW.items()}
SALTS = {k: v for k, v in SALTS.items() if v}

# --- compositional inorganic-salt parser: dissociate ANY "cation ... anion" name into ions ---
# Distinguishes known inorganic ions (BiGG id, or None if BiGG lacks that element -> skip it) from
# unknown tokens (-> reject). So double/hydrated salts dissociate, while organic esters
# ("bornyl acetate", "ethyl acetate") and antibiotics ("kanamycin sulfate") are left untouched.
_CATION = {
    "sodium":"na1","na":"na1","potassium":"k","ammonium":"nh4","calcium":"ca2","magnesium":"mg2",
    "ferrous":"fe2","ferric":"fe3","iron":"fe2","zinc":"zn2","copper":"cu2","cupric":"cu2","cuprous":"cu2",
    "manganese":"mn2","manganous":"mn2","manganic":"mn2","cobalt":"cobalt2","cobaltous":"cobalt2",
    "nickel":"ni2","nickelous":"ni2","lead":"pb",
    # recognized inorganic cations that BiGG has no metabolite for -> skip (do NOT reject the salt)
    "aluminium":None,"aluminum":None,"barium":None,"strontium":None,"lanthanum":None,"cerium":None,
    "rubidium":None,"cesium":None,"caesium":None,"lithium":None,"chromium":None,"chromic":None,
    "silver":None,"tin":None,"titanium":None,"vanadium":None,
}
_ANION = {
    "sulfate":"so4","sulphate":"so4","chloride":"cl","phosphate":"pi","nitrate":"no3",
    "carbonate":"hco3","bicarbonate":"hco3","hydrogencarbonate":"hco3","sulfide":"h2s","sulphide":"h2s",
    "hydroxide":"oh1","molybdate":"mobd","tungstate":"tungs","selenate":"slnt","selenite":"slnt",
    "iodide":"iodine","thiosulfate":"tsul","thiosulphate":"tsul","citrate":"cit","gluconate":"glcn",
    "acetate":"ac","formate":"for","nitrite":"no2",
    # recognized anions BiGG has no metabolite for -> skip
    "bromide":None,"fluoride":None,"borate":None,"silicate":None,
}
_SALT_STOP = {"hydrogen","hydrate","anhydrous","hydrated","and","of","the","x","dot","ph","w","v","wv",
              "reductant","buffer","solution","source","base","trace","mix","element","elements","dihydrogen"}
_HYD_WORD = re.compile(r"\b\w*hydrate\b|\banhydrous\b", re.I)
_PREFIX = re.compile(r"^(?:di|tri|tetra|penta|hexa|hepta|octa|nona|deca|dodeca|mono|bis|hemi|bi)")

def parse_salt(name):
    """Dissociate an inorganic salt NAME into BiGG ions, or None. Tries the name with
    parentheticals removed AND any parenthetical content (handles 'Na2S·9H2O (sodium
    sulfide)' where the parsable name is in the parens)."""
    raw = name or ""
    cands = [re.sub(r"\([^)]*\)", " ", raw)] + re.findall(r"\(([^)]*)\)", raw)
    for c in cands:
        ions = _parse_one(c)
        if ions:
            return ions
    return None

def _parse_one(s):
    s = (s or "").lower()
    s = re.split(r"->|→|/|,|;| - ", s)[0]              # keep the part before a note/arrow
    s = _HYD_WORD.sub(" ", s)                               # dodeca/hexa/mono-hydrate, anhydrous
    s = _dehydrate(s)                                       # ·7H2O forms
    toks = re.findall(r"[a-z]+", s)
    if not toks:
        return None
    cats, ans = [], []
    for t in toks:
        if t in _SALT_STOP:
            continue
        cand = t if (t in _CATION or t in _ANION) else _PREFIX.sub("", t)
        if cand in _CATION:
            cats.append(_CATION[cand])
        elif cand in _ANION:
            ans.append(_ANION[cand])
        elif cand in _SALT_STOP:
            continue
        elif len(cand) <= 2:
            continue                                       # stray formula fragment ("so", "po") — ignore
        else:
            return None                                    # unknown token -> not a clean inorganic salt
    if not cats or not ans:
        return None
    ions = []
    for b in cats + ans:
        if b and valid(b) and b not in ions:
            ions.append(b)
    return ions or None

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
    # "KH2PO4 -> Potassium" / "MgSO4·7H2O -> Sulfate": the real compound (a formula the
    # salt table can dissociate) is the part BEFORE the arrow; the ion after it is just an
    # annotation. Keep only the left side so the formula dissociates into all its ions.
    arrow = re.split(r"\s*(?:->|→|⟶|=>|➞|→)\s*", name)
    if len(arrow) > 1 and arrow[0].strip():
        add(arrow[0])
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
    ref = REFS.get(ingredient_key(name))
    amounts = ingredient_amounts(key)
    out = []
    for b in ids:
        rec = DICT.get(b, {})
        amt = amounts.get(b)
        c = {
            "name": rec.get("name", b), "bigg_metabolite": b, "exchange": "EX_%s_e" % b,
            "lower_bound": (amt["lower_bound"] if amt else -1.0), "upper_bound": 1000.0,
            "concentration_mM": None,
            "xref": rec.get("xrefs", {}), "in_biggr": rec.get("in_biggr", False),
            "exchange_source": ("biggr" if rec.get("in_biggr") else "bigg"),
            "mapping_method": "complex_decomposition", "mapping_confidence": "approximation",
            "derived_from": name,
        }
        if amt:                              # quantitative composition (mg per g yeast extract)
            c["mg_per_g_source"] = amt["mg_per_g"]
            if amt.get("mmol_per_g"):
                c["mmol_per_g_source"] = amt["mmol_per_g"]
        if ref:
            c["decomposition_ref"] = ref
        out.append(c)
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
    # 2) salt dissociation -> ions. Try every name variant, stripping hydrate (·7H2O)
    for cand in _name_variants(name):
        n = norm(_dehydrate(cand))
        if n in SALTS:
            return [new_component({"bigg_metabolite": b, "exchange": f"EX_{b}_e",
                                   "in_biggr": DICT.get(b, {}).get("in_biggr", False),
                                   "mapping_confidence": "inferred"}, name, "salt_dissociation_remap")
                    for b in SALTS[n]]
    # 2b) compositional inorganic-salt parser (double/hydrated salts not in the fixed table)
    ions = parse_salt(name)
    if ions:
        return [new_component({"bigg_metabolite": b, "exchange": f"EX_{b}_e",
                               "in_biggr": DICT.get(b, {}).get("in_biggr", False),
                               "mapping_confidence": "inferred"}, name, "salt_parse_remap")
                for b in ions]
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
        if c.get("mapping_method") == "complex_decomposition":
            ik = ingredient_key(c.get("derived_from", ""))
            # backfill the decomposition reference
            if not c.get("decomposition_ref"):
                r = REFS.get(ik)
                if r:
                    c["decomposition_ref"] = r
            # backfill QUANTITATIVE composition amounts + molar-weighted bounds onto
            # components already decomposed at build time (std/DSMZ/food media)
            amt = ingredient_amounts(ik).get(c.get("bigg_metabolite")) if ik else None
            if amt:
                c["lower_bound"] = amt["lower_bound"]
                c["mg_per_g_source"] = amt["mg_per_g"]
                if amt.get("mmol_per_g"):
                    c["mmol_per_g_source"] = amt["mmol_per_g"]
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
    # record the references for any complex-ingredient decomposition used in this medium
    drefs = {}
    for c in comps:
        if c.get("mapping_method") == "complex_decomposition":
            r = c.get("decomposition_ref")
            if r:
                ing = c.get("derived_from", "")
                drefs[ing] = {"citation": r, "url": reference_link(ing)}
    if drefs:
        med.setdefault("provenance", {})["decomposition_refs"] = drefs
    else:
        med.get("provenance", {}).pop("decomposition_refs", None)
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
