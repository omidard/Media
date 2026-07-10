#!/usr/bin/env python3
"""
Standard base-media compositions, mapped to BiGG exchange ids.

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

# name/description regex -> base key (order = priority; specific first)
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


def detect_base(text):
    for rx, key in _PATTERNS:
        if rx.search(text or ""):
            return key
    return None
