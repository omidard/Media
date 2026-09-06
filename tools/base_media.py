#!/usr/bin/env python3
"""
Standard base-media compositions, mapped to BiGG exchange ids.

THIS FILE IS THE **COMPOSITION** REGISTRY. IT IS NOT THE NAMING REGISTRY.
=========================================================================
`BASES` and `_PATTERNS` below exist for one purpose: deciding which standard
recipe to INJECT into a medium whose extraction lost its base (see
tools/expand_base_media.py). A match here rewrites chemistry.

The **naming / family** registry lives in `data/vocab/media_families.tsv` and is
consumed only by `tools/stages/normalize_names.py`. A family label there never
injects a component. The two registries are deliberately separate because
conflating them is exactly how a Wendy's quarter-pound hamburger
(usda_170772, "1/4 LB, single") acquired base_medium="LB" and 36 injected LB
yeast-extract components (audit finding NM-01), and it is why adding BG-11 to
this file "to fix the search" would silently inject a BG-11 salt scaffold into
53 cyanobacteria media (audit finding NM-05, risk 1).

DO NOT add a family to this file merely so that it can be grouped or searched.
Add it to data/vocab/media_families.tsv instead.

Many literature media are "<named standard base> + supplements" and the LLM
extraction captured only the supplements, dropping the base (e.g. "M9 + vitamin B1
+ trace elements + acetate" -> just acetate). This library holds the correct
standard composition of the common base media so they can be expanded deterministically.

Each base defines:
  defined      : BiGG ids of its defined chemical scaffold (salts, defined nutrients)
  complex      : complex-ingredient names to decompose (tryptone/yeast extract/...)
  carbon       : default carbon source id (added only if the medium names no other)
  trace        : trace-element ids (added when the recipe mentions trace elements)
  oxygen       : 'aerobic' | 'anaerobic' | 'facultative'
  cite         : formulation reference

Compositions follow standard references: M9/LB/TSB (Sambrook & Russell, Molecular
Cloning 2001; BD Bionutrient manuals), MOPS (Neidhardt et al. 1974 J Bacteriol),
M63 (Miller 1972), Davis (Davis & Mingioli 1950), MRS (de Man, Rogosa & Sharpe 1960),
Marine 2216 (ZoBell 1941), RPMI-1640 (Moore et al. 1967), Widdel & Bak 1992.
"""

# canonical mineral/salt scaffold ions and helpers (all standard BiGG ids)
_M9_SALTS = ["na1", "pi", "k", "cl", "nh4", "mg2", "so4", "ca2", "h2o", "h"]
_TRACE = ["fe2", "fe3", "mn2", "zn2", "cu2", "cobalt2", "mobd", "ni2"]
_AA20 = ["ala__L","arg__L","asn__L","asp__L","cys__L","gln__L","glu__L","gly","his__L","ile__L",
         "leu__L","lys__L","met__L","phe__L","pro__L","ser__L","thr__L","trp__L","tyr__L","val__L"]
_BVIT = ["thm","ribflv","nac","pnto__R","pydxn","fol","btn","cbl1","4abz"]

