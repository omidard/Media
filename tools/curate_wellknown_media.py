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

# ---- sixth batch: 50 more well-known media ----
# nitrogen-free mineral scaffold for diazotrophs (N2-fixers): NO ammonium/nitrate
_NFREE = [("pi", -1000.0, "phosphate"), ("so4", -1000.0, "sulfate"), ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"),
          ("ca2", -1000.0, "Ca"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("fe2", -1000.0, "Fe"),
          ("mobd", -1000.0, "molybdate (nitrogenase Fe-Mo cofactor)"), ("n2", -1000.0, "atmospheric N2 (SOLE N — diazotroph)"),
          ("h2o", -1000.0, ""), ("h", -1000.0, "")]
# photoautotroph scaffold: N from nitrate, carbon from CO2/bicarbonate, no organic C, no ammonium
def _photo(na="", extra=None):
    base = [("no3", -10.0, "nitrate (N source)"), ("hco3", -10.0, "bicarbonate/CO2 (SOLE carbon — photoautotroph)"),
            ("pi", -1000.0, "phosphate"), ("so4", -1000.0, "sulfate"), ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"),
            ("ca2", -1000.0, "Ca"), ("na1", -1000.0, na or "Na"), ("cl", -1000.0, ""), ("fe3", -1000.0, "Fe"),
            ("btn", -1.0, "biotin"), ("cbl1", -1.0, "vitamin B12"), ("thm", -1.0, "thiamine"),
            ("h2o", -1000.0, ""), ("h", -1000.0, "")] + _TRACE
    return base + (extra or [])
# Listeria / food pathogen selective
PALCAM = {"complex": ["peptone", "yeast extract"],
  "defined": [("mnl", -10.0, "mannitol (differential)"), ("glc__D", -5.0, "glucose"), ("escul", -5.0, "esculin"), ("fe3", -1000.0, "ferric ammonium citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "PALCAM agar — van Netten P et al. Int J Food Microbiol 1989;8:299. Listeria monocytogenes.",
  "note": "Selective/differential for Listeria (esculin hydrolysis, mannitol non-fermentation).", "uncovered": _sel("Polymyxin B", "Acriflavine", "Ceftazidime", "Lithium chloride", "Phenol red")}
OXFORDL = {"complex": ["casein peptone", "soytone", "beef extract", "yeast extract"],
  "defined": [("escul", -5.0, "esculin"), ("fe3", -1000.0, "ferric ammonium citrate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Oxford agar — Curtis GDW et al. Lett Appl Microbiol 1989;8:95. Listeria monocytogenes.",
  "note": "Selective/differential for Listeria (esculin, aesculin black halo).", "uncovered": _sel("Lithium chloride", "Acriflavine", "Colistin", "Cefotetan", "Cycloheximide", "Fosfomycin")}
FRASER = {"complex": ["casein peptone", "soytone", "beef extract", "yeast extract"],
  "defined": [("escul", -5.0, "esculin"), ("fe3", -1000.0, "ferric ammonium citrate"), ("na1", -1000.0, "high NaCl"), ("cl", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Fraser broth — Fraser JA, Sperber WH. J Food Prot 1988;51:762. Listeria enrichment.",
  "note": "Selective enrichment broth for Listeria (esculin blackening).", "uncovered": _sel("Lithium chloride", "Nalidixic acid", "Acriflavine")}
BPW = {"complex": ["peptone"],
  "defined": [("na1", -1000.0, "NaCl"), ("cl", -1000.0, ""), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "Na2HPO4/KH2PO4 (buffer)")] + _MINBASE,
  "oxygen": "facultative", "ref": "Buffered Peptone Water (BPW) — ISO 6579. Non-selective pre-enrichment (Salmonella).",
  "note": "Non-selective resuscitation/pre-enrichment broth; carbon from peptone."}
EEBROTH = {"complex": ["peptone"],
  "defined": [("glc__D", -10.0, "glucose"), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Enterobacteriaceae Enrichment (EE) broth — Mossel DAA et al. J Appl Bacteriol 1963;26:444.",
  "note": "Selective enrichment for Enterobacteriaceae.", "uncovered": _sel("Ox bile", "Brilliant green")}
VRBGA = {"complex": ["peptone", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Violet Red Bile Glucose Agar (VRBGA) — Mossel DAA. Enterobacteriaceae enumeration.",
  "note": "Selective/differential for Enterobacteriaceae (glucose fermentation).", "uncovered": _sel("Bile salts", "Neutral red", "Crystal violet")}
# Staph / Strep / Enterococcus
VOGELJOHNSON = {"complex": ["casein peptone", "yeast extract"],
  "defined": [("mnl", -10.0, "mannitol (differential)"), ("glc__D", -2.0, "glucose"), ("k", -1000.0, "K2HPO4"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Vogel-Johnson agar — Vogel RA, Johnson M. Public Health Lab 1960;18:131. Staphylococcus aureus.",
  "note": "Selective/differential for S. aureus (mannitol + tellurite reduction).", "uncovered": _sel("Lithium chloride", "Glycine", "Potassium tellurite", "Phenol red")}
EDWARDS = {"complex": ["peptone", "beef extract"],
  "defined": [("escul", -5.0, "esculin"), ("pheme", -0.05, "hemin (sheep blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Edwards medium — Edwards SJ. J Comp Pathol 1933;46:211. Streptococci (bovine mastitis).",
  "note": "Selective/differential for streptococci (esculin, aesculin).", "uncovered": _sel("Crystal violet", "Thallous sulfate", "Defibrinated sheep blood")}
KAA = {"complex": ["tryptone", "yeast extract"],
  "defined": [("escul", -5.0, "esculin"), ("fe3", -1000.0, "ferric ammonium citrate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Kanamycin Aesculin Azide (KAA) agar — Mossel DAA et al. J Appl Bacteriol 1978;45:381. Enterococci.",
  "note": "Selective/differential for enterococci (esculin hydrolysis).", "uncovered": _sel("Sodium azide", "Kanamycin")}
AZIDEDEX = {"complex": ["beef extract", "tryptone"],
  "defined": [("glc__D", -10.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Azide Dextrose broth (Rothe) — Mallmann WL, Seligmann EB. Am J Public Health 1930;20:499.",
  "note": "Presumptive enrichment for faecal streptococci/enterococci.", "uncovered": _sel("Sodium azide")}
BEAAZIDE = {"complex": ["casein peptone", "yeast extract"],
  "defined": [("escul", -5.0, "esculin"), ("fe3", -1000.0, "ferric ammonium citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Bile Esculin Azide agar (Enterococcosel) — Isenberg HD et al. Appl Microbiol 1970;20:433. Enterococci.",
  "note": "Selective/differential for enterococci (bile + azide + esculin).", "uncovered": _sel("Oxgall (bile)", "Sodium azide")}
GRANADA = {"complex": ["proteose peptone", "casein peptone"],
  "defined": [("strch1", -5.0, "starch"), ("pyr", -1.0, "sodium pyruvate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Granada medium — de la Rosa M et al. J Clin Microbiol 1992;30:1019. Group B Streptococcus (orange pigment).",
  "note": "Differential for GBS (orange carotenoid pigment).", "uncovered": _sel("Serum", "Methotrexate", "Colistin", "Metronidazole")}
# enteric enrichment / differential
GNBROTH = {"complex": ["casein peptone", "peptone"],
  "defined": [("glc__D", -1.0, "glucose (low)"), ("mnl", -10.0, "mannitol (high)"), ("cit", -1.0, "sodium citrate"), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "GN broth (Hajna) — Hajna AA. Public Health Lab 1955;13:83. Salmonella/Shigella enrichment.",
  "note": "Selective enrichment (high mannitol/low glucose favours non-lactose fermenters).", "uncovered": _sel("Sodium deoxycholate")}
LESENDO = {"complex": ["peptone", "yeast extract"],
  "defined": [("lcts", -10.0, "lactose"), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("so3", -0.1, "sodium sulfite")] + _MINBASE,
  "oxygen": "facultative", "ref": "LES Endo agar — McCarthy JA et al.; APHA Standard Methods. Coliforms (membrane filter).",
  "note": "Differential for coliforms (fuchsin-sulfite).", "uncovered": _sel("Basic fuchsin", "Sodium desoxycholate")}
MFC = {"complex": ["tryptone", "peptone", "yeast extract"],
  "defined": [("lcts", -10.0, "lactose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "m-FC agar — Geldreich EE et al. Appl Microbiol 1965;13:208. Faecal coliforms (44.5°C).",
  "note": "Selective/differential for faecal coliforms.", "uncovered": _sel("Bile salts", "Aniline blue", "Rosolic acid")}
TBX = {"complex": ["tryptone"],
  "defined": _MINBASE,
  "oxygen": "facultative", "ref": "TBX agar (Tryptone Bile X-glucuronide) — ISO 16649. E. coli (beta-glucuronidase).",
  "note": "Selective/differential for E. coli (BCIG cleavage → blue-green); carbon from tryptone.", "uncovered": _sel("Bile salts", "BCIG (5-bromo-4-chloro-3-indolyl beta-D-glucuronide)")}
MSRV = {"complex": ["casein peptone", "soytone"],
  "defined": [("mg2", -1000.0, "MgCl2 (high)"), ("cl", -1000.0, ""), ("na1", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "MSRV (Modified Semisolid Rappaport-Vassiliadis) — De Smedt JM et al. J Food Prot 1986;49:510. Salmonella (motility enrichment).",
  "note": "Semisolid selective enrichment; motile Salmonella migrate.", "uncovered": _sel("Malachite green", "Novobiocin")}
# Haemophilus / Neisseria / Campylobacter fastidious
HTM = {"complex": ["casein peptone", "beef extract"],
  "defined": [("strch1", -1.0, "starch"), ("pheme", -0.05, "hemin (X factor)"), ("nad", -1.0, "NAD (V factor)"), ("thm", -1.0, "thiamine"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Haemophilus Test Medium (HTM) — Jorgensen JH et al. J Clin Microbiol 1987;25:2105. Haemophilus AST.",
  "note": "Mueller-Hinton base + X (hemin) and V (NAD) factors for Haemophilus."}
LEVINTHAL = {"complex": ["peptone"],
  "defined": [("pheme", -0.05, "hemin (X)"), ("nad", -1.0, "NAD (V)"), ("glc__D", -2.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Levinthal medium — Levinthal W. 1918. Haemophilus influenzae (transparent, iridescence).",
  "note": "Transparent haem/NAD medium for Haemophilus.", "uncovered": _sel("Defibrinated blood (heated & filtered)")}
FILDES = {"complex": ["casein peptone", "peptone"],
  "defined": [("pheme", -0.05, "hemin (X)"), ("nad", -1.0, "NAD (V)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Fildes enrichment agar — Fildes P. Br J Exp Pathol 1920;1:129. Haemophilus.",
  "note": "Peptic digest of blood as X+V source for Haemophilus.", "uncovered": _sel("Peptic digest of sheep blood")}
MARTINLEWIS = {"complex": ["casein peptone", "peptone"],
  "defined": [("strch1", -1.0, "corn starch"), ("pheme", -0.05, "hemoglobin (X)"), ("glc__D", -5.0, "glucose (IsoVitaleX)"),
              ("gln__L", -1.0, "glutamine"), ("cys__L", -1.0, "cysteine"), ("thm", -1.0, "thiamine"), ("nac", -1.0, "nicotinamide"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Martin-Lewis agar — Martin JE, Lewis JS. CDC 1977. Pathogenic Neisseria (anisomycin variant of Thayer-Martin).",
  "note": "GC base + hemoglobin + IsoVitaleX; VCAT antibiotics selective.", "uncovered": _sel("Vancomycin", "Colistin", "Trimethoprim", "Anisomycin")}
PRESTON = {"complex": ["peptone", "beef extract"],
  "defined": [("pheme", -0.05, "haem (lysed horse blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Preston Campylobacter medium — Bolton FJ, Robertson L. J Clin Pathol 1982;35:462.",
  "note": "Selective blood medium for Campylobacter; incubate microaerophilically (5% O2).", "uncovered": _sel("Polymyxin B", "Rifampicin", "Trimethoprim", "Cycloheximide", "Lysed horse blood")}
# anaerobes
KVLB = {"complex": ["casein peptone", "peptone"],
  "defined": [("pheme", -0.05, "hemin"), ("phllqne", -0.01, "vitamin K1"), ("cys__L", -1.0, "cysteine"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Kanamycin-Vancomycin Laked Blood (KVLB) agar — CDC anaerobe manual. Pigmented anaerobes/Bacteroides.",
  "note": "Selective anaerobe blood agar (laked blood + kanamycin/vancomycin).", "uncovered": _sel("Kanamycin", "Vancomycin", "Laked (lysed) sheep blood")}
PY = {"complex": ["peptone", "casein peptone", "yeast extract"],
  "defined": [("cys__L", -1.0, "cysteine (reductant)"), ("pheme", -0.05, "hemin"), ("phllqne", -0.01, "vitamin K1"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Peptone Yeast (PY) broth — Holdeman LV, Moore WEC. VPI Anaerobe Manual 1977.",
  "note": "Basal anaerobe broth (base for PY-carbohydrate fermentation tests)."}
ABA = {"complex": ["casein peptone", "soytone", "yeast extract"],
  "defined": [("glc__D", -2.0, "glucose"), ("arg__L", -1.0, "arginine"), ("cys__L", -1.0, "cysteine"), ("pheme", -0.05, "hemin"), ("phllqne", -0.01, "vitamin K1"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Anaerobe Basal Agar — Oxoid/Wilkins. General anaerobe cultivation.",
  "note": "Enriched general-purpose anaerobe medium (hemin + vitamin K1 + cysteine)."}
# fungi
BIGGY = {"complex": ["yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("gly", -5.0, "glycine")] + _MINBASE,
  "oxygen": "aerobic", "ref": "BiGGY agar (Nickerson) — Nickerson WJ. J Infect Dis 1953;93:43. Candida (sulfite reduction).",
  "note": "Differential for Candida spp. (bismuth sulfite reduction → brown/black colonies).", "uncovered": _sel("Bismuth ammonium citrate", "Sodium sulfite")}
DIXON = {"complex": ["malt extract", "peptone"],
  "defined": [("glyc", -5.0, "glycerol"), ("ocdcea", -1.0, "Tween-40 / oleic acid (lipid — Malassezia is lipophilic)")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Modified Dixon agar — van Abbe NJ 1964; Guého. Malassezia (lipophilic yeasts).",
  "note": "Lipid-supplemented medium for lipophilic Malassezia.", "uncovered": _sel("Ox bile", "Glycerol mono-oleate")}
V8AGAR = {"complex": [],
  "defined": [("glc__D", -5.0, "glucose"), ("ca2", -1000.0, "CaCO3"), ("k", -1000.0, "K"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "V8 juice agar — standard. Fungal/oomycete sporulation.",
  "note": "Sporulation medium.", "uncovered": _sel("V8 vegetable juice (mixed plant nutrient matrix)")}
OATMEAL = {"complex": [],
  "defined": [("strch1", -10.0, "oat starch (carbon)"), ("k", -1000.0, "K"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg"), ("so4", -1000.0, "sulfate"), ("na1", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Oatmeal Agar (ISP Medium 3) — Shirling EB, Gottlieb D. Int J Syst Bacteriol 1966;16:313. Streptomyces sporulation.",
  "note": "Sporulation/characterisation medium for actinomycetes.", "uncovered": _sel("Oatmeal (mixed cereal nutrient matrix)")}
LITTMAN = {"complex": ["peptone"],
  "defined": [("glc__D", -10.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Littman Oxgall agar — Littman ML. Am J Clin Pathol 1947;17:659. Fungi (restricted colonies).",
  "note": "Fungal medium; oxgall restricts colony spread.", "uncovered": _sel("Ox bile (oxgall)", "Crystal violet", "Streptomycin")}
# mycobacteria
SAUTON = {"complex": [],
  "defined": [("asn__L", -5.0, "L-asparagine (SOLE N)"), ("glyc", -10.0, "glycerol (carbon)"), ("cit", -2.0, "citric acid"), ("fe3", -1.0, "ferric ammonium citrate"),
              ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "aerobic", "ref": "Sauton medium — Sauton B. C R Acad Sci 1912;155:860. Defined mycobacterial medium (BCG production).",
  "note": "Defined synthetic medium (asparagine N, glycerol C); no peptone."}
KIRCHNER = {"complex": ["peptone"],
  "defined": [("asn__L", -5.0, "L-asparagine"), ("glyc", -10.0, "glycerol"), ("cit", -2.0, "sodium citrate"), ("na1", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Kirchner medium — Kirchner O. Zentralbl Bakteriol 1932. Mycobacterium tuberculosis (liquid selective).",
  "note": "Liquid selective mycobacterial medium.", "uncovered": _sel("Serum")}
PETRAGNANI = {"complex": ["peptone"],
  "defined": [("glyc", -10.0, "glycerol"), ("strch1", -2.0, "potato starch"), ("na1", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Petragnani medium — Petragnani G. 1926. Mycobacterium tuberculosis (more inhibitory than LJ).",
  "note": "Egg-based mycobacterial medium; high malachite green.", "uncovered": _sel("Whole egg + egg yolk (protein/lipid matrix)", "Malachite green (high)")}
HEYM = {"complex": ["peptone", "beef extract"],
  "defined": [("glyc", -5.0, "glycerol"), ("pyr", -2.0, "sodium pyruvate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Herrold's Egg Yolk medium (HEYM) — Herrold RD. J Infect Dis 1931;48:236. Mycobacterium avium subsp. paratuberculosis.",
  "note": "Egg-yolk mycobacterial medium; mycobactin J for MAP.", "uncovered": _sel("Whole egg + egg yolk (protein/lipid matrix)", "Malachite green", "Mycobactin J")}
# nitrogen-fixers / rhizobia / soil
ASHBY = {"complex": [],
  "defined": [("mnl", -10.0, "mannitol (SOLE carbon)")] + _NFREE,
  "oxygen": "aerobic", "ref": "Ashby's mannitol medium — Ashby SF. J Agric Sci 1907;2:35. Azotobacter (free-living N2-fixer).",
  "note": "Nitrogen-FREE medium; N fixed from atmospheric N2 (Azotobacter)."}
JENSEN = {"complex": [],
  "defined": [("sucr", -10.0, "sucrose (SOLE carbon)"), ("cit", -1.0, "sodium citrate")] + _NFREE,
  "oxygen": "aerobic", "ref": "Jensen's N-free medium — Jensen HL. Proc Linn Soc NSW 1942;67:98. Azotobacter/diazotrophs.",
  "note": "Nitrogen-FREE medium for free-living diazotrophs (atmospheric N2)."}
NFB = {"complex": [],
  "defined": [("mal__L", -10.0, "DL-malate (SOLE carbon)")] + _NFREE,
  "oxygen": "facultative", "ref": "NFb (Nitrogen-free bromothymol) semisolid — Döbereiner J. 1976. Azospirillum (microaerophilic N2-fixer).",
  "note": "N-FREE semisolid; malate carbon; incubate microaerophilically for nitrogenase.", "uncovered": _sel("Bromothymol blue")}
YEM = {"complex": ["yeast extract"],
  "defined": [("mnl", -10.0, "mannitol (carbon)"), ("k", -1000.0, "K2HPO4"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Yeast Extract Mannitol (YEM) agar — Vincent JM. A Manual for the Practical Study of Root-Nodule Bacteria, 1970. Rhizobium.",
  "note": "General medium for rhizobia (mannitol + yeast extract)."}
CONGOYEM = {"complex": ["yeast extract"],
  "defined": [("mnl", -10.0, "mannitol"), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Congo Red Yeast Mannitol agar — Hahn NJ. Can J Microbiol 1966;12:725. Rhizobium differentiation.",
  "note": "YEM + congo red; rhizobia absorb dye weakly (agrobacteria strongly).", "uncovered": _sel("Congo red")}
PIKOVSKAYA = {"complex": ["yeast extract"],
  "defined": [("glc__D", -10.0, "glucose (carbon)"), ("nh4", -10.0, "ammonium sulfate (N)"), ("so4", -1000.0, "sulfate"), ("na1", -1000.0, "NaCl"),
              ("cl", -1000.0, ""), ("mg2", -1000.0, "MgSO4"), ("mn2", -1.0, "MnSO4"), ("fe2", -1000.0, "FeSO4"), ("ca2", -1000.0, "Ca (tricalcium phosphate)"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "aerobic", "ref": "Pikovskaya agar — Pikovskaya RI. Mikrobiologiya 1948;17:362. Phosphate-solubilising microbes.",
  "note": "Insoluble tricalcium phosphate as the added P source (only trace soluble P from yeast extract); solubilisers form clear halos.", "uncovered": _sel("Tricalcium phosphate (insoluble P substrate)")}
# actinomycetes (ISP) / other
ISP1 = {"complex": ["tryptone", "yeast extract"],
  "defined": _MINBASE,
  "oxygen": "aerobic", "ref": "ISP Medium 1 (Tryptone-Yeast Extract broth) — Shirling EB, Gottlieb D. Int J Syst Bacteriol 1966;16:313.",
  "note": "Growth medium for Streptomyces; carbon from tryptone/yeast extract."}
ISP4 = {"complex": [],
  "defined": [("strch1", -10.0, "soluble starch (carbon)"), ("nh4", -10.0, "ammonium sulfate (N)"), ("so4", -1000.0, "sulfate"), ("k", -1000.0, "K2HPO4"),
              ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "MgSO4"), ("na1", -1000.0, "NaCl"), ("cl", -1000.0, ""), ("ca2", -1000.0, "CaCO3")] + _TRACE + [("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "aerobic", "ref": "ISP Medium 4 (Inorganic Salts-Starch agar) — Shirling & Gottlieb 1966. Streptomyces characterisation.",
  "note": "Defined starch medium for actinomycete taxonomy."}
ISP5 = {"complex": [],
  "defined": [("glyc", -10.0, "glycerol (carbon)"), ("asn__L", -5.0, "L-asparagine (N)"), ("k", -1000.0, "K2HPO4"), ("pi", -1000.0, "phosphate")] + _TRACE + [("na1", -1000.0, ""), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "aerobic", "ref": "ISP Medium 5 (Glycerol-Asparagine agar) — Shirling & Gottlieb 1966. Streptomyces characterisation.",
  "note": "Defined glycerol/asparagine medium for actinomycete taxonomy."}
BENNETT = {"complex": ["yeast extract", "beef extract", "casein peptone"],
  "defined": [("glc__D", -10.0, "glucose (carbon)")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Bennett's agar — Jones KL. J Bacteriol 1949;57:141. Actinomycetes.",
  "note": "Rich medium for actinomycete isolation/growth."}
# algae / cyanobacteria / aquatic (photoautotrophs)
F2 = {"complex": [],
  "defined": _photo(na="Na (natural/artificial seawater)"),
  "oxygen": "aerobic", "ref": "f/2 medium — Guillard RRL, Ryther JH. Can J Microbiol 1962;8:229. Marine diatoms/algae.",
  "note": "Marine photoautotroph medium (seawater base); C from CO2, N from nitrate, energy from light (not modelled)."}
CHU10 = {"complex": [],
  "defined": _photo(na="Na") + [("cit", -1.0, "ferric citrate chelate")],
  "oxygen": "aerobic", "ref": "Chu-10 medium — Chu SP. J Ecol 1942;30:284. Freshwater algae.",
  "note": "Freshwater photoautotroph medium; C from CO2/bicarbonate, N from nitrate, energy from light (not modelled)."}
ASNIII = {"complex": [],
  "defined": _photo(na="Na (high — marine sea salt)"),
  "oxygen": "aerobic", "ref": "ASN-III medium — Rippka R et al. J Gen Microbiol 1979;111:1. Marine cyanobacteria.",
  "note": "Marine cyanobacterial medium; photoautotroph (C from CO2, N from nitrate, light energy not modelled)."}
# sulfur / chemolithotroph / sulfate-reducer
STARKEY = {"complex": [],
  "defined": [("tsul", -10.0, "thiosulfate (energy — chemolithotroph)"), ("hco3", -10.0, "bicarbonate/CO2 (SOLE carbon — autotroph)"), ("nh4", -10.0, "ammonium (N)"),
              ("pi", -1000.0, "phosphate"), ("k", -1000.0, "K"), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("ca2", -1000.0, "Ca"), ("fe2", -1000.0, "Fe"),
              ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "aerobic", "ref": "Starkey medium — Starkey RL. Soil Sci 1935;39:197. Thiobacillus / sulfur-oxidising chemolithoautotrophs.",
  "note": "Chemolithoautotroph medium: energy from thiosulfate oxidation, carbon fixed from CO2."}
WIDDEL = {"complex": [],
  "defined": [("lac__L", -10.0, "lactate (electron donor / carbon)"), ("so4", -1000.0, "SULFATE (terminal electron acceptor)"), ("hco3", -10.0, "bicarbonate buffer/CO2"),
              ("nh4", -10.0, "ammonium (N)"), ("pi", -1000.0, "phosphate"), ("k", -1000.0, "K"), ("mg2", -1000.0, "Mg"), ("ca2", -1000.0, "Ca"),
              ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("fe2", -1000.0, "Fe"), ("cys__L", -1.0, "cysteine (reductant)")] + _TRACE,
  "oxygen": "anaerobic", "ref": "Widdel-Pfennig medium — Widdel F, Bak F. In: The Prokaryotes, 1992. Sulfate-reducing bacteria.",
  "note": "Defined anaerobic medium for sulfate reducers (lactate donor, sulfate acceptor)."}
HUTNER = {"complex": [],
  "defined": [("nh4", -10.0, "ammonium (N)"), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("ca2", -1000.0, "Ca"), ("k", -1000.0, "K2HPO4"),
              ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _TRACE + [("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "default_carbon": ("glc__D", -10.0), "oxygen": "facultative",
  "ref": "Hutner's mineral base — Hutner SH et al. Proc Am Philos Soc 1950;94:152. Trace-element-rich defined salts base.",
  "note": "Defined trace-metal mineral base (EDTA-chelated); carbon variable (glucose default).", "uncovered": _sel("EDTA (metal chelator)")}

# ---- fifth batch: 50 more well-known media ----
# enteric selective / differential / biochemical-test media
DCA = {"complex": ["peptone", "beef extract"],
  "defined": [("lcts", -10.0, "lactose (differential)"), ("cit", -1.0, "sodium citrate"), ("fe3", -1000.0, "ferric citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Deoxycholate Citrate Agar (DCA) — Leifson E. J Pathol Bacteriol 1935;40:581. Enteric pathogens.",
  "note": "Selective/differential medium for Salmonella and Shigella.", "uncovered": _sel("Sodium deoxycholate", "Neutral red")}
BGA = {"complex": ["peptone", "yeast extract"],
  "defined": [("lcts", -10.0, "lactose"), ("sucr", -10.0, "sucrose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Brilliant Green Agar (BGA) — Kristensen M et al. 1925; modified by Kauffmann. Salmonella (non-typhoidal).",
  "note": "Highly selective for Salmonella; lactose/sucrose non-fermenters differentiated.", "uncovered": _sel("Brilliant green", "Phenol red")}
RV = {"complex": ["soytone"],
  "defined": [("na1", -1000.0, "NaCl"), ("cl", -1000.0, ""), ("mg2", -1000.0, "MgCl2 (high)"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Rappaport-Vassiliadis (RV) broth — Rappaport F 1956; Vassiliadis P. J Appl Bacteriol 1984;56:69. Salmonella enrichment.",
  "note": "Selective enrichment broth (high MgCl2, low pH); malachite green selective.", "uncovered": _sel("Malachite green")}
TETRA = {"complex": ["peptone", "beef extract"],
  "defined": [("tsul", -5.0, "thiosulfate"), ("ca2", -1000.0, "CaCO3"), ("na1", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Tetrathionate broth (Mueller-Kauffmann) — Mueller JH 1923; Kauffmann F 1935. Salmonella enrichment.",
  "note": "Selective enrichment; tetrathionate (from thiosulfate + iodine) inhibits coliforms.", "uncovered": _sel("Bile salts", "Brilliant green", "Iodine-potassium iodide")}
CIN = {"complex": ["peptone", "yeast extract"],
  "defined": [("mnl", -10.0, "mannitol (differential)"), ("pyr", -1.0, "sodium pyruvate"), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "CIN agar (Cefsulodin-Irgasan-Novobiocin) — Schiemann DA. Can J Microbiol 1979;25:1298. Yersinia enterocolitica.",
  "note": "Selective/differential for Yersinia (bull's-eye colonies).", "uncovered": _sel("Cefsulodin", "Irgasan (triclosan)", "Novobiocin", "Crystal violet", "Neutral red")}
SMAC = {"complex": ["peptone", "casein peptone"],
  "defined": [("sbt__D", -10.0, "D-sorbitol (differential — O157 is sorbitol-negative)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Sorbitol MacConkey (SMAC) — March SB, Ratnam S. J Clin Microbiol 1986;23:869. E. coli O157:H7.",
  "note": "MacConkey with sorbitol replacing lactose; O157 colourless.", "uncovered": _sel("Bile salts", "Neutral red", "Crystal violet")}
VRBA = {"complex": ["peptone", "yeast extract"],
  "defined": [("lcts", -10.0, "lactose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Violet Red Bile Agar (VRBA) — APHA Standard Methods. Coliform enumeration.",
  "note": "Selective/differential for coliforms.", "uncovered": _sel("Bile salts", "Neutral red", "Crystal violet")}
SIMMONS = {"complex": [],
  "defined": [("cit", -10.0, "sodium citrate (SOLE carbon source)"), ("nh4", -10.0, "ammonium dihydrogen phosphate (SOLE N)"),
              ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"),
              ("k", -1000.0, "K2HPO4"), ("pi", -1000.0, "phosphate"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "facultative", "ref": "Simmons Citrate Agar — Simmons JS. J Infect Dis 1926;39:209. Citrate-utilisation test.",
  "note": "Defined test medium: citrate as sole carbon, ammonium as sole N.", "uncovered": _sel("Bromothymol blue")}
TSI = {"complex": ["peptone", "beef extract", "yeast extract"],
  "defined": [("glc__D", -1.0, "glucose (0.1%)"), ("lcts", -10.0, "lactose (1%)"), ("sucr", -10.0, "sucrose (1%)"),
              ("fe2", -1.0, "ferrous sulfate / ferric ammonium citrate (H2S)"), ("tsul", -1.0, "thiosulfate (H2S)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Triple Sugar Iron (TSI) agar — Hajna AA. J Bacteriol 1945;49:516. Enteric sugar fermentation + H2S.",
  "note": "Differential: glucose/lactose/sucrose fermentation, gas, and H2S.", "uncovered": _sel("Phenol red")}
KIA = {"complex": ["peptone", "beef extract", "yeast extract"],
  "defined": [("glc__D", -1.0, "glucose (0.1%)"), ("lcts", -10.0, "lactose (1%)"),
              ("fe2", -1.0, "ferric ammonium citrate (H2S)"), ("tsul", -1.0, "thiosulfate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Kligler Iron Agar (KIA) — Kligler IJ. J Exp Med 1917;26:87. Glucose/lactose fermentation + H2S.",
  "note": "Differential: glucose vs lactose fermentation and H2S (TSI without sucrose).", "uncovered": _sel("Phenol red")}
LIA = {"complex": ["peptone", "yeast extract"],
  "defined": [("glc__D", -1.0, "glucose"), ("lys__L", -5.0, "L-lysine (decarboxylation/deamination)"),
              ("fe3", -1.0, "ferric ammonium citrate"), ("tsul", -1.0, "thiosulfate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Lysine Iron Agar (LIA) — Edwards PR, Fife MA. Appl Microbiol 1961;9:478. Lysine decarboxylase/deaminase + H2S.",
  "note": "Differential: lysine decarboxylation and deamination.", "uncovered": _sel("Bromocresol purple")}
UREA = {"complex": ["peptone"],
  "defined": [("glc__D", -1.0, "glucose"), ("urea", -10.0, "urea (urease substrate)"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("k", -1000.0, "phosphate buffer"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Christensen Urea Agar — Christensen WB. J Bacteriol 1946;52:461. Urease test.",
  "note": "Differential urease test medium.", "uncovered": _sel("Phenol red")}
SIM = {"complex": ["peptone"],
  "defined": [("fe2", -1.0, "ferrous ammonium sulfate (H2S)"), ("tsul", -1.0, "sodium thiosulfate")] + _MINBASE,
  "oxygen": "facultative", "ref": "SIM medium — Sulfide-Indole-Motility (standard, BD). Enteric identification.",
  "note": "Differential: H2S production, indole (tryptophan), and motility.", "uncovered": _sel("Kovac's/indole reagent (added post-incubation)")}
MRVP = {"complex": ["casein peptone"],
  "defined": [("glc__D", -10.0, "glucose"), ("k", -1000.0, "K2HPO4 (buffer)"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "MR-VP broth (Clark-Lubs) — Clark WM, Lubs HA. J Bacteriol 1915;1:109. Methyl-red / Voges-Proskauer.",
  "note": "Buffered glucose-peptone broth for mixed-acid vs 2,3-butanediol fermentation.", "uncovered": _sel("Methyl red (MR reagent)", "Alpha-naphthol + KOH (VP reagent)")}
MALONATE = {"complex": ["yeast extract"],
  "defined": [("malon", -10.0, "sodium malonate (SOLE carbon)"), ("glc__D", -0.5, "glucose (trace)"), ("nh4", -10.0, "ammonium sulfate (SOLE N)"),
              ("so4", -1000.0, "sulfate"), ("na1", -1000.0, "NaCl"), ("cl", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "facultative", "ref": "Malonate broth — Leifson E. J Bacteriol 1933;26:329; Ewing WH. Malonate-utilisation test.",
  "note": "Defined test medium: malonate as sole carbon, ammonium as sole N.", "uncovered": _sel("Bromothymol blue")}
PHENYLALANINE = {"complex": ["yeast extract"],
  "defined": [("phe__L", -5.0, "DL-phenylalanine (deaminase substrate)"), ("na1", -1000.0, "NaCl"), ("cl", -1000.0, ""), ("na1", -1000.0, "Na2HPO4"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Phenylalanine Agar — Ewing WH et al. Public Health Lab 1957. Phenylalanine deaminase test.",
  "note": "Differential deaminase test medium (Proteus/Providencia/Morganella).", "uncovered": _sel("Ferric chloride (test reagent)")}
MOELLER = {"complex": ["peptone", "beef extract"],
  "defined": [("glc__D", -1.0, "glucose"), ("lys__L", -5.0, "L-lysine (decarboxylase substrate)"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Moeller Decarboxylase broth (lysine base) — Moeller V. Acta Pathol Microbiol Scand 1955;36:158.",
  "note": "Amino-acid decarboxylase test base (lysine; also ornithine/arginine variants).", "uncovered": _sel("Bromocresol purple", "Cresol red")}
# Gram-positive
BLOODAGAR = {"complex": ["casein peptone", "soytone"],
  "defined": [("glc__D", -2.0, "glucose"), ("pheme", -0.05, "hemin (sheep blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Blood Agar (Tryptic Soy Agar + 5% sheep blood) — standard. Haemolysis + general isolation.",
  "note": "General-purpose enriched medium; haemolysis differentiation.", "uncovered": _sel("Defibrinated sheep blood (RBC matrix — haemolysis substrate)")}
CNA = {"complex": ["casein peptone", "soytone", "beef extract"],
  "defined": [("pheme", -0.05, "hemin (sheep blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Colistin-Nalidixic Acid (CNA) agar — Ellner PD et al. Am J Clin Pathol 1966;45:502. Gram-positive selective.",
  "note": "Selective for Gram-positive cocci (colistin + nalidixic acid inhibit Gram-negatives).", "uncovered": _sel("Colistin", "Nalidixic acid", "Defibrinated sheep blood")}
PEA = {"complex": ["casein peptone", "soytone"],
  "defined": [("pheme", -0.05, "hemin (sheep blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Phenylethyl Alcohol (PEA) agar — Lilley BD, Brewer JH. J Am Pharm Assoc 1953;42:6. Gram-positive selective.",
  "note": "Selective for Gram-positives; 2-phenylethanol inhibits Gram-negatives (DNA synthesis).", "uncovered": _sel("2-Phenylethanol", "Defibrinated sheep blood")}
BILEESCULIN = {"complex": ["peptone", "beef extract"],
  "defined": [("escul", -5.0, "esculin (hydrolysis substrate)"), ("fe3", -1.0, "ferric ammonium citrate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Bile Esculin Agar — Swan A 1954; Facklam RR, Moody MD. Appl Microbiol 1970;20:245. Group D strep / Enterococcus.",
  "note": "Differential: esculin hydrolysis in presence of bile.", "uncovered": _sel("Oxgall (bile)")}
SLANETZ = {"complex": ["peptone", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("na1", -1000.0, "phosphate/NaCl"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Slanetz-Bartley agar — Slanetz LW, Bartley CH. J Bacteriol 1957;74:591. Enterococci enumeration.",
  "note": "Selective/differential for enterococci (azide-selective, TTC reduction).", "uncovered": _sel("Sodium azide", "2,3,5-Triphenyltetrazolium chloride (TTC)")}
KF = {"complex": ["proteose peptone", "yeast extract"],
  "defined": [("lcts", -10.0, "lactose"), ("malt", -5.0, "maltose"), ("glyc3p", -1.0, "sodium glycerophosphate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "KF Streptococcus agar — Kenner BA, Clark HF, Kabler PW. Appl Microbiol 1961;9:15. Faecal streptococci.",
  "note": "Selective/differential for faecal streptococci.", "uncovered": _sel("Sodium azide", "Bromocresol purple", "TTC")}
TODDHEWITT = {"complex": ["beef extract", "casein peptone"],
  "defined": [("glc__D", -2.0, "glucose"), ("na1", -1000.0, "NaCl/Na2CO3"), ("cl", -1000.0, ""), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Todd-Hewitt broth — Todd EW, Hewitt LF. J Pathol Bacteriol 1932;35:973. Streptococcus (enrichment for GBS).",
  "note": "Buffered infusion broth for streptococci."}
ROGOSA = {"complex": ["casein peptone", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("arab__L", -5.0, "arabinose"), ("sucr", -5.0, "sucrose"), ("ac", -20.0, "sodium acetate (high, selective)"),
              ("cit", -1.0, "ammonium citrate"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"),
              ("mn2", -1.0, "MnSO4"), ("fe2", -1000.0, "FeSO4"), ("ocdcea", -1.0, "Tween-80"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Rogosa SL agar — Rogosa M, Mitchell JA, Wiseman RF. J Bacteriol 1951;62:132. Selective for lactobacilli.",
  "note": "Selective for lactobacilli (low pH, high acetate); Mn and Tween-80 as in MRS.", "uncovered": _sel("Acetic acid (low pH selective)")}
ELLIKER = {"complex": ["tryptone", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("lcts", -5.0, "lactose"), ("sucr", -5.0, "sucrose"), ("ac", -5.0, "sodium acetate"),
              ("ascb__L", -1.0, "ascorbic acid"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Elliker broth — Elliker PR, Anderson AW, Hannesson G. J Dairy Sci 1956;39:1611. Lactic acid bacteria.",
  "note": "Enumeration/cultivation of lactic acid bacteria (dairy)."}
# anaerobes
BRUCELLABA = {"complex": ["casein peptone", "peptone"],
  "defined": [("glc__D", -2.0, "glucose"), ("cys__L", -1.0, "L-cysteine"), ("pheme", -0.05, "hemin"), ("phllqne", -0.01, "vitamin K1"), ("na1", -1000.0, ""), ("pi", -1000.0, "sodium bisulfite/phosphate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Brucella Blood Agar (CDC anaerobe) — Dowell VR, Hawkins TM, CDC 1974. Anaerobe isolation.",
  "note": "Enriched anaerobe medium (hemin + vitamin K1 + cysteine + blood).", "uncovered": _sel("Defibrinated sheep blood")}
BBE = {"complex": ["casein peptone"],
  "defined": [("escul", -5.0, "esculin"), ("fe3", -1.0, "ferric ammonium citrate"), ("pheme", -0.05, "hemin"), ("phllqne", -0.01, "vitamin K1")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Bacteroides Bile Esculin (BBE) agar — Livingston SJ, Kominos SD, Yee RB. J Clin Microbiol 1978;7:448.",
  "note": "Selective/differential for Bacteroides fragilis group (bile-resistant, esculin+).", "uncovered": _sel("Oxgall (20% bile)", "Gentamicin")}
EYA = {"complex": ["peptone", "proteose peptone"],
  "defined": [("glc__D", -2.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Egg Yolk Agar (McClung-Toabe) — McClung LS, Toabe R. J Bacteriol 1947;53:139. Clostridium lecithinase/lipase.",
  "note": "Anaerobe medium for lecithinase (Nagler) and lipase reactions.", "uncovered": _sel("Egg yolk emulsion (lecithin/lipid substrate)")}
CMG = {"complex": ["peptone", "yeast extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("cys__L", -1.0, "L-cysteine (reductant)"), ("pheme", -0.05, "hemin"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "Chopped Meat Glucose broth — VPI Anaerobe Laboratory Manual (Holdeman & Moore 1977).",
  "note": "Enrichment/maintenance broth for anaerobes; meat particles poise redox.", "uncovered": _sel("Cooked ground-meat particles (Fe/reductant matrix)")}
# fungi / yeast
YM = {"complex": ["yeast extract", "malt extract", "peptone"],
  "defined": [("glc__D", -10.0, "glucose")] + _MINBASE,
  "oxygen": "aerobic", "ref": "YM (Yeast-Mould) agar — Wickerham LJ. USDA Tech Bull 1029, 1951. Yeasts and moulds.",
  "note": "General yeast/mould medium (low pH)."}
CORNMEAL = {"complex": [],
  "defined": [("strch1", -5.0, "cornmeal starch"), ("glc__D", -1.0, "glucose (trace)"), ("ocdcea", -1.0, "Tween-80 (chlamydospore induction)")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Cornmeal Agar (with Tween-80) — standard (BD). Candida chlamydospore / dermatophyte morphology.",
  "note": "Nutritionally poor fungal medium; induces chlamydospores/hyphae."}
NIGERSEED = {"complex": ["peptone"],
  "defined": [("glc__D", -1.0, "glucose"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Niger Seed (Birdseed) Agar — Staib F. Z Hyg 1962;148:466. Cryptococcus neoformans.",
  "note": "Differential for C. neoformans (laccase → brown colonies on caffeic acid).", "uncovered": _sel("Guizotia abyssinica (niger) seed extract — caffeic acid substrate", "Chloramphenicol")}
ROSEBENGAL = {"complex": ["soytone"],
  "defined": [("glc__D", -10.0, "glucose"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Rose Bengal Chloramphenicol Agar — Martin JP. Soil Sci 1950;69:215; King AD et al. 1979. Fungi (food/soil).",
  "note": "Selective for fungi; rose bengal restricts colony spread.", "uncovered": _sel("Rose bengal", "Chloramphenicol")}
DTM = {"complex": ["soytone"],
  "defined": [("glc__D", -10.0, "glucose")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Dermatophyte Test Medium (DTM) — Taplin D et al. Arch Dermatol 1969;99:203. Dermatophytes.",
  "note": "Selective/differential for dermatophytes (alkaline → red phenol-red shift).", "uncovered": _sel("Phenol red", "Cycloheximide", "Chlortetracycline", "Gentamicin")}
IMA = {"complex": ["casein peptone", "peptone"],
  "defined": [("dextrin", -5.0, "dextrin"), ("glc__D", -5.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("k", -1000.0, "phosphate"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("fe2", -1000.0, "Fe")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Inhibitory Mould Agar (IMA) — standard (BD). Recovery of pathogenic fungi (with chloramphenicol).",
  "note": "Enriched selective fungal medium.", "uncovered": _sel("Chloramphenicol")}
# fastidious / clinical
REGANLOWE = {"complex": ["beef extract", "casein peptone"],
  "defined": [("glc__D", -1.0, "glucose (starch)"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("pheme", -0.05, "hemin (horse blood)")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Regan-Lowe agar — Regan J, Lowe F. J Clin Microbiol 1977;6:303. Bordetella pertussis.",
  "note": "Charcoal-based selective medium for Bordetella.", "uncovered": _sel("Activated charcoal", "Cephalexin", "Defibrinated horse blood")}
CYSTINETELL = {"complex": ["casein peptone", "soytone"],
  "defined": [("glc__D", -2.0, "glucose"), ("cys__L", -1.0, "L-cystine"), ("pheme", -0.05, "hemin (blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Cystine-Tellurite Blood Agar — Frobisher M. J Infect Dis 1937. Corynebacterium diphtheriae.",
  "note": "Selective/differential for C. diphtheriae (tellurite reduction → black colonies).", "uncovered": _sel("Potassium tellurite", "Defibrinated blood")}
TINSDALE = {"complex": ["peptone"],
  "defined": [("cys__L", -1.0, "L-cystine"), ("tsul", -1.0, "sodium thiosulfate"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("pheme", -0.05, "hemin (serum)")] + _MINBASE,
  "oxygen": "facultative", "ref": "Tinsdale medium — Tinsdale GFW. J Pathol Bacteriol 1947;59:461. Corynebacterium diphtheriae.",
  "note": "Selective/differential for C. diphtheriae (brown halo from cystinase).", "uncovered": _sel("Potassium tellurite", "Bovine serum", "Coagulated serum")}
LOEFFLER = {"complex": ["beef extract", "peptone"],
  "defined": [("glc__D", -1.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Loeffler serum slope — Loeffler F. Zentralbl Bakteriol 1887. Corynebacterium (metachromatic granules).",
  "note": "Serum-enriched slope; enhances metachromatic granule/pleomorphism.", "uncovered": _sel("Coagulated bovine/horse serum", "Egg")}
NYC = {"complex": ["casein peptone"],
  "defined": [("glc__D", -2.0, "glucose"), ("cys__L", -1.0, "cysteine"), ("gln__L", -1.0, "glutamine"), ("thm", -1.0, "thiamine"),
              ("nac", -1.0, "nicotinamide"), ("pheme", -0.05, "haem (lysed horse blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "New York City (NYC) medium — Faur YC et al. Health Lab Sci 1973;10:44. Neisseria gonorrhoeae.",
  "note": "Transparent selective medium for pathogenic Neisseria.", "uncovered": _sel("Vancomycin", "Colistin", "Amphotericin B", "Trimethoprim", "Lysed horse blood/plasma")}
SKIRROW = {"complex": ["casein peptone", "soytone"],
  "defined": [("pheme", -0.05, "haem (lysed horse blood)"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Skirrow agar — Skirrow MB. Br Med J 1977;2:9. Campylobacter (microaerophilic).",
  "note": "Selective blood agar for Campylobacter; incubate microaerophilically (5% O2).", "uncovered": _sel("Vancomycin", "Polymyxin B", "Trimethoprim", "Lysed horse blood")}
CCDA = {"complex": ["casein peptone"],
  "defined": [("pyr", -1.0, "sodium pyruvate"), ("fe2", -1.0, "ferrous sulfate"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Charcoal Cefoperazone Deoxycholate Agar (CCDA) — Bolton FJ et al. J Clin Pathol 1984;37:1109. Campylobacter.",
  "note": "Blood-free charcoal selective medium for Campylobacter (microaerophilic).", "uncovered": _sel("Activated charcoal", "Cefoperazone", "Sodium deoxycholate")}
OGAWA = {"complex": ["peptone"],
  "defined": [("glu__L", -1.0, "sodium glutamate (N)"), ("glyc", -10.0, "glycerol (carbon)"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Ogawa egg medium — Ogawa T. 1949; Kudoh & Kudoh 1974. Mycobacterium tuberculosis (Japan).",
  "note": "Egg-based mycobacterial medium (glutamate, no asparagine).", "uncovered": _sel("Whole egg (protein/lipid matrix)", "Malachite green")}
DUBOS = {"complex": ["casein peptone"],
  "defined": [("asn__L", -1.0, "L-asparagine (N)"), ("glc__D", -2.0, "glucose"), ("cit", -1.0, "citrate"), ("fe3", -1.0, "ferric ammonium citrate"),
              ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("na1", -1000.0, ""), ("pi", -1000.0, "phosphate"), ("ocdcea", -1.0, "Tween-80")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Dubos broth — Dubos RJ, Middlebrook G. Am Rev Tuberc 1947;56:334. Mycobacterium tuberculosis (liquid).",
  "note": "Defined liquid mycobacterial medium (Tween-80 dispersed).", "uncovered": _sel("Serum albumin (BSA fraction V)")}
STONEBRINK = {"complex": ["peptone"],
  "defined": [("pyr", -10.0, "sodium pyruvate (carbon — for M. bovis)"), ("k", -1000.0, "KH2PO4"), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg"), ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Stonebrink medium — Stonebrink B. 1958. Mycobacterium bovis (pyruvate, glycerol-free).",
  "note": "Egg-based medium with pyruvate for M. bovis (which grows poorly on glycerol).", "uncovered": _sel("Whole egg (protein/lipid matrix)", "Malachite green")}
# environmental / defined
KINGSA = {"complex": ["peptone"],
  "defined": [("glyc", -10.0, "glycerol (carbon)"), ("k", -1000.0, "K2SO4"), ("so4", -1000.0, "sulfate"), ("mg2", -1000.0, "MgCl2"), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "King's A medium — King EO, Ward MK, Raney DE. J Lab Clin Med 1954;44:301. Pseudomonas pyocyanin.",
  "note": "Enhances pyocyanin production by P. aeruginosa (K2SO4 + MgCl2)."}
PIA = {"complex": ["peptone"],
  "defined": [("glyc", -10.0, "glycerol (carbon)"), ("mg2", -1000.0, "MgCl2"), ("cl", -1000.0, ""), ("k", -1000.0, "K2SO4"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Pseudomonas Isolation Agar (PIA) — standard (BD; King's A base + Irgasan). Pseudomonas aeruginosa.",
  "note": "Selective for P. aeruginosa; enhances pyocyanin.", "uncovered": _sel("Irgasan (triclosan)")}
SPIZIZEN = {"complex": [],
  "defined": [("nh4", -10.0, "ammonium sulfate (N)"), ("so4", -1000.0, "sulfate"), ("k", -1000.0, "K2HPO4/KH2PO4"), ("pi", -1000.0, "phosphate"),
              ("cit", -1.0, "trisodium citrate"), ("mg2", -1000.0, "MgSO4"), ("na1", -1000.0, ""), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "default_carbon": ("glc__D", -10.0), "oxygen": "facultative",
  "ref": "Spizizen minimal medium — Spizizen J. Proc Natl Acad Sci USA 1958;44:1072. Bacillus subtilis transformation.",
  "note": "Defined minimal medium for B. subtilis; carbon variable (glucose default)."}
LANDY = {"complex": [],
  "defined": [("glu__L", -10.0, "L-glutamic acid (C+N source)"), ("glc__D", -20.0, "glucose (carbon)"), ("k", -1000.0, "K2HPO4"), ("pi", -1000.0, "phosphate"),
              ("mg2", -1000.0, "MgSO4"), ("so4", -1000.0, "sulfate"), ("fe2", -1000.0, "FeSO4"), ("mn2", -1.0, "MnSO4"), ("cu2", -1000.0, "CuSO4"),
              ("na1", -1000.0, ""), ("h2o", -1000.0, ""), ("h", -1000.0, "")],
  "oxygen": "aerobic", "ref": "Landy medium — Landy M et al. Proc Soc Exp Biol Med 1948;67:539. Bacillus (surfactin/iturin production).",
  "note": "Defined medium for Bacillus secondary metabolites (glutamate + glucose)."}
NUTGELATIN = {"complex": ["beef extract", "peptone"],
  "defined": _MINBASE,
  "oxygen": "facultative", "ref": "Nutrient Gelatin — standard. Gelatin-hydrolysis (gelatinase) test.",
  "note": "Nutrient broth solidified with gelatin; tests gelatinase (liquefaction).", "uncovered": _sel("Gelatin (protease substrate)")}

# ---- fourth batch: 20 more well-known media ----
LJ = {"complex": ["peptone"],
  "defined": [("asn__L", -1.0, "L-asparagine (N)"), ("glyc", -10.0, "glycerol (carbon)"), ("k", -1000.0, "K (KH2PO4)"),
              ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate"), ("cit", -1.0, "magnesium citrate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Löwenstein-Jensen medium — Jensen KA, Löwenstein E, 1932; BD LJ. Egg-based selective medium for Mycobacterium tuberculosis.",
  "note": "Egg-based mycobacterial medium; malachite green selective.", "uncovered": _sel("Malachite green", "Coagulated egg (undefined lipid/protein matrix)")}
M7H11 = {"complex": ["casein peptone"],
  "defined": M7H9["defined"], "oxygen": "aerobic",
  "ref": "Middlebrook 7H11 agar — Cohn ML, Waggoner RF, McClatchy JK. Am Rev Respir Dis 1968;98:295; BD 7H11. (7H10 base + 0.1% casein hydrolysate.)",
  "note": "Mycobacterial agar (7H10 + casein hydrolysate).", "uncovered": _sel("Malachite green")}
THAYER = {"complex": ["peptone"],
  "defined": [("strch1", -1.0, "corn starch"), ("pheme", -0.05, "hemoglobin (X factor)"), ("glc__D", -5.0, "glucose (IsoVitaleX)"),
              ("gln__L", -1.0, "glutamine"), ("cys__L", -1.0, "cysteine"), ("thm", -1.0, "thiamine"), ("nac", -1.0, "nicotinamide"),
              ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("k", -1000.0, ""), ("pi", -1000.0, "")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Modified Thayer-Martin medium — Thayer JD, Martin JE. Public Health Rep 1966;81:559. Selective for Neisseria gonorrhoeae/meningitidis.",
  "note": "GC base + hemoglobin + IsoVitaleX; VCNT antibiotics selective.", "uncovered": _sel("Vancomycin", "Colistin", "Nystatin", "Trimethoprim")}
BCYE = {"complex": ["yeast extract"],
  "defined": [("cys__L", -1.0, "L-cysteine (essential for Legionella)"), ("fe3", -1.0, "ferric pyrophosphate"), ("akg", -1.0, "alpha-ketoglutarate")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Buffered Charcoal Yeast Extract (BCYE) — Feeley JC et al. J Clin Microbiol 1979;10:437. Legionella.",
  "note": "Legionella medium; L-cysteine and iron are essential growth factors; ACES-buffered.", "uncovered": _sel("ACES buffer", "Activated charcoal")}
BORDET = {"complex": ["peptone"],
  "defined": [("glyc", -10.0, "glycerol (carbon)"), ("pheme", -0.02, "hemin (blood)"), ("glc__D", -2.0, "glucose (potato)")] + _MINBASE,
  "oxygen": "aerobic", "ref": "Bordet-Gengou medium — Bordet J, Gengou O. Ann Inst Pasteur 1906;20:731. Bordetella pertussis.",
  "note": "Potato-glycerol-blood medium for Bordetella."}
SS = {"complex": ["peptone", "beef extract"],
  "defined": [("lcts", -10.0, "lactose (differential)"), ("cit", -1.0, "citrate"), ("tsul", -1.0, "thiosulfate"), ("fe3", -1000.0, "ferric citrate"),
              ("na1", -1000.0, ""), ("cl", -1000.0, "")] + _MINBASE,
  "oxygen": "facultative", "ref": "Salmonella-Shigella (SS) agar — standard (Difco/BD). Selective/differential for Salmonella and Shigella.",
  "note": "Selective/differential enteric medium.", "uncovered": _sel("Bile salts", "Brilliant green", "Neutral red")}
BISMUTH = {"complex": ["peptone", "beef extract"],
  "defined": [("glc__D", -5.0, "glucose"), ("na1", -1000.0, ""), ("pi", -1000.0, "phosphate"), ("fe2", -1000.0, "ferrous sulfate"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "facultative", "ref": "Bismuth Sulfite agar (Wilson-Blair) — Wilson WJ, Blair EMM. J Hyg 1927;26:374. Salmonella Typhi.",
  "note": "Highly selective for Salmonella Typhi.", "uncovered": _sel("Bismuth sulfite indicator", "Brilliant green")}
CLED = {"complex": ["peptone", "casein peptone", "beef extract"],
  "defined": [("lcts", -10.0, "lactose"), ("cys__L", -1.0, "L-cystine")] + [(b, lb, r) for (b, lb, r) in _MINBASE if b not in ("na1", "cl")] + [("na1", -1.0, "low electrolyte (no NaCl — inhibits Proteus swarming)")],
  "oxygen": "facultative", "ref": "CLED (Cystine Lactose Electrolyte Deficient) agar — Mackey JP, Sandys GH. Br Med J 1965;1:1173. Urine culture.",
  "note": "Electrolyte-deficient (prevents Proteus swarming); non-selective for urinary organisms.", "uncovered": _sel("Bromothymol blue")}
ENDO = {"complex": ["peptone"],
  "defined": [("lcts", -10.0, "lactose"), ("k", -1000.0, "K (K2HPO4)"), ("pi", -1000.0, "phosphate"), ("na1", -1000.0, ""), ("so3", -0.1, "sodium sulfite")] + _MINBASE,
  "oxygen": "facultative", "ref": "Endo agar — Endo S, 1904; APHA Standard Methods. Coliform detection.",
  "note": "Differential medium for coliforms (fuchsin-sulfite).", "uncovered": _sel("Basic fuchsin")}
SELENITE = {"complex": ["peptone"],
  "defined": [("lcts", -5.0, "lactose"), ("na1", -1000.0, ""), ("pi", -1000.0, "phosphate"), ("slnt", -0.5, "sodium selenite (selective inhibitor)")] + _MINBASE,
  "oxygen": "facultative", "ref": "Selenite F broth — Leifson E. Am J Hyg 1936;24:423. Salmonella enrichment.",
  "note": "Enrichment broth; selenite selectively inhibits coliforms."}
APW = {"complex": ["peptone"],
  "defined": [("na1", -1000.0, "high NaCl (1%)"), ("cl", -1000.0, "")] + _MINBASE + [("o2", -20.0, "aerobic")],
  "oxygen": "facultative", "ref": "Alkaline Peptone Water (APW) — standard (pH 8.4-8.6). Vibrio/Aeromonas enrichment.",
  "note": "Alkaline enrichment broth for vibrios; carbon from peptone amino acids."}
M17 = {"complex": ["tryptone", "soytone", "beef extract", "yeast extract"],
  "defined": [("lcts", -10.0, "lactose (carbon)"), ("ascb__L", -1.0, "ascorbic acid"), ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate"),
              ("glyc3p", -1.0, "beta-glycerophosphate (buffer)"), ("na1", -1000.0, ""), ("pi", -1000.0, "phosphate")] + _MINBASE,
  "oxygen": "facultative", "ref": "M17 medium — Terzaghi BE, Sandine WE. Appl Microbiol 1975;29:807. Lactococcus/Streptococcus thermophilus.",
  "note": "Lactococcal/streptococcal medium; beta-glycerophosphate buffered."}
APT = {"complex": ["tryptone", "yeast extract"],
  "defined": [("glc__D", -10.0, "glucose"), ("na1", -1000.0, ""), ("cl", -1000.0, ""), ("cit", -1.0, "citrate"), ("k", -1000.0, "K (K2HPO4)"),
              ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg"), ("so4", -1000.0, "sulfate"), ("mn2", -1.0, "Mn (MnCl2)"),
              ("fe2", -1000.0, "Fe"), ("ocdcea", -1.0, "Tween-80/oleate"), ("thm", -1.0, "thiamine")] + _MINBASE,
  "oxygen": "facultative", "ref": "APT agar — Evans JB, Niven CF. J Bacteriol 1951;62:599. Heterofermentative lactobacilli.",
  "note": "Rich medium for lactobacilli; Mn and Tween-80 as in MRS."}
PDA = {"complex": [],
  "defined": [("glc__D", -15.0, "dextrose (carbon)"), ("strch1", -1.0, "potato starch")] + _MINBASE + [("o2", -20.0, "aerobic")],
  "oxygen": "aerobic", "ref": "Potato Dextrose Agar (PDA) — BD/standard. Potato infusion + 2% dextrose. Fungi/moulds/yeasts.",
  "note": "Fungal medium; potato infusion + dextrose."}
MEA = {"complex": ["malt_extract"],
  "defined": [("malt", -10.0, "maltose (malt extract)"), ("glc__D", -10.0, "dextrose")] + _MINBASE + [("o2", -20.0, "aerobic")],
  "oxygen": "aerobic", "ref": "Malt Extract Agar (MEA) — standard (BD/Oxoid). Fungi and yeasts.", "note": "Fungal medium; malt extract sugars."}
CZAPEK = {"complex": [],
  "defined": [("sucr", -15.0, "sucrose (carbon)"), ("no3", -10.0, "nitrate (NaNO3, N source)"), ("k", -1000.0, "K (K2HPO4)"),
              ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate"), ("cl", -1000.0, "KCl"),
              ("fe2", -1000.0, "Fe (FeSO4)"), ("na1", -1000.0, ""), ("h2o", -1000.0, ""), ("h", -1000.0, ""), ("o2", -20.0, "aerobic")],
  "oxygen": "aerobic", "ref": "Czapek-Dox medium — Czapek F 1902; Dox AW 1910. Defined medium for fungi/Aspergillus/Penicillium (sucrose carbon, nitrate N).",
  "note": "Defined fungal medium; sucrose + nitrate."}
VOGELBONNER = {"complex": [],
  "defined": [("mg2", -1000.0, "Mg (MgSO4)"), ("so4", -1000.0, "sulfate"), ("cit", -1.0, "citric acid"), ("k", -1000.0, "K (K2HPO4)"),
              ("pi", -1000.0, "phosphate"), ("na1", -1000.0, "Na (NaNH4 phosphate)"), ("nh4", -1000.0, "ammonium"),
              ("h2o", -1000.0, ""), ("h", -1000.0, ""), ("o2", -20.0, "aerobic")],
  "default_carbon": ("glc__D", -10.0), "oxygen": "facultative",
  "ref": "Vogel-Bonner minimal medium E — Vogel HJ, Bonner DM. J Biol Chem 1956;218:97. E. coli/Salmonella defined minimal.",
  "note": "Defined minimal medium (citrate as trace-metal chelator); carbon variable (glucose default)."}
POSTGATE = {"complex": ["yeast extract"],
  "defined": [("lac__L", -10.0, "lactate (carbon / electron donor)"), ("k", -1000.0, "K (KH2PO4)"), ("pi", -1000.0, "phosphate"),
              ("nh4", -1000.0, "ammonium"), ("cl", -1000.0, ""), ("na1", -1000.0, ""), ("so4", -1000.0, "SULFATE (terminal electron acceptor)"),
              ("ca2", -1000.0, "Ca"), ("mg2", -1000.0, "Mg"), ("fe2", -1000.0, "Fe"), ("cit", -1.0, "citrate")],
  "oxygen": "anaerobic", "ref": "Postgate medium C — Postgate JR, The Sulphate-Reducing Bacteria, 2nd ed. Cambridge UP 1984. Desulfovibrio.",
  "note": "Anaerobic medium for sulfate-reducing bacteria; lactate donor, sulfate acceptor.", "uncovered": _sel("Sodium thioglycollate", "Ascorbate (reductant)")}
CCFA = {"complex": ["proteose_peptone"],
  "defined": [("fru", -10.0, "fructose (carbon)"), ("na1", -1000.0, ""), ("pi", -1000.0, "phosphate"), ("k", -1000.0, "K"), ("cl", -1000.0, ""), ("mg2", -1000.0, "Mg"), ("so4", -1000.0, "sulfate")] + _MINBASE,
  "oxygen": "anaerobic", "ref": "CCFA (Cycloserine-Cefoxitin Fructose Agar) — George WL et al. J Clin Microbiol 1979;9:214. Clostridioides difficile.",
  "note": "Selective anaerobic medium for C. difficile.", "uncovered": _sel("Cycloserine", "Cefoxitin", "Neutral red", "Taurocholate (germinant)")}
STARCHCASEIN = {"complex": ["casein peptone"],
  "defined": [("strch1", -10.0, "soluble starch (carbon)"), ("no3", -10.0, "nitrate (KNO3, N)"), ("k", -1000.0, "K"), ("na1", -1000.0, ""),
              ("cl", -1000.0, ""), ("pi", -1000.0, "phosphate"), ("mg2", -1000.0, "Mg"), ("so4", -1000.0, "sulfate"), ("ca2", -1000.0, "Ca"), ("fe2", -1000.0, "Fe")] + _MINBASE + [("o2", -20.0, "aerobic")],
  "oxygen": "aerobic", "ref": "Starch-Casein agar — Küster E, Williams ST. Nature 1964;202:928. Soil actinomycetes/Streptomyces.",
  "note": "Selective medium for soil actinomycetes; starch carbon, nitrate N."}

# kind -> (spec, match regex, exclude regex or None, std_id, std_name)
REGISTRY = [
    ("PALCAM", PALCAM, r"\bPALCAM\b", r"modified", "std_palcam", "PALCAM agar (standard, Listeria)"),
    ("OxfordListeria", OXFORDL, r"oxford agar|oxford listeria", r"modified", "std_oxford_listeria", "Oxford agar (standard, Listeria)"),
    ("Fraser", FRASER, r"fraser broth", r"half.?fraser|modified", "std_fraser", "Fraser broth (standard)"),
    ("BPW", BPW, r"buffered peptone water|\bBPW\b", r"modified", "std_bpw", "Buffered Peptone Water (standard)"),
    ("EEbroth", EEBROTH, r"enterobacteriaceae enrichment|\bEE broth\b|mossel", r"modified", "std_ee_broth", "Enterobacteriaceae Enrichment broth (standard)"),
    ("VRBGA", VRBGA, r"violet red bile glucose|\bVRBGA\b|\bVRBG\b", r"modified", "std_vrbga", "Violet Red Bile Glucose Agar (standard)"),
    ("VogelJohnson", VOGELJOHNSON, r"vogel.?johnson", r"modified", "std_vogel_johnson", "Vogel-Johnson agar (standard)"),
    ("Edwards", EDWARDS, r"edwards medium|edwards agar", r"modified", "std_edwards", "Edwards medium (standard)"),
    ("KAA", KAA, r"kanamycin aesculin azide|kanamycin esculin azide|\bKAA\b", r"modified", "std_kaa", "Kanamycin Aesculin Azide agar (standard)"),
    ("AzideDextrose", AZIDEDEX, r"azide dextrose|rothe broth", r"modified", "std_azide_dextrose", "Azide Dextrose broth (standard)"),
    ("BileEsculinAzide", BEAAZIDE, r"bile esculin azide|enterococcosel", r"modified", "std_bile_esculin_azide", "Bile Esculin Azide agar (standard)"),
    ("Granada", GRANADA, r"granada medium|granada agar", r"modified", "std_granada", "Granada medium (standard, GBS)"),
    ("GNbroth", GNBROTH, r"\bGN broth\b|hajna.?gn", r"modified", "std_gn_broth", "GN broth (standard, Hajna)"),
    ("LESEndo", LESENDO, r"\bLES endo\b|\bm.?endo\b", r"modified", "std_les_endo", "LES Endo agar (standard)"),
    ("mFC", MFC, r"\bm.?FC\b|faecal coliform agar|fecal coliform agar", r"modified", "std_mfc", "m-FC agar (standard)"),
    ("TBX", TBX, r"\bTBX\b|tryptone bile glucuronide|tryptone bile x", r"modified", "std_tbx", "TBX agar (standard)"),
    ("MSRV", MSRV, r"\bMSRV\b|semisolid rappaport", r"modified", "std_msrv", "MSRV agar (standard)"),
    ("HTM", HTM, r"haemophilus test medium|\bHTM\b", r"modified", "std_htm", "Haemophilus Test Medium (standard)"),
    ("Levinthal", LEVINTHAL, r"levinthal", r"modified", "std_levinthal", "Levinthal medium (standard)"),
    ("Fildes", FILDES, r"fildes", r"modified", "std_fildes", "Fildes enrichment agar (standard)"),
    ("MartinLewis", MARTINLEWIS, r"martin.?lewis", r"modified", "std_martin_lewis", "Martin-Lewis agar (standard)"),
    ("Preston", PRESTON, r"preston (medium|broth|agar|campylobacter)", r"modified", "std_preston", "Preston Campylobacter medium (standard)"),
    ("KVLB", KVLB, r"\bKVLB\b|kanamycin.?vancomycin laked", r"modified", "std_kvlb", "Kanamycin-Vancomycin Laked Blood agar (standard)"),
    ("PYbroth", PY, r"peptone yeast (broth|medium)|\bPY broth\b", r"glucose|carbohydrate|modified", "std_py_broth", "Peptone Yeast broth (standard)"),
    ("AnaerobeBasal", ABA, r"anaerobe basal|anaerobic basal agar", r"modified", "std_anaerobe_basal", "Anaerobe Basal Agar (standard)"),
    ("BiGGY", BIGGY, r"\bBiGGY\b|nickerson", r"modified", "std_biggy", "BiGGY agar (standard, Candida)"),
    ("Dixon", DIXON, r"dixon agar|dixon medium", r"modified", "std_dixon", "Dixon agar (standard, Malassezia)"),
    ("V8", V8AGAR, r"\bV8\b (juice )?agar", r"modified", "std_v8_agar", "V8 juice agar (standard)"),
    ("Oatmeal", OATMEAL, r"oatmeal agar|\bISP\W?3\b|ISP medium 3", r"modified", "std_oatmeal", "Oatmeal Agar / ISP3 (standard)"),
    ("Littman", LITTMAN, r"littman", r"modified", "std_littman", "Littman Oxgall agar (standard)"),
    ("Sauton", SAUTON, r"sauton", r"modified", "std_sauton", "Sauton medium (standard)"),
    ("Kirchner", KIRCHNER, r"kirchner", r"modified", "std_kirchner", "Kirchner medium (standard)"),
    ("Petragnani", PETRAGNANI, r"petragnani", r"modified", "std_petragnani", "Petragnani medium (standard)"),
    ("HEYM", HEYM, r"herrold'?s egg|\bHEYM\b", r"modified", "std_heym", "Herrold's Egg Yolk medium (standard)"),
    ("Ashby", ASHBY, r"ashby'?s? (mannitol )?(medium|agar)|ashby mannitol", r"modified", "std_ashby", "Ashby's mannitol medium (standard)"),
    ("Jensen", JENSEN, r"jensen'?s? (n.?free|nitrogen.?free)", r"modified", "std_jensen_nfree", "Jensen's N-free medium (standard)"),
    ("NFb", NFB, r"\bNFb\b|nitrogen.?free bromothymol", r"modified", "std_nfb", "NFb semisolid medium (standard)"),
    ("YEM", YEM, r"yeast (extract )?mannitol|\bYEM\b|\bYMA\b", r"congo|modified", "std_yem", "Yeast Extract Mannitol agar (standard)"),
    ("CongoYEM", CONGOYEM, r"congo red (yeast|mannitol|YEM)|CRYEM", r"modified", "std_congo_yem", "Congo Red YEM agar (standard)"),
    ("Pikovskaya", PIKOVSKAYA, r"pikovskaya", r"modified", "std_pikovskaya", "Pikovskaya agar (standard)"),
    ("ISP1", ISP1, r"\bISP\W?1\b|ISP medium 1|tryptone.?yeast extract broth", r"modified", "std_isp1", "ISP Medium 1 (standard)"),
    ("ISP4", ISP4, r"\bISP\W?4\b|ISP medium 4|inorganic salts.?starch", r"modified", "std_isp4", "ISP Medium 4 (standard)"),
    ("ISP5", ISP5, r"\bISP\W?5\b|ISP medium 5|glycerol.?asparagine", r"modified", "std_isp5", "ISP Medium 5 (standard)"),
    ("Bennett", BENNETT, r"bennett'?s? (agar|medium)", r"modified", "std_bennett", "Bennett's agar (standard)"),
    ("F2", F2, r"\bf/2\b|guillard'?s? f/2|f/2 medium", r"modified", "std_f2", "f/2 medium (standard, marine algae)"),
    ("Chu10", CHU10, r"chu.?10|chu'?s? medium", r"modified", "std_chu10", "Chu-10 medium (standard)"),
    ("ASNIII", ASNIII, r"\bASN.?III\b", r"modified", "std_asn_iii", "ASN-III medium (standard, marine cyanobacteria)"),
    ("Starkey", STARKEY, r"starkey", r"modified", "std_starkey", "Starkey medium (standard)"),
    ("Widdel", WIDDEL, r"widdel|widdel.?pfennig", r"modified", "std_widdel", "Widdel-Pfennig medium (standard)"),
    ("Hutner", HUTNER, r"hutner'?s?", r"modified", "std_hutner", "Hutner's mineral base (standard)"),
    ("DCA", DCA, r"deoxycholate citrate|\bDCA\b", r"modified", "std_dca", "Deoxycholate Citrate Agar (standard)"),
    ("BrilliantGreen", BGA, r"brilliant green agar|\bBGA\b", r"modified", "std_brilliant_green", "Brilliant Green Agar (standard)"),
    ("RappaportVassiliadis", RV, r"rappaport.?vassiliadis|\bRV\b broth|\bRVS\b", r"modified", "std_rappaport_vassiliadis", "Rappaport-Vassiliadis broth (standard)"),
    ("Tetrathionate", TETRA, r"tetrathionate", r"modified", "std_tetrathionate", "Tetrathionate broth (standard)"),
    ("CIN", CIN, r"\bCIN\b agar|cefsulodin.?irgasan", r"modified", "std_cin", "CIN agar (standard, Yersinia)"),
    ("SMAC", SMAC, r"sorbitol macconkey|\bSMAC\b", r"modified", "std_smac", "Sorbitol MacConkey (standard)"),
    ("VRBA", VRBA, r"violet red bile agar|\bVRBA\b", r"glucose|\bVRBGA\b|modified", "std_vrba", "Violet Red Bile Agar (standard)"),
    ("SimmonsCitrate", SIMMONS, r"simmons citrate|citrate agar", r"modified", "std_simmons_citrate", "Simmons Citrate Agar (standard)"),
    ("TSI", TSI, r"triple sugar iron|\bTSI\b", r"modified", "std_tsi", "Triple Sugar Iron agar (standard)"),
    ("KIA", KIA, r"kligler", r"modified", "std_kia", "Kligler Iron Agar (standard)"),
    ("LIA", LIA, r"lysine iron|\bLIA\b", r"modified", "std_lia", "Lysine Iron Agar (standard)"),
    ("UreaAgar", UREA, r"christensen|urea agar|urease agar", r"modified", "std_urea_agar", "Christensen Urea Agar (standard)"),
    ("SIM", SIM, r"\bSIM\b medium|sulfide.?indole.?motility", r"modified", "std_sim", "SIM medium (standard)"),
    ("MRVP", MRVP, r"\bMR.?VP\b|methyl red.?voges|clark.?lubs", r"modified", "std_mrvp", "MR-VP broth (standard)"),
    ("Malonate", MALONATE, r"malonate broth|malonate utiliz", r"modified", "std_malonate", "Malonate broth (standard)"),
    ("Phenylalanine", PHENYLALANINE, r"phenylalanine agar|phenylalanine deaminase", r"modified", "std_phenylalanine", "Phenylalanine Agar (standard)"),
    ("MoellerDecarb", MOELLER, r"moeller|decarboxylase broth", r"modified", "std_moeller_decarboxylase", "Moeller Decarboxylase broth (standard)"),
    ("BloodAgar", BLOODAGAR, r"blood agar|sheep blood agar", r"chocolate|columbia|brucella|bordet|thayer|brain|cystine|tellurite|regan|azide|phenylethyl|colistin|modified", "std_blood_agar", "Blood Agar (TSA + sheep blood, standard)"),
    ("CNA", CNA, r"colistin.?nalidixic|\bCNA\b agar", r"modified", "std_cna", "Colistin-Nalidixic Acid agar (standard)"),
    ("PEA", PEA, r"phenylethyl alcohol|\bPEA\b agar", r"modified", "std_pea", "Phenylethyl Alcohol agar (standard)"),
    ("BileEsculin", BILEESCULIN, r"bile esculin", r"bacteroides|\bBBE\b|azide|modified", "std_bile_esculin", "Bile Esculin Agar (standard)"),
    ("SlanetzBartley", SLANETZ, r"slanetz.?bartley", r"modified", "std_slanetz_bartley", "Slanetz-Bartley agar (standard)"),
    ("KFStrep", KF, r"\bKF\b strep|kenner.?fair", r"modified", "std_kf_streptococcus", "KF Streptococcus agar (standard)"),
    ("ToddHewitt", TODDHEWITT, r"todd.?hewitt", r"modified", "std_todd_hewitt", "Todd-Hewitt broth (standard)"),
    ("Rogosa", ROGOSA, r"rogosa", r"modified", "std_rogosa", "Rogosa SL agar (standard)"),
    ("Elliker", ELLIKER, r"elliker", r"modified", "std_elliker", "Elliker broth (standard)"),
    ("BrucellaBA", BRUCELLABA, r"brucella blood|brucella agar", r"modified", "std_brucella_blood", "Brucella Blood Agar (standard)"),
    ("BBE", BBE, r"bacteroides bile esculin|\bBBE\b", r"modified", "std_bbe", "Bacteroides Bile Esculin agar (standard)"),
    ("EggYolk", EYA, r"egg yolk agar|mcclung.?toabe", r"modified", "std_egg_yolk", "Egg Yolk Agar (standard)"),
    ("ChoppedMeatGlucose", CMG, r"chopped meat glucose|chopped meat carbohydrate", r"modified", "std_chopped_meat_glucose", "Chopped Meat Glucose broth (standard)"),
    ("YMagar", YM, r"\bYM\b agar|yeast.?mou?ld agar|yeast.?malt agar", r"modified", "std_ym_agar", "YM (Yeast-Mould) agar (standard)"),
    ("Cornmeal", CORNMEAL, r"cornmeal agar|corn meal agar", r"modified", "std_cornmeal", "Cornmeal Agar (standard)"),
    ("NigerSeed", NIGERSEED, r"niger seed|birdseed agar|bird seed agar|staib", r"modified", "std_niger_seed", "Niger Seed Agar (standard)"),
    ("RoseBengal", ROSEBENGAL, r"rose.?bengal", r"modified", "std_rose_bengal", "Rose Bengal Chloramphenicol Agar (standard)"),
    ("DTM", DTM, r"dermatophyte test", r"modified", "std_dtm", "Dermatophyte Test Medium (standard)"),
    ("IMA", IMA, r"inhibitory mou?ld agar|\bIMA\b", r"modified", "std_ima", "Inhibitory Mould Agar (standard)"),
    ("ReganLowe", REGANLOWE, r"regan.?lowe", r"modified", "std_regan_lowe", "Regan-Lowe agar (standard)"),
    ("CystineTellurite", CYSTINETELL, r"cystine.?tellurite", r"modified", "std_cystine_tellurite", "Cystine-Tellurite Blood Agar (standard)"),
    ("Tinsdale", TINSDALE, r"tinsdale", r"modified", "std_tinsdale", "Tinsdale medium (standard)"),
    ("Loeffler", LOEFFLER, r"l[oö]effler", r"modified", "std_loeffler", "Loeffler serum slope (standard)"),
    ("NYC", NYC, r"new york city medium|\bNYC\b medium", r"modified", "std_nyc", "New York City medium (standard)"),
    ("Skirrow", SKIRROW, r"skirrow", r"modified", "std_skirrow", "Skirrow agar (standard)"),
    ("CCDA", CCDA, r"\bCCDA\b|charcoal cefoperazone", r"modified", "std_ccda", "Charcoal Cefoperazone Deoxycholate Agar (standard)"),
    ("Ogawa", OGAWA, r"ogawa", r"modified", "std_ogawa", "Ogawa egg medium (standard)"),
    ("Dubos", DUBOS, r"dubos", r"modified", "std_dubos", "Dubos broth (standard)"),
    ("Stonebrink", STONEBRINK, r"stonebrink", r"modified", "std_stonebrink", "Stonebrink medium (standard)"),
    ("KingsA", KINGSA, r"king'?s a\b|king a (medium|agar)", r"modified", "std_kings_a", "King's A medium (standard)"),
    ("PIA", PIA, r"pseudomonas isolation agar|\bPIA\b", r"modified", "std_pia", "Pseudomonas Isolation Agar (standard)"),
    ("Spizizen", SPIZIZEN, r"spizizen", r"modified", "std_spizizen", "Spizizen minimal medium (standard)"),
    ("Landy", LANDY, r"landy medium|landy broth", r"modified", "std_landy", "Landy medium (standard)"),
    ("NutrientGelatin", NUTGELATIN, r"nutrient gelatin|gelatin agar", r"modified", "std_nutrient_gelatin", "Nutrient Gelatin (standard)"),
    ("LowensteinJensen", LJ, r"l[oö]wenstein.?jensen|\bLJ\b (medium|slant|agar)", r"modified", "std_lowenstein_jensen", "Löwenstein-Jensen medium (standard)"),
    ("Middlebrook7H11", M7H11, r"7H11", r"modified", "std_middlebrook_7h11", "Middlebrook 7H11 agar (standard)"),
    ("ThayerMartin", THAYER, r"thayer.?martin", r"derived", "std_thayer_martin", "Modified Thayer-Martin medium (standard)"),
    ("BCYE", BCYE, r"\bBCYE\b|buffered charcoal|charcoal yeast", r"modified", "std_bcye", "Buffered Charcoal Yeast Extract (standard)"),
    ("BordetGengou", BORDET, r"bordet.?gengou", r"modified", "std_bordet_gengou", "Bordet-Gengou medium (standard)"),
    ("SSagar", SS, r"salmonella.?shigella|\bSS agar\b|\bSSA\b", r"modified", "std_ss_agar", "Salmonella-Shigella agar (standard)"),
    ("BismuthSulfite", BISMUTH, r"bismuth sulf?ite|wilson.?blair", r"modified", "std_bismuth_sulfite", "Bismuth Sulfite agar (standard)"),
    ("CLED", CLED, r"\bCLED\b|cystine lactose electrolyte", r"modified", "std_cled", "CLED agar (standard)"),
    ("Endo", ENDO, r"endo agar|endo'?s? medium", r"modified", "std_endo", "Endo agar (standard)"),
    ("Selenite", SELENITE, r"selenite", r"modified", "std_selenite_broth", "Selenite F broth (standard)"),
    ("APW", APW, r"alkaline peptone water|\bAPW\b", r"modified", "std_alkaline_peptone_water", "Alkaline Peptone Water (standard)"),
    ("M17", M17, r"\bM17\b", r"modified", "std_m17", "M17 medium (standard)"),
    ("APT", APT, r"\bAPT\b (agar|broth|medium)", r"modified", "std_apt", "APT medium (standard)"),
    ("PDA", PDA, r"potato dextrose|\bPDA\b", r"modified", "std_potato_dextrose", "Potato Dextrose Agar (standard)"),
    ("MEA", MEA, r"malt extract agar|\bMEA\b", r"modified", "std_malt_extract_agar", "Malt Extract Agar (standard)"),
    ("Czapek", CZAPEK, r"czapek", r"modified", "std_czapek_dox", "Czapek-Dox medium (standard)"),
    ("VogelBonner", VOGELBONNER, r"vogel.?bonner", r"modified", "std_vogel_bonner", "Vogel-Bonner minimal medium (standard)"),
    ("Postgate", POSTGATE, r"postgate", r"modified", "std_postgate_c", "Postgate medium C (standard)"),
    ("CCFA", CCFA, r"\bCCFA\b|cycloserine.?cefoxitin", r"modified", "std_ccfa", "CCFA (standard, C. difficile)"),
    ("StarchCasein", STARCHCASEIN, r"starch.?casein", r"modified", "std_starch_casein", "Starch-Casein agar (standard)"),
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
    # default carbon source only if the medium has no *substantive* carbon
    # (a trace chelator like citrate at lb -1 must not suppress the default)
    if spec.get("default_carbon"):
        if not any((c.get("bigg_metabolite") in CARBON) and (c.get("lower_bound", 0) <= -5)
                   for c in comps.values()):
            b, lbnd = spec["default_carbon"]
            if valid(b):
                comps["EX_%s_e" % b] = comp(b, lbnd, "default carbon source (glucose)")
    if spec["oxygen"] == "anaerobic":
        comps.pop("EX_o2_e", None)
    elif "EX_o2_e" not in comps and valid("o2"):
        # aerobic/facultative media must offer O2 uptake for respiration
        comps["EX_o2_e"] = comp("o2", -20.0, "O2 (%s)" % spec["oxygen"])
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
