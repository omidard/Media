#!/usr/bin/env python3
"""
Decomposition of undefined complex ingredients into their approximate defined
chemical composition, mapped to BiGG exchange ids.

Complex ingredients (yeast extract, tryptone, peptone, casamino acids, beef/malt
extract, ...) are undefined hydrolysates. Their bulk chemical composition is well
characterised in the literature, so we expand each into a labelled in-silico
approximation: the amino acids, B-vitamins, nucleosides, sugars and minerals it is
known to supply. These become real exchanges (so a model can actually grow on the
medium) but are flagged mapping_confidence="approximation" and carry derived_from.

Compositions are standard microbiological knowledge (e.g. BD Bionutrient manuals;
Zarnitz & Pfennig; Atlas, Handbook of Microbiological Media). Casamino acids omit
tryptophan (destroyed by acid hydrolysis); malt extract is sugar-dominant.
"""
import re

AA20 = ["ala__L", "arg__L", "asn__L", "asp__L", "cys__L", "gln__L", "glu__L", "gly",
        "his__L", "ile__L", "leu__L", "lys__L", "met__L", "phe__L", "pro__L", "ser__L",
        "thr__L", "trp__L", "tyr__L", "val__L"]
AA_NO_TRP = [a for a in AA20 if a != "trp__L"]
BVIT = ["thm", "ribflv", "nac", "pnto__R", "pydxn", "fol", "btn", "cbl1", "4abz"]
NUC = ["adn", "gsn", "cytd", "uri", "ins", "thymd"]
MIN = ["k", "mg2", "pi", "ca2", "fe2", "zn2", "mn2", "cu2", "cobalt2", "so4"]
SUG_MALT = ["malt", "glc__D", "malttr"]

# ingredient key (matched by regex on the component name) -> constituent BiGG ids
COMPOSITION = {
    "yeast_extract":   AA20 + BVIT + NUC + MIN,      # richest: AAs + all B-vits + nucleosides
    "tryptone":        AA20 + ["thm", "ribflv", "nac"],   # casein tryptic digest: AA-rich
    "casein_peptone":  AA20 + ["thm", "ribflv", "nac"],
    "trypticase":      AA20 + ["thm", "ribflv", "nac"],
    "peptone":         AA20 + ["nac", "ribflv"],     # generic proteolytic digest
    "proteose_peptone": AA20 + ["nac", "ribflv"],
    "soytone":         AA20 + ["thm", "ribflv", "nac"] + ["glc__D"],
    "casamino_acids":  AA_NO_TRP,                    # acid hydrolysis destroys Trp
    "beef_extract":    AA20 + BVIT + NUC + MIN,
    "meat_extract":    AA20 + BVIT + NUC + MIN,
    "lab_lemco":       AA20 + BVIT + NUC + MIN,
    "malt_extract":    SUG_MALT + AA20[:6] + ["thm", "ribflv", "nac", "pydxn"],  # sugar-dominant
}

# name -> ingredient key (order matters: more specific first)
_PATTERNS = [
    (re.compile(r"casamino", re.I), "casamino_acids"),
    (re.compile(r"casein\s*(peptone|hydrolysate|digest)|tryptic\s*digest\s*of\s*casein", re.I), "casein_peptone"),
    (re.compile(r"trypticase", re.I), "trypticase"),
    (re.compile(r"tryptone", re.I), "tryptone"),
    (re.compile(r"proteose\s*peptone", re.I), "proteose_peptone"),
    (re.compile(r"soytone|soy\s*peptone|soybean\s*peptone", re.I), "soytone"),
    (re.compile(r"yeast\s*extract|yeast\s*autolysate", re.I), "yeast_extract"),
    (re.compile(r"malt\s*extract", re.I), "malt_extract"),
    (re.compile(r"beef\s*extract", re.I), "beef_extract"),
    (re.compile(r"meat\s*extract|lab-?lemco", re.I), "meat_extract"),
    (re.compile(r"\bpeptone\b|bacto\s*peptone|bacteriological\s*peptone", re.I), "peptone"),
]