BASES = {
    "M9": {
        "defined": _M9_SALTS, "complex": [], "carbon": "glc__D", "trace": True,
        "oxygen": "facultative",
        "cite": "M9 minimal medium (Sambrook & Russell 2001): Na2HPO4, KH2PO4, NaCl, NH4Cl, MgSO4, CaCl2 + carbon source.",
    },
    "MOPS": {  # Neidhardt MOPS minimal
        "defined": _M9_SALTS + ["mops", "fe2"], "complex": [], "carbon": "glc__D", "trace": True,
        "oxygen": "facultative",
        "cite": "MOPS minimal medium (Neidhardt, Bloch & Smith 1974): MOPS-buffered defined salts + K2HPO4 + NH4Cl + micronutrients + carbon.",
    },
    "M63": {
        "defined": ["k", "pi", "nh4", "so4", "mg2", "fe2", "h2o", "h"], "complex": [],
        "carbon": "glc__D", "trace": False, "oxygen": "facultative",
        "cite": "M63 minimal medium (Miller 1972): KH2PO4, (NH4)2SO4, MgSO4, FeSO4 + thiamine + carbon.",
    },
    "Davis": {
        "defined": ["k", "pi", "nh4", "so4", "cit", "mg2", "na1", "h2o", "h"], "complex": [],
        "carbon": "glc__D", "trace": False, "oxygen": "facultative",
        "cite": "Davis minimal medium (Davis & Mingioli 1950): K2HPO4/KH2PO4, (NH4)2SO4, Na-citrate, MgSO4 + glucose.",
    },
    "LB": {  # Lysogeny/Luria broth (undefined: tryptone + yeast extract + NaCl)
        "defined": ["na1", "cl", "h2o", "h", "pi", "k", "mg2"], "complex": ["tryptone", "yeast extract"],
        "carbon": None, "trace": False, "oxygen": "facultative",
        "cite": "LB / Lysogeny broth (Bertani 1951; Sambrook & Russell 2001): tryptone 10 g/L, yeast extract 5 g/L, NaCl (in-silico approximation of the hydrolysates).",
    },
    "TSB": {  # tryptic soy broth
        "defined": ["na1", "cl", "k", "pi", "h2o", "h", "mg2"], "complex": ["casein peptone", "soytone"],
        "carbon": "glc__D", "trace": False, "oxygen": "facultative",
        "cite": "Tryptic Soy Broth (BD): casein & soy peptone, NaCl, K2HPO4, dextrose (in-silico approximation).",
    },
    "BHI": {
        "defined": ["na1", "cl", "pi", "k", "h2o", "h", "mg2"], "complex": ["peptone", "beef extract"],
        "carbon": "glc__D", "trace": False, "oxygen": "facultative",
        "cite": "Brain Heart Infusion (BD): brain/heart infusion solids, peptone, NaCl, phosphate, dextrose (in-silico approximation).",
    },
    "nutrient": {  # nutrient broth
        "defined": ["na1", "cl", "h2o", "h"], "complex": ["peptone", "beef extract"],
        "carbon": None, "trace": False, "oxygen": "facultative",
        "cite": "Nutrient broth (BD): peptone + beef/meat extract + NaCl (in-silico approximation).",
    },
    "MRS": {  # de Man Rogosa Sharpe (lactobacilli)
        "defined": ["na1", "cl", "ac", "cit", "nh4", "mg2", "mn2", "k", "pi", "h2o", "h"],
        "complex": ["peptone", "beef extract", "yeast extract"], "carbon": "glc__D", "trace": False,
        "oxygen": "facultative",
        "cite": "MRS medium (de Man, Rogosa & Sharpe 1960): peptone, beef & yeast extract, glucose, Tween-80, ammonium citrate, Na-acetate, MgSO4, MnSO4, K2HPO4.",
    },
    "marine": {  # Marine broth 2216 / ZoBell
        "defined": ["na1", "cl", "mg2", "so4", "ca2", "k", "hco3", "fe3", "h2o", "h"],
        "complex": ["peptone", "yeast extract"], "carbon": None, "trace": True, "oxygen": "facultative",
        "cite": "Marine Broth 2216 (ZoBell 1941; BD Difco): peptone, yeast extract, ferric citrate + sea-salt ion complement.",
    },
    "RPMI": {  # RPMI-1640 defined
        "defined": _M9_SALTS + ["glc__D"] + _AA20 + _BVIT + ["chol", "ins"],
        "complex": [], "carbon": "glc__D", "trace": False, "oxygen": "facultative",
        "cite": "RPMI-1640 (Moore et al. 1967): defined amino acids, vitamins, glucose, salts.",
    },
    "DMEM": {
        "defined": _M9_SALTS + ["glc__D"] + _AA20 + _BVIT + ["chol", "ins", "pyr"],
        "complex": [], "carbon": "glc__D", "trace": False, "oxygen": "facultative",
        "cite": "DMEM (Dulbecco & Freeman): defined amino acids, vitamins, glucose, pyruvate, salts.",
    },
    "Widdel": {  # anaerobic defined mineral medium
        "defined": ["na1", "cl", "mg2", "so4", "ca2", "k", "nh4", "pi", "fe2", "hco3", "h2s", "h2o", "h"],
        "complex": [], "carbon": None, "trace": True, "oxygen": "anaerobic",
        "cite": "Widdel & Bak (1992) defined anaerobic mineral medium: salts + NH4Cl + trace elements + vitamins + bicarbonate/sulfide reductant.",
    },
}

# name regex -> base key (order = priority; specific first)
#
# NOTE ON INPUT: these patterns must be matched against a medium's NAME ONLY.
# Matching them against `description` is a proven defect: 701 food records carry
# the generated phrase "plus a standard M9 mineral base" in their description and
# 0 food records name M9, so a name+description match would stamp 319 food media
# with base_medium="M9" and inject M9 salts into them (NM-01 verification (6),
# risk 5). detect_base() below now refuses description-shaped input.
import re as _re
_PATTERNS = [
    (_re.compile(r"tryptic soy|\bTSB\b|\bTSA\b", _re.I), "TSB"),
    (_re.compile(r"brain.?heart|\bBHIS?\b", _re.I), "BHI"),
    (_re.compile(r"\bMRS\b|de man", _re.I), "MRS"),
    (_re.compile(r"marine broth|\b2216\b|zobell", _re.I), "marine"),
    (_re.compile(r"\bMOPS\b.{0,20}(minimal|medium|buffered)", _re.I), "MOPS"),
    (_re.compile(r"\bM63\b", _re.I), "M63"),
    (_re.compile(r"davis (minimal|medium)", _re.I), "Davis"),
    (_re.compile(r"\bRPMI\b", _re.I), "RPMI"),
    (_re.compile(r"\bDMEM\b", _re.I), "DMEM"),
    (_re.compile(r"widdel", _re.I), "Widdel"),
    (_re.compile(r"\bLB\b|luria|lysogeny|lennox", _re.I), "LB"),
    (_re.compile(r"nutrient broth|nutrient agar", _re.I), "nutrient"),
    (_re.compile(r"\bM9\b", _re.I), "M9"),
]

