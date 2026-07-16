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
    "beef_extract":    AA20 + BVIT + NUC + MIN + ["creat"],   # + creatine (muscle marker)
    "meat_extract":    AA20 + BVIT + NUC + MIN + ["creat"],
    "lab_lemco":       AA20 + BVIT + NUC + MIN + ["creat"],
    "malt_extract":    SUG_MALT + ["sucr", "fru"] + AA20 + ["nac", "ribflv"],  # sugar-dominant
}

# name -> ingredient key (order matters: more specific first)
_PATTERNS = [
    (re.compile(r"casamino", re.I), "casamino_acids"),
    (re.compile(r"casein\s*(peptone|hydrolysate|digest)|tryptic\s*digest\s*of\s*casein|casitone", re.I), "casein_peptone"),
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
    "yeast_extract": "Yeast extract = autolysate of Saccharomyces cerevisiae. Component amounts here are QUANTITATIVE (mg per g yeast extract), from Tao Z et al., J Microbiol Biotechnol 2022;32:1236-1247, Table 2 (doi:10.4014/jmb.2207.07057, PMC9998214): free amino acids ~35% w/w with the measured pattern (Ala/Glu/Asp/Leu/Arg/Lys dominant; Cys/Met/Trp minor), B-vitamins (niacin >> pyridoxine/pantothenate > thiamine > riboflavin/folate/B12; biotin trace), ~10% RNA-derived nucleosides, and minerals (K/P-rich). Corroborated by Podpora B et al., Czech J Food Sci 2016;34:554-563, doi:10.17221/419/2015-CJFS; Atlas RM, Handbook of Microbiological Media, doi:10.1201/EBK1439804063. Per-component lower bounds are scaled to molar abundance (mg/g ÷ molecular weight).",
    "tryptone": "Tryptone = pancreatic (tryptic) digest of casein; tryptophan retained. QUANTITATIVE amino-acid composition (mg/g) from casein: Glu/Pro/Leu-dominant — FAO Amino-acid Content of Foods (1970); Rafiq S et al., Asian-Australas J Anim Sci 2016;29:1022, doi:10.5713/ajas.15.0452; BD Bionutrient Technical Manual.",
    "casein_peptone": "Casein peptone = enzymatic digest of casein. QUANTITATIVE amino-acid composition (mg/g): Glu/Pro/Leu-dominant — FAO (1970); Rafiq S et al., Asian-Australas J Anim Sci 2016;29:1022, doi:10.5713/ajas.15.0452; BD Bionutrient Technical Manual.",
    "trypticase": "Trypticase = pancreatic digest of casein (BBL). QUANTITATIVE casein amino-acid composition (mg/g): Glu/Pro/Leu-dominant — Rafiq S et al., Asian-Australas J Anim Sci 2016;29:1022, doi:10.5713/ajas.15.0452; BD Bionutrient Technical Manual.",
    "peptone": "Peptone = enzymatic digest of animal protein/gelatin. QUANTITATIVE amino-acid composition (mg/g) — gelatin/collagen signature: glycine/proline-dominant, tryptophan/cysteine near-zero (intrinsic to collagen). BD Bionutrient Technical Manual; GRiSP bacteriological peptone data sheet.",
    "proteose_peptone": "Proteose peptone = enzymatic protein digest. QUANTITATIVE amino-acid composition (mg/g), gelatin/animal signature (glycine/proline-dominant) — BD Bionutrient Technical Manual.",
    "soytone": "Soytone = papaic digest of soybean meal. QUANTITATIVE amino-acid composition (mg/g): glutamate/aspartate-rich soy-protein profile — BD/US Biological Soytone data sheet; soy protein amino-acid literature.",
    "casamino_acids": "Casamino acids = ACID hydrolysate of casein — tryptophan destroyed, cysteine very low. QUANTITATIVE casein amino-acid composition (mg/g, Trp=0): Glu/Pro/Leu-dominant — Rafiq S et al. 2016, doi:10.5713/ajas.15.0452; BD/Difco Casamino Acids table.",
    "beef_extract": "Beef extract = aqueous meat extract. QUANTITATIVE composition (mg/g): muscle-protein amino acids (Glu/Leu-rich), creatine, K/Na — BBL Beef Extract analysis (BD Bionutrient Technical Manual); Jarboe JK, Mabrouk AF, J Agric Food Chem 1974;22:787, doi:10.1021/jf60195a038.",
    "meat_extract": "Meat extract (Lab-Lemco) = aqueous meat extract. QUANTITATIVE composition (mg/g): muscle-protein amino acids, creatine, K/Na — BD Bionutrient Technical Manual; Jarboe & Mabrouk, J Agric Food Chem 1974, doi:10.1021/jf60195a038.",
    "lab_lemco": "Lab-Lemco meat extract. QUANTITATIVE composition (mg/g): muscle amino acids, creatine, K/Na — Jarboe & Mabrouk 1974, doi:10.1021/jf60195a038; Oxoid/BD technical data.",
    "malt_extract": "Malt extract = carbohydrate-dominant (~90% sugars). QUANTITATIVE composition (mg/g): maltose (~52%) > glucose > maltotriose (Cote GL 1999; BD Bionutrient Technical Manual); minor proline-dominant free amino acids from wort — Fermentation 2018;4:23, doi:10.3390/fermentation4020023.",
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
_CASEIN = "https://doi.org/10.5713/ajas.15.0452"    # Rafiq et al. 2016 (casein amino-acid composition)
_MEAT = "https://doi.org/10.1021/jf60195a038"       # Jarboe & Mabrouk 1974 (beef-extract free amino acids)
_MALT = "https://doi.org/10.3390/fermentation4020023"  # wort free amino acids 2018 (open access)
REF_LINKS = {
    "yeast_extract": _YEAST, "tryptone": _CASEIN, "casein_peptone": _CASEIN, "trypticase": _CASEIN,
    "peptone": _DIFCO, "proteose_peptone": _DIFCO, "soytone": _DIFCO, "casamino_acids": _CASEIN,
    "beef_extract": _MEAT, "meat_extract": _MEAT, "lab_lemco": _MEAT, "malt_extract": _MALT,
}


def reference_link(name):
    """Return a public URL for the composition reference of a complex ingredient, else None."""
    key = ingredient_key(name)
    return REF_LINKS.get(key) if key else None


# ---- QUANTITATIVE yeast-extract composition (mg per gram of yeast extract) ----
# Grounded in Tao et al., J Microbiol Biotechnol 2022 (doi:10.4014/jmb.2207.07057),
# Table 2. Free amino acids: the reported per-product ranges are wide, so each amino
# acid's midpoint sets its RELATIVE proportion and the set is scaled to a realistic
# total free-amino-acid fraction (~35% w/w) — this preserves the measured pattern
# (Ala/Glu/Asp/Leu/Arg/Lys dominant; Cys/Met/Trp minor) without over-reading the
# high end of each range. Vitamins/minerals: Table 2 midpoints (biotin corrected to
# the µg-scale — the table's "mg/100g" is biologically implausible for biotin).
# Nucleosides: from the ~10% RNA content (individual 5'-nucleotides not tabulated),
# split across the ribonucleosides. Trp/Asn/Gln are not in Table 2 — small literature
# estimates, flagged. These are representative values, not a single product's assay.
YEAST_MG_PER_G = {
    # free amino acids (mg/g), Tao 2022 Table 2 pattern scaled to ~350 mg/g total
    "ala__L": 63.8, "arg__L": 29.6, "asp__L": 27.3, "cys__L": 1.5, "glu__L": 37.9,
    "gly": 12.3, "his__L": 16.4, "ile__L": 15.5, "leu__L": 25.3, "lys__L": 22.4,
    "met__L": 6.3, "phe__L": 16.7, "pro__L": 13.4, "ser__L": 15.7, "thr__L": 13.5,
    "tyr__L": 12.0, "val__L": 20.4, "trp__L": 3.0, "asn__L": 5.0, "gln__L": 5.0,
    # B-vitamins (mg/g), Tao 2022 Table 2 midpoints
    "thm": 0.10, "ribflv": 0.012, "nac": 3.33, "pnto__R": 0.124, "pydxn": 0.291,
    "btn": 0.0012, "fol": 0.032, "cbl1": 0.002, "4abz": 0.02,
    # minerals (mg/g of the element), Tao 2022 Table 2 midpoints
    "k": 50.0, "pi": 16.8, "na1": 6.8, "mg2": 3.6, "ca2": 0.14, "zn2": 0.14,
    "mn2": 0.083, "cu2": 0.003, "fe2": 0.10, "so4": 2.0, "cobalt2": 0.002,
    # ribonucleosides (mg/g) from ~10% RNA
    "adn": 16.0, "gsn": 16.0, "cytd": 14.0, "uri": 14.0, "ins": 8.0, "thymd": 2.0,
}
# elemental exchanges keep the mineral (non-limiting) bound; the rest are molar-weighted
MINERAL_IDS = {"k", "pi", "na1", "mg2", "ca2", "zn2", "mn2", "cu2", "fe2", "so4", "cobalt2"}
YEAST_MINERAL_IDS = MINERAL_IDS   # back-compat alias

# ---- QUANTITATIVE composition (mg per gram) for the other complex ingredients ----
# From dedicated composition research (amino acids g/100g or % of total AA; sugars g/100g;
# vitamins/minerals mg/100g), all converted to mg/g. Per-component lower bounds are scaled
# to molar abundance downstream, so relative proportions are what matter.
#   casein digests (tryptone/casein peptone/trypticase): FAO amino-acid data + Rafiq et al.
#     2016 (doi:10.5713/ajas.15.0452) + BD/Difco Casamino Acids table. Glu/Pro/Leu-rich.
#   casamino acids: casein profile, Trp destroyed by acid hydrolysis, cysteine very low.
#   peptone/proteose peptone: gelatin/animal enzymatic digest (GRiSP data sheet; BD manual) —
#     glycine/proline-dominant, near-zero Trp/Cys (intrinsic to collagen).
#   soytone: papaic digest of soybean meal (BD/USBio spec) — Glu/Asp-rich.
#   beef/meat extract / Lab-Lemco: BBL Beef Extract analysis (BD manual) + Jarboe & Mabrouk,
#     J Agric Food Chem 1974 (doi:10.1021/jf60195a038) — muscle-protein AAs (% of total AA),
#     creatine, K, Na. Nucleotides/vitamins qualitative -> left presence-based.
#   malt extract: sugar-dominant (maltose/glucose/maltotriose; Cote 1999, BD manual);
#     free amino acids from all-malt wort (Fermentation 2018, doi:10.3390/fermentation4020023),
#     proline-dominant; niacin/riboflavin.
COMPOSITION_MG_PER_G = {"yeast_extract": YEAST_MG_PER_G,
    "tryptone": {"glu__L": 221.0, "pro__L": 108.0, "leu__L": 93.0, "lys__L": 72.0, "asp__L": 70.0, "val__L": 62.0, "ser__L": 56.0, "tyr__L": 50.0, "phe__L": 49.0, "ile__L": 46.0, "thr__L": 37.0, "ala__L": 32.0, "arg__L": 29.0, "his__L": 25.0, "trp__L": 19.0, "gly": 19.0, "met__L": 16.0, "cys__L": 14.0},
    "casein_peptone": {"glu__L": 221.0, "pro__L": 108.0, "leu__L": 93.0, "lys__L": 72.0, "asp__L": 70.0, "val__L": 62.0, "ser__L": 56.0, "tyr__L": 50.0, "phe__L": 49.0, "ile__L": 46.0, "thr__L": 37.0, "ala__L": 32.0, "arg__L": 29.0, "his__L": 25.0, "trp__L": 19.0, "gly": 19.0, "met__L": 16.0, "cys__L": 14.0},
    "trypticase": {"glu__L": 221.0, "pro__L": 108.0, "leu__L": 93.0, "lys__L": 72.0, "asp__L": 70.0, "val__L": 62.0, "ser__L": 56.0, "tyr__L": 50.0, "phe__L": 49.0, "ile__L": 46.0, "thr__L": 37.0, "ala__L": 32.0, "arg__L": 29.0, "his__L": 25.0, "trp__L": 19.0, "gly": 19.0, "met__L": 16.0, "cys__L": 14.0},
    "casamino_acids": {"glu__L": 221.0, "pro__L": 108.0, "leu__L": 93.0, "lys__L": 72.0, "asp__L": 70.0, "val__L": 62.0, "ser__L": 56.0, "tyr__L": 50.0, "phe__L": 49.0, "ile__L": 46.0, "thr__L": 37.0, "ala__L": 32.0, "arg__L": 29.0, "his__L": 25.0, "gly": 19.0, "met__L": 16.0, "cys__L": 3.0},
    "peptone": {"gly": 207.1, "pro__L": 117.1, "glu__L": 99.3, "ala__L": 79.5, "arg__L": 72.1, "asp__L": 64.2, "lys__L": 36.9, "ser__L": 35.1, "leu__L": 30.2, "val__L": 24.0, "phe__L": 19.4, "thr__L": 19.0, "ile__L": 14.1, "his__L": 9.3, "met__L": 9.2, "tyr__L": 7.5, "cys__L": 1.4, "trp__L": 0.9},
    "proteose_peptone": {"gly": 207.1, "pro__L": 117.1, "glu__L": 99.3, "ala__L": 79.5, "arg__L": 72.1, "asp__L": 64.2, "lys__L": 36.9, "ser__L": 35.1, "leu__L": 30.2, "val__L": 24.0, "phe__L": 19.4, "thr__L": 19.0, "ile__L": 14.1, "his__L": 9.3, "met__L": 9.2, "tyr__L": 7.5, "cys__L": 1.4, "trp__L": 0.9},
    "soytone": {"glu__L": 118.3, "asp__L": 90.0, "leu__L": 39.0, "lys__L": 38.5, "ala__L": 31.8, "arg__L": 30.5, "val__L": 29.4, "ser__L": 26.9, "thr__L": 26.1, "ile__L": 25.5, "pro__L": 25.4, "gly": 24.7, "phe__L": 24.0, "tyr__L": 13.8, "his__L": 12.3, "met__L": 8.6, "cys__L": 7.9, "trp__L": 6.8},
    "beef_extract": {"glu__L": 146.0, "leu__L": 72.0, "lys__L": 57.0, "pro__L": 57.0, "asp__L": 55.0, "val__L": 54.0, "ile__L": 51.0, "phe__L": 50.0, "creat": 36.0, "k": 28.8, "gly": 23.0, "his__L": 21.0, "ser__L": 21.0, "na1": 18.5, "thr__L": 18.0, "met__L": 16.0, "tyr__L": 15.0},
    "meat_extract": {"glu__L": 146.0, "leu__L": 72.0, "lys__L": 57.0, "pro__L": 57.0, "asp__L": 55.0, "val__L": 54.0, "ile__L": 51.0, "phe__L": 50.0, "creat": 36.0, "k": 28.8, "gly": 23.0, "his__L": 21.0, "ser__L": 21.0, "na1": 18.5, "thr__L": 18.0, "met__L": 16.0, "tyr__L": 15.0},
    "lab_lemco": {"glu__L": 146.0, "leu__L": 72.0, "lys__L": 57.0, "pro__L": 57.0, "asp__L": 55.0, "val__L": 54.0, "ile__L": 51.0, "phe__L": 50.0, "creat": 36.0, "k": 28.8, "gly": 23.0, "his__L": 21.0, "ser__L": 21.0, "na1": 18.5, "thr__L": 18.0, "met__L": 16.0, "tyr__L": 15.0},
    "malt_extract": {"malt": 520.0, "glc__D": 190.0, "malttr": 150.0, "sucr": 15.0, "fru": 15.0, "pro__L": 4.7, "leu__L": 2.4, "arg__L": 1.9, "phe__L": 1.8, "tyr__L": 1.7, "val__L": 1.7, "lys__L": 1.6, "ala__L": 1.6, "asn__L": 1.3, "ile__L": 1.0, "ser__L": 0.9, "asp__L": 0.8, "glu__L": 0.7, "his__L": 0.6, "gly": 0.5, "trp__L": 0.5, "met__L": 0.4, "gln__L": 0.3, "nac": 0.025, "ribflv": 0.003},
}


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