# reference supporting each ingredient's approximate compound-class composition
REFS = {
    "yeast_extract": "Yeast extract = autolysate of Saccharomyces cerevisiae: free amino acids (glutamate/alanine/aspartate-rich, essential AAs ~40% of total), B-vitamins (B1 thiamine, B2 riboflavin, B3 niacin, B5 pantothenate, B6 pyridoxine, B7 biotin, B9 folate, B12), RNA-derived 5'-nucleotides/nucleosides (~10-15%), and minerals (K, P, Mg, Zn, Mn). Quantitative composition: Tao Z et al., J Microbiol Biotechnol 2022;32:1236-1247, doi:10.4014/jmb.2207.07057 (PMC9998214); Podpora B et al., Czech J Food Sci 2016;34:554-563, doi:10.17221/419/2015-CJFS; Atlas RM, Handbook of Microbiological Media, doi:10.1201/EBK1439804063.",
    "tryptone": "Tryptone = pancreatic (tryptic) digest of casein; amino-acid-rich, tryptophan retained — BD Bionutrient Technical Manual; casein amino-acid profile (FAO/WHO).",
    "casein_peptone": "Tryptic/enzymatic digest of casein; amino-acid profile of casein — BD Bionutrient Technical Manual.",
    "trypticase": "Trypticase = pancreatic digest of casein (BBL) — BD Bionutrient Technical Manual.",
    "peptone": "Peptone = proteolytic digest of animal/plant protein; peptides + free amino acids — Atlas RM, Handbook of Microbiological Media (CRC Press).",
    "proteose_peptone": "Proteose peptone = enzymatic protein digest — BD Bionutrient Technical Manual.",
    "soytone": "Soytone = papaic digest of soybean meal (amino acids + carbohydrate) — BD Bionutrient Technical Manual.",
    "casamino_acids": "Casamino acids = ACID hydrolysate of casein — tryptophan destroyed by acid hydrolysis, cysteine low (Nolan & Smith 1962, J Biol Chem; BD Bionutrient Technical Manual).",
    "beef_extract": "Beef extract = aqueous meat extract; amino acids, nucleotides (creatine/creatinine), water-soluble vitamins and minerals — Atlas RM, Handbook of Microbiological Media.",
    "meat_extract": "Meat extract (Lab-Lemco) composition — Oxoid/BD technical data; Atlas RM, Handbook of Microbiological Media.",
    "lab_lemco": "Lab-Lemco meat extract — Oxoid technical data.",
    "malt_extract": "Malt extract = maltose-dominant sugars plus amino acids and B-vitamins — BD Bionutrient Technical Manual.",
}


def ingredient_key(name):
    name = (name or "").replace("_", " ")
    for rx, key in _PATTERNS:
        if rx.search(name):
            return key
    return None


def reference_for(name):
    key = ingredient_key(name)
    return REFS.get(key) if key else None


# authoritative, publicly-accessible links for each composition reference
_ATLAS = "https://doi.org/10.1201/EBK1439804063"   # Atlas RM, Handbook of Microbiological Media, CRC 4th ed.
_DIFCO = "https://archive.org/details/difcomanualdehyd0000unse"  # Difco/BD Manual (BD Bionutrient lineage)
_YEAST = "https://doi.org/10.4014/jmb.2207.07057"  # Tao et al. 2022, J Microbiol Biotechnol (open access, PMC9998214)
REF_LINKS = {
    "yeast_extract": _YEAST, "tryptone": _DIFCO, "casein_peptone": _DIFCO, "trypticase": _DIFCO,
    "peptone": _ATLAS, "proteose_peptone": _DIFCO, "soytone": _DIFCO, "casamino_acids": _DIFCO,
    "beef_extract": _ATLAS, "meat_extract": _ATLAS, "lab_lemco": _ATLAS, "malt_extract": _DIFCO,
}


def reference_link(name):
    """Return a public URL for the composition reference of a complex ingredient, else None."""
    key = ingredient_key(name)
    return REF_LINKS.get(key) if key else None


def decompose(name, valid=None):
    """Return (ingredient_key, [bigg_ids]) for a complex-ingredient name, else None.
    `valid` optional callable(bigg_id)->bool to filter to ids that exist."""
    key = ingredient_key(name)
    if not key:
        return None
    ids = COMPOSITION[key]
    if valid:
        ids = [b for b in ids if valid(b)]
    return (key, ids) if ids else None