# ---------------------------------------------------------------------------
# Quantity-context veto for "LB".
#
# "LB" is both a medium name and the abbreviation for POUND. usda_170772 is
# "WENDY'S, DAVE'S Hot 'N Juicy 1/4 LB, single" -- a quarter pound of beef, which
# the old bare `\bLB\b` matched. It was stamped base_medium="LB", had 39 of its 43
# measured USDA nutrients and all 10 measured minerals replaced by 36 LB
# yeast-extract decomposition components + 14 LB canonical components, and was
# ranked tier 1 "expert" in the shipped index citing Bertani 1951 (finding NM-01).
#
# The veto is UNIT-AWARE, not category-aware, because detect_base() takes a bare
# string and cannot see a record's category. Callers that DO have the record
# should additionally pass category= below.
#
# It must NOT over-fire: "1/3 LB Agar (DSMZ J842)" is one-third-strength LB
# medium, a real DSMZ variant, and vetoing it would lose a genuine family member.
# The discriminator is what FOLLOWS the LB token -- a medium-context word, or a
# food noun / end of clause.
#
# This is the single definition. tools/stages/normalize_names.py imports it
# rather than carrying a second copy, because two uncoordinated regexes for the
# same rule is exactly the defect that let base_media.py:113 and
# curate_wellknown_media.py:1618 both govern all 13,515 media independently.
LB_QUANTITY_VETO = _re.compile(
    r"(?:\d+\s*/\s*\d+|\d+(?:[.,]\d+)?|[¼½¾⅓⅔])\s*(?:-\s*)?LB\b"
    r"(?!\s*(?:agar|broth|medium|media|plate|slant|liquid|seawater|salt|\+))",
    _re.I)
_LB_QUANTITY_VETO = LB_QUANTITY_VETO  # back-compat alias

# A description is generated prose, not a name. If the caller hands us something
# description-shaped we refuse rather than silently matching a base that the
# description merely MENTIONS.
# Only phrases that occur in GENERATED DESCRIPTIONS and never in a medium name.
# Verified over all 13,515 shipped names: each of these occurs 0 times in `name`,
# whereas "mineral base" occurs in 701 food DESCRIPTIONS. ("in-silico" and
# "approximation" are deliberately NOT here -- 5 canonical std_* records carry
# them in their own names.)
_DESCRIPTION_SHAPED = _re.compile(
    r"standard M9 mineral base|measured amino acids|per 100 ?g|"
    r"rendered as a labeled|metabolizable components of", _re.I)


def veto_reasons(text, category=None):
    """Return the list of reasons a base must NOT be detected from `text`.

    Empty list == no veto. Exposed so callers can log WHY a base was refused
    instead of silently getting None.
    """
    t = text or ""
    out = []
    if category == "food":
        out.append("category_food")
    if _DESCRIPTION_SHAPED.search(t):
        out.append("description_shaped_input")
    return out


def detect_bases(text, category=None):
    """Return EVERY base whose pattern matches, not just the first.

    tools/base_media.py used to return the first hit in a fixed priority list,
    which silently mis-resolved multi-base names: "Luria Broth (LB) for in vitro
    bacterial growth; tryptic soy agar (TSA) for plating" returned TSB -- the
    plating agar beat the actual growth medium -- and "1/2 MRS + 1/2 BHI Agar"
    returned BHI, dropping the MRS half (NM-13 verification (b)).

    A caller that gets >1 base back must REFUSE to expand and flag the record
    ambiguous. Flag, do not force.
    """
    t = text or ""
    if veto_reasons(t, category):
        return []
    lb_vetoed = bool(_LB_QUANTITY_VETO.search(t))
    hits = []
    for rx, key in _PATTERNS:
        if key == "LB" and lb_vetoed:
            continue
        if rx.search(t):
            hits.append(key)
    return hits


def detect_base(text, category=None):
    """Back-compatible single-base detector, now with the vetoes applied.

    Returns None when the name is ambiguous between two bases, because injecting
    one base's scaffold into a medium that names two is a fabrication. Existing
    callers (tools/expand_base_media.py:51) therefore stop expanding ambiguous
    records instead of picking by pattern order.
    """
    hits = detect_bases(text, category=category)
    return hits[0] if len(hits) == 1 else None
