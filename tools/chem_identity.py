#!/usr/bin/env python3
"""Chemistry primitives for metabolite identity resolution.

This module exists because the Media pipeline's central defect was resolving
metabolite identity by lower-cased name string. Everything here works on
CHEMISTRY -- InChIKey layers, molecular formula element sets, case-sensitive
element/ion tokens and explicit stereo descriptors -- so that a name match can
be checked against structure instead of being trusted on its own.

Nothing in this module guesses. Every function returns None when the evidence
does not decide, and the caller is expected to record that as an absent value
rather than substitute a default.

InChIKey layout used below:
    AAAAAAAAAAAAAA-BBBBBBBBFV-P
    ^ skeleton (14)  ^ stereo/isotope (8) + flag + version  ^ protonation
Two compounds with the same skeleton block and different stereo blocks are
stereoisomers of one another (this is what separates L- from D-serine, and it
is invisible to a molecular-formula comparison).
"""
import re

# --------------------------------------------------------------------------
# InChIKey layers
# --------------------------------------------------------------------------

_IK_RE = re.compile(r"^([A-Z]{14})-([A-Z]{10})-([A-Z])$")


def ik_parts(ik):
    """('skeleton','stereo','proton') or None if not a well-formed InChIKey."""
    if not ik:
        return None
    m = _IK_RE.match(str(ik).strip().upper())
    return (m.group(1), m.group(2), m.group(3)) if m else None


def ik_skeleton(ik):
    p = ik_parts(ik)
    return p[0] if p else None


def ik_stereo(ik):
    p = ik_parts(ik)
    return p[1] if p else None


def same_skeleton(a, b):
    """True/False/None -- None when either key is missing or malformed."""
    sa, sb = ik_skeleton(a), ik_skeleton(b)
    if sa is None or sb is None:
        return None
    return sa == sb


def same_stereo(a, b):
    sa, sb = ik_stereo(a), ik_stereo(b)
    if sa is None or sb is None:
        return None
    return sa == sb


# --------------------------------------------------------------------------
# Molecular formula
# --------------------------------------------------------------------------

_ELEM_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


def formula_elements(formula):
    """Set of element symbols in a molecular formula. None if unparseable.

    Case matters: 'CO2' -> {'C','O'} (carbon dioxide) but 'Co' -> {'Co'}
    (cobalt). Collapsing case is exactly how CO2 became a cobalt ion.
    """
    if not formula:
        return None
    f = str(formula).strip()
    if not f or not f[0].isupper():
        return None
    out, pos = set(), 0
    for m in _ELEM_RE.finditer(f):
        if m.start() != pos:
            break
        out.add(m.group(1))
        pos = m.end()
    # tolerate BiGG's polymer suffixes ('C12H20O10*2', 'X', 'R')
    rest = f[pos:]
    if rest and not re.fullmatch(r"[*RXn0-9().+\-]*", rest):
        return None
    return out or None


def formula_counts(formula):
    """{'C':6,'H':12,...} or None."""
    els = formula_elements(formula)
    if els is None:
        return None
    out, pos = {}, 0
    for m in _ELEM_RE.finditer(str(formula).strip()):
        if m.start() != pos:
            break
        out[m.group(1)] = out.get(m.group(1), 0) + int(m.group(2) or 1)
        pos = m.end()
    return out or None


def heavy_skeleton(formula):
    """Element counts ignoring hydrogen -- protonation-state-insensitive."""
    c = formula_counts(formula)
    if c is None:
        return None
    return {k: v for k, v in c.items() if k != "H"}


def formulas_disagree(a, b):
    """True only when both parse AND their heavy-atom skeletons differ."""
    ha, hb = heavy_skeleton(a), heavy_skeleton(b)
    if ha is None or hb is None:
        return False
    return ha != hb


# --------------------------------------------------------------------------
# Stereo descriptors carried by a source name
# --------------------------------------------------------------------------

# Leading enantiomer descriptor. Deliberately anchored and punctuation-bounded so
# "Dextrose", "Lactose" and "DL-alanine" are not confused with "D-".
_STEREO_PREFIX = re.compile(r"^\s*\(?\s*(dl|d|l)\s*\)?\s*[-‐-―− ]\s*", re.I)
# Descriptors that appear after the compound name: "Serine, L-", "glucose (D)"
_STEREO_SUFFIX = re.compile(r"[,(]\s*(dl|d|l)\s*[-)]?\s*$", re.I)


def stereo_of_name(name):
    """'L' | 'D' | 'DL' | None -- the enantiomer the SOURCE declared."""
    if not name:
        return None
    s = str(name).strip()
    m = _STEREO_PREFIX.match(s)
    if not m:
        m = _STEREO_SUFFIX.search(s)
    if not m:
        return None
    tok = m.group(1).upper()
    return "DL" if tok == "DL" else tok


