#!/usr/bin/env python3
"""
Expert curation of a few canonical laboratory media (MRS, LB, MacConkey) to their
full, correctly-bounded, cited formulations.

The auto-extraction / base-expansion left these missing the inorganic base, the
carbon source, and (for MRS) Mn2+ — which is load-bearing for lactic acid bacteria,
which accumulate mM Mn2+ in place of SOD (Archibald & Fridovich 1981). Here each
canonical medium is written out fully with sensible FBA bounds: a limiting carbon
source, unlimited mineral/salt ions, a moderate Mn2+ bound, and O2 set to the real
cultivation regime. Complex ingredients are decomposed (labelled approximations,
with references). Any paper-specific carbon source / supplement already captured on a
medium is preserved.

Run:  python3 tools/curate_wellknown_media.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")
sys.path.insert(0, HERE)
from map_metabolite import Mapper                     # noqa: E402
from complex_ingredients import decompose, REFS, ingredient_key  # noqa: E402
from enrich_coverage import recover                    # noqa: E402

MAP = Mapper(); DICT = MAP.dict
def valid(b): return b in DICT

# carbon sources / additives to PRESERVE if a medium already carries them (paper-specific)
CARBON = {"glc__D","lcts","malt","sucr","fru","gal","lac__L","lac__D","glyc","pyr",
          "cellb","tre","man","mnl","xyl__D","arab__L","rmn","fuc__L","rib__D","melib","raffin",
          "gam","acgam","etoh","glcn","cit","succ","meoh",
          # organic acids used as sole carbon/energy source on minimal media
          "ac","ppa","but","fum","mal__L","akg","glyclt","hxa","glx","2ddglcn","for"}
SUPPLEMENT = CARBON | {"cys__L","thm","btn","hemeD","pheme","4abz","ade","gua","ura","o2"}

REF_MRS = ("De Man JC, Rogosa M, Sharpe ME. A medium for the cultivation of lactobacilli. "
           "J Appl Bacteriol 1960;23(1):130-135. doi:10.1111/j.1365-2672.1960.tb00188.x. "
           "Mn2+ requirement of lactic acid bacteria: Archibald & Fridovich, J Bacteriol 1981;146(3):928-936.")
REF_LB = ("Bertani G. Studies on lysogenesis I. J Bacteriol 1951;62(3):293-300; "
          "Sambrook & Russell, Molecular Cloning (CSHL, 2001). LB (Lennox): tryptone 10, yeast extract 5, NaCl 5 g/L; no added sugar.")
REF_MAC = ("MacConkey A. Lactose-fermenting bacteria in faeces. J Hyg (Lond) 1905;5(3):333-379. "
           "Standard MacConkey agar: peptone, lactose 10 g/L, bile salts, NaCl, neutral red, crystal violet, agar.")

# canonical formulations: (complex_ingredients, defined [(bigg, lower_bound, role)], oxygen, ref, uncovered[])
def C(*ids): return list(ids)
MRS = {
    "complex": ["peptone", "beef extract", "yeast extract"],
    "defined": [("glc__D", -15.0, "carbon source (glucose 20 g/L, limiting)"),
                ("ocdcea", -1.0, "oleate (Tween-80 surfactant / membrane fatty acid)"),
                ("ac", -5.0, "acetate (Na-acetate 5 g/L, selective agent)"),
                ("cit", -1.0, "citrate (diammonium citrate)"),
                ("nh4", -10.0, "ammonium (diammonium citrate)"),
                ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate (K2HPO4)"),
                ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate (MgSO4/MnSO4)"),
                ("mn2", -1.0, "MANGANESE (MnSO4) — mM Mn is the LAB oxidative-stress defence"),
                ("na1", -1000.0, "Na (Na-acetate)"), ("cl", -1000.0, "chloride"),
                ("ca2", -1000.0, "Ca"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
    "oxygen": "anaerobic", "ref": REF_MRS,
    "note": "MRS cultivation is microaerophilic-to-anaerobic; LAB grow by fermentation, so O2 uptake is off by default.",
}
LB = {
    "complex": ["tryptone", "yeast extract"],
    "defined": [("na1", -1000.0, "Na (NaCl)"), ("cl", -1000.0, "chloride (NaCl)"),
                ("pi", -1000.0, "phosphate (from hydrolysates)"), ("so4", -1000.0, "sulfate"),
                ("nh4", -1000.0, "ammonium (from hydrolysates)"), ("k", -1000.0, "K"),
                ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"), ("fe2", -1000.0, "Fe"),
                ("mn2", -1000.0, "Mn"), ("zn2", -1000.0, "Zn"), ("cu2", -1000.0, "Cu"),
                ("h2o", -1000.0, ""), ("h", -1000.0, "")],
    "oxygen": "facultative", "ref": REF_LB,
    "note": "LB has NO added sugar; carbon and energy come from the amino acids/peptides of tryptone and yeast extract. Typically grown aerobically.",
}
MAC = {
    "complex": ["peptone"],
    "defined": [("lcts", -10.0, "lactose 10 g/L (differential carbon source)"),
                ("na1", -1000.0, "Na (NaCl)"), ("cl", -1000.0, "chloride (NaCl)"),
                ("pi", -1000.0, "phosphate"), ("so4", -1000.0, "sulfate"),
                ("nh4", -1000.0, "ammonium"), ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"),
                ("ca2", -1000.0, "Ca"), ("o2", -10.0, "aerobic"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
    "oxygen": "aerobic", "ref": REF_MAC,
    "uncovered": [("Bile salts", "selective agent (inhibits Gram-positives); not a defined metabolite exchange"),
                  ("Crystal violet", "selective dye; not a nutrient"),
                  ("Neutral red", "pH indicator dye; not a nutrient"),
                  ("Agar", "gelling agent; not a nutrient")],
}

# ---- the rest of the top-10 laboratory media ----
REF_M9 = ("M9 minimal medium — Sambrook J, Russell DW, Molecular Cloning: A Laboratory Manual, 3rd ed. "
          "CSHL Press 2001. Salts: Na2HPO4, KH2PO4, NaCl, NH4Cl; + 2 mM MgSO4, 0.1 mM CaCl2, ~0.2-0.4% carbon source (glucose).")
REF_TSB = ("Tryptic Soy Broth (Soybean-Casein Digest Medium) — BD Bionutrient Technical Manual; USP <62>. "
           "Casein peptone 17, soy peptone 3, NaCl 5, K2HPO4 2.5, dextrose 2.5 g/L.")
REF_BHI = ("Brain Heart Infusion — Rosenow EC, J Dent Res 1919; BD BHI formulation: brain/heart infusion solids, "
           "proteose peptone 10, NaCl 5, Na2HPO4 2.5, dextrose 2 g/L.")
REF_NB = ("Nutrient Broth — Atlas RM, Handbook of Microbiological Media (CRC Press). Peptone 5 g + meat/beef extract 3 g "
          "+ NaCl 5 g/L; no added sugar (carbon from the digest).")
REF_TB = ("Terrific Broth — Tartof KD, Hobbs CA, Bethesda Res Lab Focus 1987;9:12; Sambrook & Russell 2001. "
          "Tryptone 12, yeast extract 24 g/L, 0.4% glycerol, potassium phosphate buffer (KH2PO4 0.017 M, K2HPO4 0.072 M).")
REF_YT = ("2xYT — Sambrook & Russell, Molecular Cloning 2001; Miller 1972. Tryptone 16, yeast extract 10, NaCl 5 g/L; no added sugar.")
REF_SOB = ("SOB/SOC — Hanahan D, J Mol Biol 1983;166(4):557-580. SOB: tryptone 20, yeast extract 5, NaCl 0.5 g/L, "
           "2.5 mM KCl, 10 mM MgCl2, 10 mM MgSO4; SOC = SOB + 20 mM glucose.")
REF_MOPS = ("MOPS minimal medium — Neidhardt FC, Bloch PL, Smith DF, J Bacteriol 1974;119(3):736-747. "
            "40 mM MOPS + 4 mM tricine, K2HPO4, NH4Cl, K2SO4, MgCl2, CaCl2, FeSO4, NaCl, micronutrients, glucose.")

_MINBASE = [("pi", -1000.0, "phosphate"), ("so4", -1000.0, "sulfate"), ("nh4", -1000.0, "ammonium"),
            ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"),
            ("na1", -1000.0, "Na"), ("cl", -1000.0, "chloride"), ("h2o", -1000.0, ""), ("h", -1000.0, "")]
_TRACE = [("fe2", -1000.0, "Fe"), ("mn2", -1000.0, "Mn"), ("zn2", -1000.0, "Zn"),
          ("cu2", -1000.0, "Cu"), ("cobalt2", -1000.0, "Co"), ("mobd", -1000.0, "Mo"), ("ni2", -1000.0, "Ni")]

M9 = {"complex": [], "defined": _MINBASE + _TRACE + [("o2", -20.0, "aerobic")],
      "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_M9,
      "note": "M9 is a defined MINIMAL medium: salts + a single carbon source. Glucose is the default carbon; any carbon named on the medium is used instead."}
TSB = {"complex": ["casein peptone", "soytone"],
       "defined": [("glc__D", -10.0, "dextrose (carbon)"), ("na1", -1000.0, "Na (NaCl)"),
                   ("cl", -1000.0, "chloride"), ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate"),
                   ("so4", -1000.0, "sulfate"), ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"),
                   ("o2", -20.0, "aerobic"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
       "oxygen": "facultative", "ref": REF_TSB, "note": "General-purpose medium; casein + soy peptone + dextrose."}
BHI = {"complex": ["proteose_peptone", "beef extract"],
       "defined": [("glc__D", -10.0, "dextrose (carbon)")] + _MINBASE + [("o2", -20.0, "aerobic")],
       "oxygen": "facultative", "ref": REF_BHI, "note": "Rich medium for fastidious organisms; brain/heart infusion + peptone + dextrose."}
NB = {"complex": ["peptone", "beef extract"],
      "defined": _MINBASE + [("o2", -20.0, "aerobic")],
      "oxygen": "facultative", "ref": REF_NB, "note": "Classic general medium; peptone + meat extract + NaCl, no added sugar."}
TB = {"complex": ["tryptone", "yeast extract"],
      "defined": [("glyc", -10.0, "glycerol (carbon)"), ("k", -1000.0, "K (phosphate buffer)"),
                  ("pi", -1000.0, "phosphate (buffer, high)")] + _MINBASE[1:] + [("o2", -30.0, "aerobic, vigorous")],
      "oxygen": "aerobic", "ref": REF_TB, "note": "High-density E. coli medium; very rich (24 g/L yeast extract) with glycerol and strong phosphate buffer."}
YT2 = {"complex": ["tryptone", "yeast extract"],
       "defined": _MINBASE + [("o2", -20.0, "aerobic")],
       "oxygen": "facultative", "ref": REF_YT, "note": "Rich medium (phage/cloning); tryptone + yeast extract + NaCl, no added sugar."}
SOB = {"complex": ["tryptone", "yeast extract"],
       "defined": [("na1", -1000.0, "Na (NaCl)"), ("cl", -1000.0, "chloride"), ("k", -1000.0, "K (KCl)"),
                   ("mg2", -1000.0, "Mg (MgCl2/MgSO4)"), ("so4", -1000.0, "sulfate"), ("pi", -1000.0, "phosphate"),
                   ("nh4", -1000.0, "ammonium"), ("ca2", -1000.0, "Ca"), ("o2", -20.0, "aerobic"),
                   ("h2o", -1000.0, ""), ("h", -1000.0, "")],
       "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_SOB,
       "note": "Transformation-recovery medium; SOC = SOB + 20 mM glucose."}
MOPS = {"complex": [],
        "defined": [("mops", -1000.0, "MOPS buffer")] + _MINBASE + _TRACE + [("o2", -20.0, "aerobic")],
        "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_MOPS,
        "note": "Neidhardt MOPS-buffered defined minimal medium; glucose default carbon."}

# ---- second batch: 10 more well-known media ----
REF_7H9 = ("Middlebrook 7H9 broth — Middlebrook G, Cohn ML, Am J Public Health 1958; BD Middlebrook 7H9 "
           "formulation (defined salts + L-glutamate, ferric ammonium citrate, pyridoxine, biotin) + glycerol "
           "+ ADC/OADC enrichment (albumin-dextrose-catalase +/- oleic acid) + Tween-80. Mycobacterium spp.")
REF_MH = ("Mueller-Hinton — Mueller JH, Hinton J, Proc Soc Exp Biol Med 1941;48:330-333. Beef extract + acid "
          "hydrolysate of casein + soluble starch; the CLSI reference medium for antimicrobial susceptibility testing.")
REF_BG11 = ("BG-11 — Rippka R et al., J Gen Microbiol 1979;111:1-61; Stanier RY et al. 1971. Photoautotrophic "
            "cyanobacterial medium: NaNO3 (N), phosphate, Mg/Ca salts, ferric ammonium citrate, citrate, Na2CO3, trace "
            "metals; carbon = CO2/bicarbonate, energy = light (light not modelled as an exchange).")
REF_YPD = "YPD/YEPD — Sherman F, Methods Enzymol 2002;350:3-41. Yeast extract 10, peptone 20, dextrose 20 g/L. S. cerevisiae."
REF_SAB = "Sabouraud dextrose — Sabouraud R 1892; BD formulation. Peptone 10 g/L, dextrose 40 g/L, pH ~5.6. Fungi/yeasts."
REF_MAR = ("Marine Broth 2216 — ZoBell CE, J Mar Res 1941;4:42-75; BD Difco. Peptone 5, yeast extract 1, ferric citrate 0.1 g/L "
           "+ full sea-salt ion complement (NaCl, MgCl2, Na2SO4, CaCl2, KCl, NaHCO3 ...).")
REF_RCM = ("Reinforced Clostridial Medium — Hirsch A, Grinsted E, J Dairy Res 1954;21:101-110; Oxoid CM0149. "
           "Peptone, beef & yeast extract, glucose, soluble starch, NaCl, Na-acetate, L-cysteine-HCl (reductant). Anaerobes.")
REF_R2A = ("R2A — Reasoner DJ, Geldreich EE, Appl Environ Microbiol 1985;49:1-7. Low-nutrient medium (yeast extract, "
           "proteose peptone, casamino acids, dextrose, starch, Na-pyruvate, K2HPO4, MgSO4 — each ~0.5 g/L) for oligotrophic water bacteria.")
REF_M63 = "M63 minimal — Miller JH, Experiments in Molecular Genetics, CSHL 1972. KH2PO4, (NH4)2SO4, MgSO4, FeSO4, thiamine + carbon source."
REF_DAVIS = "Davis minimal — Davis BD, Mingioli ES, J Bacteriol 1950;60:17-28. K2HPO4/KH2PO4, (NH4)2SO4, Na-citrate, MgSO4 + glucose."

M7H9 = {"complex": [],
        "defined": [("nh4", -1000.0, "ammonium (NH4)2SO4"), ("so4", -1000.0, "sulfate"),
                    ("k", -1000.0, "K (KH2PO4)"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, "Na"),
                    ("cit", -1.0, "citrate"), ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"),
                    ("zn2", -1000.0, "Zn"), ("cu2", -1000.0, "Cu"), ("glu__L", -1.0, "L-glutamate"),
                    ("fe3", -1000.0, "ferric ammonium citrate"), ("pydxn", -1.0, "pyridoxine"),
                    ("btn", -1.0, "biotin"), ("glyc", -10.0, "glycerol (carbon)"),
                    ("ocdcea", -1.0, "oleic acid (OADC) / Tween-80"), ("glc__D", -2.0, "dextrose (ADC/OADC)"),
                    ("o2", -20.0, "aerobic (Mycobacterium is an obligate aerobe)"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
        "oxygen": "aerobic", "ref": REF_7H9, "note": "Defined mycobacterial medium; carbon = glycerol (+ dextrose from ADC); obligate aerobe."}
MH = {"complex": ["beef extract", "casamino acids"],
      "defined": [("strch1", -1.0, "soluble starch")] + _MINBASE + [("o2", -20.0, "aerobic")],
      "oxygen": "facultative", "ref": REF_MH, "note": "CLSI reference AST medium; beef extract + casein acid-hydrolysate + starch; carbon from amino acids/starch."}
BG11 = {"complex": [],
        "defined": [("no3", -10.0, "nitrate (NaNO3, N source)"), ("co2", -10.0, "CO2 (photoautotroph carbon)"),
                    ("hco3", -10.0, "bicarbonate (Na2CO3, inorganic carbon)"), ("na1", -1000.0, "Na"),
                    ("k", -1000.0, "K"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg"),
                    ("so4", -1000.0, "sulfate"), ("ca2", -1000.0, "Ca"), ("cl", -1000.0, "chloride"),
                    ("cit", -1.0, "citrate / ferric ammonium citrate"), ("fe3", -1000.0, "iron"),
                    ("nh4", -0.1, "trace ammonium (ferric ammonium citrate)")] + _TRACE + [("o2", -20.0, "photosynthetic (produces O2)"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
        "oxygen": "aerobic", "ref": REF_BG11, "note": "Photoautotrophic cyanobacterial medium: carbon = CO2/bicarbonate, N = nitrate, energy = light (not modelled)."}
YPD = {"complex": ["yeast extract", "peptone"],
       "defined": [("glc__D", -15.0, "dextrose (carbon)")] + _MINBASE + [("o2", -20.0, "aerobic")],
       "oxygen": "facultative", "ref": REF_YPD, "note": "Standard rich yeast medium; yeast extract + peptone + glucose."}
SAB = {"complex": ["peptone"],
       "defined": [("glc__D", -20.0, "dextrose (high, 40 g/L)")] + _MINBASE + [("o2", -20.0, "aerobic")],
       "oxygen": "aerobic", "ref": REF_SAB, "note": "Fungal medium; high dextrose, low pH."}
MAR = {"complex": ["peptone", "yeast extract"],
       "defined": [("na1", -1000.0, "Na (sea salt)"), ("cl", -1000.0, "chloride"), ("mg2", -1000.0, "Mg"),
                   ("so4", -1000.0, "sulfate"), ("ca2", -1000.0, "Ca"), ("k", -1000.0, "K"),
                   ("hco3", -1.0, "bicarbonate"), ("fe3", -1000.0, "ferric citrate"), ("cit", -1.0, "citrate"),
                   ("pi", -1000.0, "phosphate")] + _TRACE + [("o2", -20.0, "aerobic"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
       "oxygen": "facultative", "ref": REF_MAR, "note": "Marine medium; peptone + yeast extract + full sea-salt ion complement."}
RCM = {"complex": ["peptone", "beef extract", "yeast extract"],
       "defined": [("glc__D", -10.0, "glucose (carbon)"), ("strch1", -1.0, "soluble starch"),
                   ("ac", -3.0, "acetate (Na-acetate)"), ("cys__L", -1.0, "L-cysteine (reductant)")] + _MINBASE + [],
       "oxygen": "anaerobic", "ref": REF_RCM, "note": "Anaerobe/clostridial medium; cysteine reductant, no O2."}
R2A = {"complex": ["yeast extract", "proteose_peptone", "casamino_acids"],
       "defined": [("glc__D", -5.0, "dextrose (low)"), ("strch1", -1.0, "soluble starch"),
                   ("pyr", -1.0, "pyruvate (Na-pyruvate)"), ("k", -1000.0, "K (K2HPO4)"),
                   ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate")] + _MINBASE[2:] + [("o2", -20.0, "aerobic")],
       "oxygen": "facultative", "ref": REF_R2A, "note": "Low-nutrient medium for oligotrophic/environmental bacteria."}
M63 = {"complex": [],
       "defined": [("k", -1000.0, "K (KH2PO4)"), ("pi", -1000.0, "phosphate"), ("nh4", -1000.0, "ammonium ((NH4)2SO4)"),
                   ("so4", -1000.0, "sulfate"), ("fe2", -1000.0, "Fe (FeSO4)"), ("mg2", -1000.0, "Mg (MgSO4)"),
                   ("thm", -1.0, "thiamine"), ("na1", -1000.0, "Na"), ("cl", -1000.0, "chloride"),
                   ("h2o", -1000.0, ""), ("h", -1000.0, ""), ("o2", -20.0, "aerobic")],
       "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_M63, "note": "Defined minimal medium; carbon variable (glucose default)."}
DAVIS = {"complex": [],
         "defined": [("k", -1000.0, "K (K2HPO4/KH2PO4)"), ("pi", -1000.0, "phosphate"), ("nh4", -1000.0, "ammonium"),
                     ("so4", -1000.0, "sulfate"), ("na1", -1000.0, "Na (Na-citrate)"), ("cit", -1.0, "citrate"),
                     ("mg2", -1000.0, "Mg"), ("cl", -1000.0, "chloride"), ("ca2", -1000.0, "Ca"),
                     ("h2o", -1000.0, ""), ("h", -1000.0, ""), ("o2", -20.0, "aerobic")],
         "default_carbon": ("glc__D", -10.0), "oxygen": "facultative", "ref": REF_DAVIS, "note": "Defined minimal medium (Davis); carbon variable (glucose default)."}

# ---- third batch: 20 more well-known media ----
def _sel(*names):
    return [(n, "selective/differential agent (dye, bile, detergent, antibiotic, high salt or reductant) — not a metabolite exchange") for n in names]

WILKINS = {"complex": ["tryptone", "peptone", "yeast extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("arg__L", -1.0, "arginine"), ("pyr", -1.0, "pyruvate"),
              ("pheme", -0.01, "hemin (X factor)"), ("mqn8", -0.01, "menadione (vitamin K)")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Wilkins-Chalgren anaerobe broth — Wilkins TD, Chalgren S. Antimicrob Agents Chemother 1976;10:926-928.", "note": "General anaerobe susceptibility medium."}
THIO = {"complex": ["casein peptone", "yeast extract"],
  "defined": [("glc__D", -5.0, "dextrose"), ("cys__L", -1.0, "L-cystine")] + _MINBASE,
  "oxygen": "facultative", "ref": "Fluid Thioglycollate Medium — Brewer JH, JAMA 1940;115:598; USP <71>. Sodium thioglycollate + L-cystine reductants create an anaerobic gradient.",
  "note": "Reducing medium for aerotolerance testing / anaerobes; thioglycollate reductant.", "uncovered": _sel("Sodium thioglycollate", "Resazurin")}
COOKEDMEAT = {"complex": ["beef extract", "peptone", "yeast extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("cys__L", -1.0, "L-cysteine (reductant)"), ("pheme", -0.01, "hemin"),
              ("k", -1000.0, "K"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Cooked/Chopped Meat Medium — Robertson M, J Pathol Bacteriol 1916; Holdeman, Cato & Moore, VPI Anaerobe Laboratory Manual 1977.",
  "note": "Classic anaerobe medium with meat particles; cysteine reductant.", "uncovered": _sel("Resazurin")}
PYG = {"complex": ["peptone", "trypticase", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("cys__L", -1.0, "L-cysteine"), ("pheme", -0.01, "hemin"),
              ("mqn8", -0.01, "vitamin K"), ("hco3", -1.0, "bicarbonate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "PYG (Peptone-Yeast-Glucose) — Holdeman, Cato & Moore, VPI Anaerobe Laboratory Manual, 4th ed. 1977. Bacteroides/gut anaerobes.",
  "note": "Standard Bacteroides/gut-anaerobe medium.", "uncovered": _sel("Resazurin")}
GAM = {"complex": ["peptone", "soytone", "beef extract", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("strch1", -1.0, "soluble starch"), ("cys__L", -1.0, "L-cysteine"),
              ("arg__L", -1.0, "arginine"), ("trp__L", -1.0, "tryptophan")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Gifu Anaerobic Medium (GAM) — Nissui; Ueki A et al. Standard rich anaerobe/gut-microbiota medium.",
  "note": "Rich anaerobe/gut medium.", "uncovered": _sel("Sodium thioglycollate")}
SCHAEDLER = {"complex": ["casein peptone", "soytone", "yeast extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("cys__L", -1.0, "L-cystine"), ("pheme", -0.01, "hemin"), ("hco3", -1.0, "Tris/bicarbonate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Schaedler broth — Schaedler RW, Dubos R, Costello R. J Exp Med 1965;122:59-66. Gut anaerobes.", "note": "Gut-anaerobe medium."}
EMB = {"complex": ["peptone"],
  "defined": [("lcts", -10.0, "lactose (differential)"), ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Eosin Methylene Blue (Levine) agar — Levine M, J Bacteriol 1918;3:253; Holt-Harris & Teague 1916.",
  "note": "Differential medium for enteric Gram-negatives; eosin+methylene blue distinguish lactose fermenters.", "uncovered": _sel("Eosin Y", "Methylene blue")}
XLD = {"complex": ["yeast extract"],
  "defined": [("xyl__D", -5.0, "xylose"), ("lys__L", -1.0, "lysine"), ("lcts", -2.0, "lactose"), ("sucr", -2.0, "sucrose"),
              ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("tsul", -1.0, "thiosulfate (H2S indicator)"), ("fe3", -1000.0, "ferric ammonium citrate"),
              ("nh4", -1000.0, ""), ("cit", -1.0, "citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Xylose Lysine Deoxycholate (XLD) agar — Taylor WI. Am J Clin Pathol 1965;44:471. Salmonella/Shigella.",
  "note": "Selective/differential for Salmonella & Shigella.", "uncovered": _sel("Sodium deoxycholate (bile)", "Phenol red")}
HEKTOEN = {"complex": ["peptone", "yeast extract"],
  "defined": [("lcts", -5.0, "lactose"), ("sucr", -5.0, "sucrose"), ("salcn", -2.0, "salicin"),
              ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("tsul", -1.0, "thiosulfate"), ("fe3", -1000.0, "ferric ammonium citrate"), ("nh4", -1000.0, ""), ("cit", -1.0, "citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Hektoen Enteric agar — King S, Metzger WI. Appl Microbiol 1968;16:577. Enteric pathogens.",
  "note": "Selective/differential for enteric pathogens.", "uncovered": _sel("Bile salts", "Bromothymol blue", "Acid fuchsin")}
TCBS = {"complex": ["peptone", "yeast extract"],
  "defined": [("sucr", -10.0, "sucrose (differential carbon)"), ("cit", -1.0, "citrate"), ("tsul", -1.0, "thiosulfate"),
              ("na1", -1000.0, "high NaCl (marine/Vibrio)"), ("cl", -1000.0, ""), ("fe3", -1000.0, "ferric citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "TCBS (Thiosulfate-Citrate-Bile-Sucrose) agar — Kobayashi T et al. Jpn J Bacteriol 1963;18:387. Vibrio spp.",
  "note": "Selective/differential for Vibrio (sucrose fermentation).", "uncovered": _sel("Oxgall / sodium cholate (bile)", "Bromothymol blue", "Thymol blue")}
CETRIMIDE = {"complex": ["peptone"],
  "defined": [("glyc", -10.0, "glycerol (carbon)"), ("mg2", -1000.0, "Mg (MgCl2)"), ("cl", -1000.0, ""), ("k", -1000.0, "K (K2SO4)"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Cetrimide agar — Lowbury EJL, Collins AG. J Clin Pathol 1955;8:47; Brown & Lowbury 1965. Pseudomonas aeruginosa.",
  "note": "Selective for P. aeruginosa; cetrimide is a quaternary-ammonium selective agent.", "uncovered": _sel("Cetrimide (cetyltrimethylammonium bromide)")}
KINGSB = {"complex": ["proteose_peptone"],
  "defined": [("glyc", -10.0, "glycerol (carbon)"), ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "King's B medium — King EO, Ward MK, Raney DE. J Lab Clin Med 1954;44:301. Pseudomonas fluorescein/pigment.", "note": "Pseudomonas fluorescence medium."}
MSA = {"complex": ["peptone", "beef extract"],
  "defined": [("mnl", -10.0, "mannitol (differential carbon)"), ("na1", -1000.0, "high NaCl 7.5% (selective)"), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Mannitol Salt Agar (Chapman) — Chapman GH. J Bacteriol 1945;50:201. Staphylococci.",
  "note": "Selective (7.5% NaCl) + differential (mannitol) for staphylococci.", "uncovered": _sel("Phenol red")}
BAIRDPARKER = {"complex": ["tryptone", "beef extract", "yeast extract"],
  "defined": [("pyr", -5.0, "sodium pyruvate"), ("gly", -1.0, "glycine (selective)"), ("cl", -1000.0, "LiCl (selective)")] + _MINBASE,
  "oxygen": "facultative", "ref": "Baird-Parker agar — Baird-Parker AC. J Appl Bacteriol 1962;25:12. Staphylococcus aureus.",
  "note": "Selective/differential for S. aureus (egg-yolk tellurite reduction).", "uncovered": _sel("Potassium tellurite", "Lithium chloride", "Egg yolk emulsion")}
CHOCOLATE = {"complex": ["peptone", "beef extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("pheme", -0.05, "hemin (X factor, from lysed blood)"), ("nad", -0.05, "NAD (V factor, from lysed blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Chocolate agar — standard clinical medium (heated blood agar releasing X and V factors) for Haemophilus and Neisseria.", "note": "Fastidious-organism medium supplying hemin (X) and NAD (V)."}
COLUMBIA = {"complex": ["casein peptone", "peptone", "beef extract", "yeast extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("strch1", -1.0, "corn starch"), ("pheme", -0.02, "hemin (from blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Columbia blood agar base — Ellner PD et al. Am J Clin Pathol 1966;45:502; BD Columbia agar.", "note": "General-purpose enriched medium (with sheep blood)."}
M7H10 = {"complex": [],
  "defined": M7H9["defined"], "oxygen": "aerobic",
  "ref": "Middlebrook 7H10 agar — Cohn ML, Waggoner RF, McClatchy JK. Am Rev Respir Dis 1968;98:295; BD 7H10.",
  "note": "Mycobacterial agar (7H9 salts base + OADC + glycerol + malachite green selective).", "uncovered": _sel("Malachite green")}
PCA = {"complex": ["tryptone", "yeast extract"],
  "defined": [("glc__D", -2.0, "glucose (low)")] + _MINBASE + [("o2", -20.0, "aerobic")],
  "oxygen": "facultative", "ref": "Plate Count Agar (Standard Methods Agar) — APHA Standard Methods for the Examination of Water and Wastewater; Buchbinder et al. 1953.", "note": "Viable-count medium."}
ISP2 = {"complex": ["yeast extract", "malt_extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("malt", -5.0, "maltose (malt extract)")] + _MINBASE + [("o2", -20.0, "aerobic")],
  "oxygen": "aerobic", "ref": "ISP Medium 2 / Yeast-Malt (GYM) agar — Shirling EB, Gottlieb D. Int J Syst Bacteriol 1966;16:313. Streptomyces/actinomycetes.", "note": "Standard actinomycete medium."}
BUSHNELL = {"complex": [],
  "defined": [("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate"), ("ca2", -1000.0, "Ca (CaCl2)"), ("cl", -1000.0, ""),
              ("k", -1000.0, "K (phosphates)"), ("pi", -1000.0, "phosphate"), ("nh4", -1000.0, "ammonium (NH4NO3)"), ("no3", -1000.0, "nitrate (NH4NO3)"),
              ("fe3", -1000.0, "Fe (FeCl3)"), ("na1", -1000.0, ""), ("h2o", -1000.0, ""), ("h", -1000.0, ""), ("o2", -20.0, "aerobic")],
  "oxygen": "aerobic", "ref": "Bushnell-Haas medium — Bushnell LD, Haas HF. J Bacteriol 1941;41:653. Mineral medium for hydrocarbon degraders (carbon supplied by the substrate under test).",
  "note": "Mineral-salts medium; carbon = the added hydrocarbon/pollutant (no built-in carbon source)."}

# kind -> (spec, match regex, exclude regex or None, std_id, std_name)
REGISTRY = [
    ("Wilkins", WILKINS, r"wilkins.?chalgren|\bWCA\b", r"modified", "std_wilkins_chalgren", "Wilkins-Chalgren anaerobe broth (standard)"),
    ("Thioglycollate", THIO, r"thioglycollate|thioglycolate|\bFTM\b", r"modified", "std_thioglycollate", "Fluid Thioglycollate Medium (standard)"),
    ("CookedMeat", COOKEDMEAT, r"cooked meat|chopped meat|robertson", r"modified", "std_cooked_meat", "Cooked/Chopped Meat Medium (standard)"),
    ("PYG", PYG, r"\bPYG\b|peptone.?yeast.?glucose", r"modified", "std_pyg", "PYG medium (standard)"),
    ("GAM", GAM, r"\bGAM\b|gifu anaerobic", r"modified", "std_gam", "Gifu Anaerobic Medium (standard)"),
    ("Schaedler", SCHAEDLER, r"schaedler", r"modified", "std_schaedler", "Schaedler broth (standard)"),
    ("EMB", EMB, r"\bEMB\b|eosin methylene|levine.{0,6}agar", r"modified", "std_emb", "Eosin Methylene Blue agar (standard)"),
    ("XLD", XLD, r"\bXLD\b|xylose lysine", r"modified", "std_xld", "XLD agar (standard)"),
    ("Hektoen", HEKTOEN, r"hektoen", r"modified", "std_hektoen", "Hektoen Enteric agar (standard)"),
    ("TCBS", TCBS, r"\bTCBS\b|thiosulfate.?citrate", r"modified", "std_tcbs", "TCBS agar (standard)"),
    ("Cetrimide", CETRIMIDE, r"cetrimide", r"modified", "std_cetrimide", "Cetrimide agar (standard)"),
    ("KingsB", KINGSB, r"king'?s b\b|kings b\b", r"modified", "std_kings_b", "King's B medium (standard)"),
    ("MSA", MSA, r"mannitol salt|\bMSA\b|chapman", r"modified", "std_mannitol_salt", "Mannitol Salt Agar (standard)"),
    ("BairdParker", BAIRDPARKER, r"baird.?parker", r"modified", "std_baird_parker", "Baird-Parker agar (standard)"),
    ("Chocolate", CHOCOLATE, r"chocolate agar", r"modified", "std_chocolate_agar", "Chocolate agar (standard)"),
    ("Columbia", COLUMBIA, r"columbia", r"modified|derived", "std_columbia_blood", "Columbia blood agar (standard)"),
    ("Middlebrook7H10", M7H10, r"7H10|7H11", r"modified", "std_middlebrook_7h10", "Middlebrook 7H10 agar (standard)"),
    ("PCA", PCA, r"plate count agar|standard methods agar|\bPCA\b", r"modified", "std_plate_count_agar", "Plate Count Agar (standard)"),
    ("ISP2", ISP2, r"\bISP\b|yeast.?malt|\bGYM\b agar|\bYM\b agar", r"modified", "std_isp2_ym", "ISP Medium 2 / Yeast-Malt agar (standard)"),
    ("BushnellHaas", BUSHNELL, r"bushnell.?haas|\bBH\b medium|mineral salts.{0,10}hydrocarbon", r"modified", "std_bushnell_haas", "Bushnell-Haas mineral medium (standard)"),
    ("Middlebrook7H9", M7H9, r"7H9|middlebrook", r"without|derived", "std_middlebrook_7h9", "Middlebrook 7H9 broth (standard)"),
    ("MuellerHinton", MH, r"mueller.?hinton|\bMHB\b|\bMHA\b", r"modified|derived|lysed|blood", "std_mueller_hinton", "Mueller-Hinton broth (standard)"),
    ("BG11", BG11, r"BG-?11", r"modified|derived", "std_bg11", "BG-11 medium (standard, cyanobacteria)"),
    ("YPD", YPD, r"\bYPD\b|\bYEPD\b|yeast extract.{0,4}peptone.{0,4}dextrose", r"modified|derived|galactose|raffinose", "std_ypd", "YPD medium (standard)"),
    ("Sabouraud", SAB, r"sabouraud|\bSDA\b|\bSDB\b", r"modified|derived", "std_sabouraud_dextrose", "Sabouraud dextrose broth (standard)"),
    ("Marine2216", MAR, r"marine broth|\b2216\b|zobell", r"artificial|derived", "std_marine_broth_2216", "Marine Broth 2216 (standard, ZoBell)"),
    ("RCM", RCM, r"reinforced clostridial|\bRCM\b", r"modified|derived", "std_reinforced_clostridial", "Reinforced Clostridial Medium (standard)"),
    ("R2A", R2A, r"\bR2A\b", r"modified|derived", "std_r2a", "R2A medium (standard)"),
    ("M63", M63, r"\bM63\b", r"derived|modified", "std_m63_minimal", "M63 minimal medium (standard)"),
    ("Davis", DAVIS, r"davis (minimal|medium)", r"derived|modified", "std_davis_minimal", "Davis minimal medium (standard)"),
    ("MacConkey", MAC, r"macconkey|mac conkey", None, "std_macconkey_agar", "MacConkey agar (standard)"),
    ("MRS", MRS, r"\bMRS\b|de man|rogosa", None, "std_mrs_broth", "MRS broth (standard, De Man-Rogosa-Sharpe)"),
    ("TSB", TSB, r"tryptic soy|\bTSB\b|\bTSA\b|soybean.?casein", r"without|[- ]free\b|derived", "std_tsb", "Tryptic Soy Broth (standard)"),
    ("BHI", BHI, r"brain.?heart|\bBHIS?\b", r"without|[- ]free\b|limited|derived", "std_bhi", "Brain Heart Infusion (standard)"),
    ("Terrific", TB, r"terrific", None, "std_terrific_broth", "Terrific Broth (standard)"),
    ("SOB", SOB, r"\bSOB\b|\bSOC\b", r"halophil|modified", "std_sob_soc", "SOB / SOC (standard)"),
    ("2xYT", YT2, r"2\s*[x×]\s*yt", r"artificial|sea.?water|\bASW\b", "std_2xyt", "2xYT (standard)"),
    ("MOPS", MOPS, r"\bMOPS\b (minimal|defined)|minimal.{0,12}\bMOPS\b|\bMOPS\b minimal", r"ez\s*rich|rich defined", "std_mops_minimal", "MOPS minimal medium (standard, Neidhardt)"),
    ("Nutrient", NB, r"nutrient broth|nutrient agar", r"modified|dap-|granucult|derived", "std_nutrient_broth", "Nutrient Broth (standard)"),
    ("M9", M9, r"\bM9\b", r"derived|\bBee9\b|artificial|sea.?water|modified", "std_m9_minimal", "M9 minimal medium (standard)"),
    ("LB", LB, r"\bLB\b|\bLBv2\b|luria|lysogen|lennox|bertani", r"artificial|sea.?water|\bASW\b", "std_lb_broth", "LB broth (standard, Lennox)"),
]


def comp(bid, lb, role, method="wellknown_curation", conf="curated"):
    rec = DICT.get(bid, {})
    c = {"name": rec.get("name", bid), "bigg_metabolite": bid, "exchange": "EX_%s_e" % bid,
         "lower_bound": lb, "upper_bound": 1000.0, "concentration_mM": None,
         "xref": rec.get("xrefs", {}), "in_biggr": rec.get("in_biggr", False),
         "exchange_source": ("biggr" if rec.get("in_biggr") else "bigg"),
         "mapping_method": method, "mapping_confidence": conf}
    if role:
        c["role"] = role
    return c


def build(spec, keep_existing=None):
    comps = {}
    drefs = {}
    # complex ingredient decomposition (labelled approximations, with refs)
    for ing in spec["complex"]:
        d = decompose(ing, valid=valid)
        if d:
            drefs[ing] = REFS.get(ingredient_key(ing), "")
            for b in d[1]:
                comps.setdefault("EX_%s_e" % b, comp(b, -1.0, None, "complex_decomposition", "approximation"))
                comps["EX_%s_e" % b]["derived_from"] = ing
                if drefs[ing]:
                    comps["EX_%s_e" % b]["decomposition_ref"] = drefs[ing]
    # defined components (override decomposition where they overlap, e.g. explicit bounds)
    for bid, lb, role in spec["defined"]:
        if valid(bid):
            comps["EX_%s_e" % bid] = comp(bid, lb, role)
    # preserve any paper-specific supplement already on the medium
    for c in (keep_existing or []):
        b = c.get("bigg_metabolite"); ex = c.get("exchange")
        if b in SUPPLEMENT and ex not in comps:
            c2 = dict(c); c2["role"] = c.get("role", "paper-specific supplement")
            if b in CARBON and (c2.get("lower_bound", 0) or 0) > -5:
                c2["lower_bound"] = -10.0
            comps[ex] = c2
    return comps, drefs


_AMT = re.compile(r"\d[\d.]*\s*(?:g/l|mg/l|g|mm|mol/l|m|%|w/v|v/v|µm|um|nm|mg)\b", re.I)
_STOP = re.compile(r"\b(total|feed|feeding|final|broth|medium|agar|control|supplement|supplemented|with|and)\b", re.I)
def name_supplements(name):
    """Map any '+ <compound>' additions named in the medium title to components."""
    out = {}
    for seg in re.split(r"\s*\+\s*", name or "")[1:]:
        seg = re.sub(r"\([^)]*\)", "", seg)
        seg = _AMT.sub("", seg); seg = _STOP.sub("", seg).strip(" ,.-")
        if len(seg) < 2:
            continue
        r = recover(seg, {})
        for c in (r if isinstance(r, list) else ([r] if r else [])):
            b = c.get("bigg_metabolite")
            if b in CARBON and (c.get("lower_bound", 0) or 0) > -5:
                c["lower_bound"] = -10.0
            c["role"] = "supplement (from medium name: '%s')" % seg
            out.setdefault(c["exchange"], c)
    return out


def curate(d, spec, kind):
    comps, drefs = build(spec, d.get("components", []))
    # add supplements named in the title (e.g. "+ 40 g/L sodium formate")
    for ex, c in name_supplements(d.get("name", "")).items():
        comps.setdefault(ex, c)
    # default carbon source only if the medium has none (minimal media)
    if spec.get("default_carbon"):
        if not any((c.get("bigg_metabolite") in CARBON) for c in comps.values()):
            b, lbnd = spec["default_carbon"]
            if valid(b):
                comps["EX_%s_e" % b] = comp(b, lbnd, "default carbon source (glucose)")
    if spec["oxygen"] == "anaerobic":
        comps.pop("EX_o2_e", None)
    d["components"] = sorted(comps.values(), key=lambda c: c["exchange"])
    d["oxygen"] = spec["oxygen"]; d["aerobic"] = (spec["oxygen"] != "anaerobic")
    d["oxygen_note"] = spec.get("note", "")
    d["base_medium"] = kind
    d["n_components"] = len(d["components"])
    d["n_mapped"] = len(d["components"])
    d["n_in_biggr"] = sum(1 for c in d["components"] if c.get("in_biggr"))
    # uncovered: keep MacConkey selective agents, else clear
    if spec.get("uncovered"):
        d["uncovered"] = [{"name": n, "reason": "non_nutrient", "curation": "no_exchange",
                           "xref": {}, "note": why} for n, why in spec["uncovered"]]
    prov = d.setdefault("provenance", {})
    prov["verification"] = "expert-curated (canonical formulation)"
    prov["wellknown_reference"] = spec["ref"]
    prov.pop("formulation_warning", None)
    if drefs:
        prov["decomposition_refs"] = {k: v for k, v in drefs.items() if v}
    return d


def match(nm):
    """Return the first REGISTRY entry whose pattern matches and exclude does not."""
    for kind, spec, pat, excl, sid, sname in REGISTRY:
        if re.search(pat, nm, re.I) and not (excl and re.search(excl, nm, re.I)):
            return kind, spec, pat, excl, sid, sname
    return None


def main():
    dry = "--dry" in sys.argv
    from collections import Counter
    n = Counter(); skipped = Counter()
    # 1) curate matching plain-standard media (skip already-expert-curated + excluded)
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f)); nm = d.get("name") or ""
        ver = (d.get("provenance") or {}).get("verification", "")
        # never overwrite an expert-curated or paper-verified medium.
        if ver.startswith("expert-curated") or ver.startswith("paper-verified"):
            continue
        # skip database-sourced recipes (DSMZ MediaDive / USDA / FooDB / HMDB) — those
        # are real published recipes, not ours to replace with a generic canonical.
        if d["id"].startswith(("mediadive_", "usda_", "food_", "biospecimen_")):
            continue
        m = match(nm)
        if not m:
            # count near-misses that were excluded, for reporting
            for kind, spec, pat, excl, sid, sname in REGISTRY:
                if re.search(pat, nm, re.I) and excl and re.search(excl, nm, re.I):
                    skipped[kind] += 1; break
            continue
        kind, spec = m[0], m[1]
        curate(d, spec, kind); n[kind] += 1
        if not dry:
            with open(f, "w") as fh:
                json.dump(d, fh, ensure_ascii=False)
    # 2) ensure a clean canonical std_ record exists for every registry medium
    created = []
    for kind, spec, pat, excl, sid, sname in REGISTRY:
        path = os.path.join(MEDIA, sid + ".json")
        if os.path.exists(path):
            # refresh the existing std record to the current spec
            rec = json.load(open(path))
        else:
            rec = {"id": sid, "name": sname, "category": "laboratory",
                   "organism_scope": "general laboratory", "aerobic": True, "namespace": "bigg",
                   "description": "%s — canonical reference formulation." % sname,
                   "provenance": {"source_type": "standard", "citation": spec["ref"], "doi": "", "url": ""}}
            created.append(sid)
        rec["name"] = sname
        rec.setdefault("description", "%s — canonical reference formulation." % sname)
        rec["provenance"]["citation"] = spec["ref"]
        curate(rec, spec, kind)
        if not dry:
            json.dump(rec, open(path, "w"), ensure_ascii=False)
    print("curated media by kind:", dict(n))
    print("excluded (left as paper-verified):", dict(skipped))
    print("std canonical records created:", created)


if __name__ == "__main__":
    main()