def strip_stereo_prefix(name):
    """'L-Serine' -> 'Serine'. Leaves everything else untouched."""
    if not name:
        return name
    return _STEREO_PREFIX.sub("", str(name), count=1)


_ID_STEREO = re.compile(r"__(D|L)$")


def stereo_of_id(bid):
    """'D' | 'L' | None from a BiGG id suffix ('ser__L' -> 'L')."""
    if not bid:
        return None
    m = _ID_STEREO.search(str(bid))
    return m.group(1) if m else None


def id_stereo_base(bid):
    """'ser__L' -> 'ser'; 'orn' -> 'orn'."""
    return _ID_STEREO.sub("", str(bid or ""))


# --------------------------------------------------------------------------
# Case-sensitive element / ion / small-molecule tokens
# --------------------------------------------------------------------------
# These are the tokens whose identity is destroyed by lower-casing. Resolved
# BEFORE any normalisation, keyed on the RAW source string with case and charge
# intact. This is the fix for CO2 -> EX_cobalt2_e: 'CO2' and 'Co2+' differ only
# in the case of the second character and in the trailing charge, and norm()
# deletes both.
#
# Every entry states the chemistry it asserts so the table can be reviewed.
FORMULA_TOKENS = {
    # token (verbatim, case-sensitive)   bigg id     what it is
    "CO2": ("co2", "carbon dioxide, CO2"),
    "CO₂": ("co2", "carbon dioxide, CO2"),
    "CO2(g)": ("co2", "carbon dioxide, gaseous"),
    "CO": ("co", "carbon monoxide, CO"),
    "Co": ("cobalt2", "cobalt, Co"),
    "Co2+": ("cobalt2", "cobalt(II) cation"),
    "Co(2+)": ("cobalt2", "cobalt(II) cation"),
    "Co++": ("cobalt2", "cobalt(II) cation"),
    "CoII": ("cobalt2", "cobalt(II) cation"),
    "NO": ("no", "nitric oxide, NO"),
    "No": (None, "nobelium -- never a medium component; refuse"),
    "N2": ("n2", "dinitrogen"),
    "N2O": ("n2o", "nitrous oxide"),
    "NO2": ("no2", "nitrite / nitrogen dioxide"),
    "NO3": ("no3", "nitrate"),
    "H2": ("h2", "dihydrogen"),
    "H2O": ("h2o", "water"),
    "H2S": ("h2s", "hydrogen sulfide"),
    "O2": ("o2", "dioxygen"),
    "CH4": ("ch4", "methane"),
    "HCO3": ("hco3", "bicarbonate"),
    "HCO3-": ("hco3", "bicarbonate"),
    "SO4": ("so4", "sulfate"),
    "PO4": ("pi", "orthophosphate"),
    "NH3": ("nh4", "ammonia -- BiGG models the ammonium ion"),
    "NH4": ("nh4", "ammonium"),
    "NH4+": ("nh4", "ammonium"),
}

# Tokens that a case-folded lookup would confuse with one another. When a raw
# source token normalises into one of these keys and is NOT resolved by
# FORMULA_TOKENS above, the mapper must refuse rather than pick, because the
# name index cannot tell the candidates apart.
AMBIGUOUS_NORM_KEYS = {
    "co2": "CO2 (carbon dioxide) vs Co2+ (cobalt(II)) -- case and charge decide",
    "co": "CO (carbon monoxide) vs Co (cobalt)",
    "no": "NO (nitric oxide) vs No (nobelium)",
    "ni": "Ni (nickel) vs NI",
}


def resolve_formula_token(raw):
    """Resolve a formula-shaped source token by CHEMISTRY, before normalisation.

    Returns (bigg_id_or_None, justification) when the raw token is recognised as
    a formula/ion token, else None. A returned bigg_id of None means 'recognised
    and deliberately refused'.
    """
    if not raw:
        return None
    tok = str(raw).strip()
    # tolerate a trailing charge or state annotation the sources use
    tok = re.sub(r"\s*\((?:g|aq|l|s|gas|aqueous)\)\s*$", "", tok, flags=re.I).strip()
    if tok in FORMULA_TOKENS:
        return FORMULA_TOKENS[tok]
    # A trailing charge: 'Cl-', 'SO42-', 'Ca2+'. Strip the SIGN first and only then a
    # digit that turns out to be part of the charge, or 'NO3-' loses its subscript and
    # becomes NO -- nitrate read as nitric oxide.
    for pattern in (r"[+-]+$", r"\d[+-]+$"):
        bare = re.sub(pattern, "", tok).strip()
        if bare != tok and bare in FORMULA_TOKENS:
            return FORMULA_TOKENS[bare]
    return None


def looks_formula_shaped(raw):
    """True for short tokens made only of element letters, digits and charges."""
    if not raw:
        return False
    tok = str(raw).strip()
    return bool(re.fullmatch(r"[A-Za-z]{1,3}\d{0,2}[+-]{0,2}", tok))
