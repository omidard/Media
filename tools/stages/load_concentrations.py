#!/usr/bin/env python3
"""
STAGE: load_concentrations
==========================

WHY THIS IS A STAGE AND NOT A REBUILD
-------------------------------------
The raw inputs to this resource are gone: 18 tools hardcode paths into a deleted
/tmp scratchpad and data/media/*.json is the sole surviving copy of the corpus
(finding PIPE-01). tools/mediadive/build_mediadive_media.py:6-12 points at
/tmp/claude-1000/.../media_work/ which does not exist, so the quantitative layer
cannot be recovered by re-running the builder. This stage therefore READS the
current corpus and WRITES a corrected corpus. It is composable: it never edits
data/media/ in place.


CONTRACT
--------
READS
  --in    DIR   corpus of medium JSONs            (default: data/media)
  --vocab DIR   versioned inputs                  (default: data/vocab)
  --dict  FILE  tools/bigg_metabolite_dict.json   (formula source of last resort)
  --mass-table FILE  OPTIONAL TSV from the mapping-layer stage. This is the
        agreed hand-off point with the mapper agent. Columns, tab separated,
        with a header line:
            bigg_id  formula  molar_mass_g_per_mol  charge  mass_source
        `molar_mass_g_per_mol` may be empty; `mass_source` is free text recording
        how the mapper resolved it (e.g. "inchi", "bigg_formula", "chebi").
        When the table is absent this stage falls back to computing a molar mass
        from `component.xref.formula`, which is present on 485,554 of 665,582
        components (72.95%) and never disagrees with itself across records
        (0 conflicting formulas for any BiGG id, measured).

WRITES
  <out>/media/<id>.json                    corrected corpus, one file per input
  <out>/reports/concentrations_report.json machine-readable summary
  <out>/reports/quantities.tsv             one row per component that carries a
                                           source amount, with what was derived
                                           from it and why anything was refused

WHAT IT ADDS TO EACH COMPONENT (never removes anything)
  quantity                {value, unit, basis, source_field, verbatim}
                          The amount EXACTLY as the source stated it. Preserved
                          verbatim so any derived number stays auditable.
  quantity_basis          per_litre_medium | per_100g_food | per_g_source_ingredient
                          | physiological_fluid | null
  amount_mmol_per_100g    USDA foods only. A food's nutrient content is an AMOUNT,
                          not a concentration; converting it to mM would require
                          inventing a volume basis that was never measured
                          (NM-11 verification (3), risk (b)). So the molar figure
                          is published on its own honest basis and NOT as mM.
  concentration_mM        Only where the basis genuinely IS per litre of finished
                          medium AND the molar mass of the SAME chemical species
                          is known. Otherwise left untouched / null.
  concentration_status    source_stated | derived | not_derivable
  concentration_source    the field it came from, or null
  concentration_block_reason   why nothing was derived (see BLOCK_REASONS)
  derived_not_sourced     true on every pipeline-invented component, so the
                          34.5% of records that were never observed in any source
                          are explicitly labelled wherever they appear and can be
                          excluded from coverage arithmetic (operator decision:
                          SEGREGATE AND LABEL, never delete).

WHAT IT NEVER TOUCHES
  lower_bound, upper_bound. client/pymediadb/__init__.py:153 builds the COBRApy
  medium straight from abs(lower_bound); silently re-deriving bounds from a
  concentration would change every downstream simulation as an undeclared side
  effect of a data-quality fix (COV-04 risk 3, PROV-09 final trap). Bounds are a
  separate, versioned decision.


ASSERTIONS (the stage exits non-zero if any fails)
  A1  component count is identical per record, in and out
  A2  no lower_bound or upper_bound value changes
  A3  no concentration_mM is ever written as 0.0. A sub-micromolar measurement
      rounded to 0.0 reads to a modeller as "absent from the medium", which is
      worse than null (PROV-13). Underflow -> null + reason.
  A4  no concentration is derived for a `mediadive_salt` component. recipe_g_l
      there is the mass of the PARENT SALT while the component is a dissociated
      ION whose parent identity was discarded at build time
      (build_mediadive_media.py:44-56 keeps `gl` but drops `cname`). Dividing by
      the ion's mass is wrong by the salt/ion ratio, hydration and stoichiometry
      -- so4 96.06 instead of MgSO4.7H2O 246.47 is 2.6x too much sulfate across
      38,363 components (PROV-09 risk 2). Honest null beats a confident number.
  A5  no per-100g food amount is ever written into concentration_mM
  A6  no quantity is derived for a pipeline-invented component
  A7  no derived concentration exceeds the pure-substance molarity of the species
  A8  every non-null concentration_mM carries a concentration_status and source
"""
import json, os, re, sys, glob, collections, copy

STAGE_ID = "50_load_concentrations"
STAGE_VERSION = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# Components the pipeline INVENTED rather than read from a source. 229,509
# component records (34.48%) are of these kinds: hydrolysate approximations and
# complex decompositions plus injected mineral bases. They stay in the corpus
# (operator decision) but they are never a measurement, so no quantity is ever
# derived for them and they are labelled wherever they appear.
INVENTED_METHODS = {
    "hydrolysate_approximation",
    "complex_decomposition",
    "mineral_base",
    "base",
    "base_medium_expansion",
    "usda_mineral",          # injected mineral complement, not a USDA analyte
}

# recipe_g_l on these methods is the mass of a parent salt whose identity the
# builder discarded. See assertion A4.
SALT_METHODS_PARENT_LOST = {"mediadive_salt"}

BLOCK_REASONS = {
    "invented_component": "component was generated by the pipeline, not observed in any source",
    "parent_salt_identity_lost": "recipe_g_l is the parent salt's mass; the salt's identity, hydration and ion stoichiometry were discarded at build time, so the ion molarity cannot be recovered",
    "no_molar_mass": "no molar mass could be resolved for this species",
    "food_amount_no_volume_basis": "a per-100 g food amount is not a concentration; no volume basis was ever measured",
    "per_gram_of_source_ingredient": "amount is per gram of a complex ingredient, and the ingredient's g/L in this medium was not retained",
    "below_representable_precision": "the derived value underflows to zero at 4 significant figures; a measured trace amount must not be published as 0",
    "implausible_exceeds_pure_substance": "the derived value exceeds the molarity of the pure substance, so the source figure is a neat-reagent density or an undiluted stock, not g per litre of finished medium",
    "unrecognised_unit": "the source unit is not in the declared unit table",
    "no_source_amount": "no quantitative field is present on this component",
}

# Pure-substance molarity ceilings (mmol/L) for species whose recipe_g_l is known
# to be a neat-reagent density rather than a per-litre-of-medium mass. Measured
# offenders: methanol 24,717.6 mM from g_l=792 (methanol's density), ethanol
# 20,620.8 mM from g_l=950 (above neat ethanol's 17,100), glycerol 13,573.7 mM
# from g_l=1250 (glycerol's density) -- PROV-09.
PURE_SUBSTANCE_MM = {
    "meoh": 24700.0, "etoh": 17100.0, "glyc": 13700.0, "h2o": 55500.0,
}

_ELEM = re.compile(r"([A-Z][a-z]?)(\d*)")
ATOMIC = {
    "H": 1.008, "D": 2.014, "He": 4.003, "Li": 6.94, "Be": 9.012, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974,
    "S": 32.06, "Cl": 35.45, "Ar": 39.948, "K": 39.098, "Ca": 40.078,
    "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Kr": 83.798, "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224,
    "Nb": 92.906, "Mo": 95.95, "Tc": 98.0, "Ru": 101.07, "Rh": 102.906,
    "Pd": 106.42, "Ag": 107.868, "Cd": 112.414, "In": 114.818, "Sn": 118.710,
    "Sb": 121.760, "Te": 127.60, "I": 126.904, "Xe": 131.293, "Cs": 132.905,
    "Ba": 137.327, "La": 138.905, "W": 183.84, "Pt": 195.084, "Au": 196.967,
    "Hg": 200.592, "Pb": 207.2, "Bi": 208.980, "R": 0.0, "X": 0.0,
}


def molar_mass_from_formula(formula):
    """Return (mass, 'formula') or (None, reason). Refuses generic/polymer formulae."""
    if not formula or not isinstance(formula, str):
        return None, "no_formula"
    f = formula.strip()
    if not f or f.upper() in ("NONE", "NULL"):
        return None, "no_formula"
    # generic / polymeric formulae carry no definite mass
    if re.search(r"[()\[\]*]|R\d|X\b|n\b", f):
        if re.search(r"\bR\d|\(|\)|\[|\]|\*", f):
            return None, "generic_or_polymeric_formula"
    total = 0.0
    consumed = 0
    for sym, cnt in _ELEM.findall(f):
        if not sym:
            continue
        consumed += len(sym) + len(cnt)
        if sym not in ATOMIC:
            return None, "unknown_element:" + sym
        total += ATOMIC[sym] * (int(cnt) if cnt else 1)
    if consumed != len(re.sub(r"[+-]\d*$", "", f)):
        return None, "unparsed_formula"
    if total <= 0:
        return None, "zero_mass"
    return total, "formula"


def sigfig(x, n=4):
    """4 significant figures, NOT 4 decimal places.

    build_mediadive_media.py:48 uses round(x, 4), which maps biotin at
    5e-06 g/L to 0.0 mM. 296 concentration_mM values across 14 files are exactly
    0.0 for precisely this reason and they are real measurements, not absences
    (PROV-13). Significant figures preserve them.
    """
    if x is None:
        return None
    if x == 0:
        return 0.0
    from math import log10, floor
    return float(f"%.{n}g" % x)


# Declared unit table. An unrecognised unit is quarantined, never defaulted.
MASS_UNITS_TO_G = {"g": 1.0, "mg": 1e-3, "ug": 1e-6, "µg": 1e-6, "mcg": 1e-6,
                   "kg": 1e3, "ng": 1e-9}
NON_MASS_UNITS = {"iu", "ne", "α-te", "a-te", "rae", "re", "dfe", "kcal", "kj",
                  "ml", "l"}


class Stage:
    """Holds the molar-mass resolution tables and the per-run tallies.

    Constructed with plain paths so the registered stage entrypoint
    (50_load_concentrations.py) can build it without argparse.
    """

    def __init__(self, dict_path=None, mass_table=None):
        self.mass_table = {}
        self.mass_source = {}
        self.inputs = []
        if mass_table and os.path.exists(mass_table):
            self._load_mass_table(mass_table)
            self.inputs.append(os.path.relpath(mass_table, REPO))
        self.dict_formula = {}
        dict_path = dict_path or os.path.join(REPO, "tools", "bigg_metabolite_dict.json")
        if os.path.exists(dict_path):
            self.inputs.append(os.path.relpath(dict_path, REPO))
            d = json.load(open(dict_path))
            for bid, v in d.items():
                fo = (v.get("xrefs") or {}).get("formula")
                if fo:
                    self.dict_formula[bid] = fo
        self.stats = collections.Counter()
        self.block = collections.Counter()
        self.rows = []
        self.failures = []

    def _load_mass_table(self, path):
        with open(path) as fh:
            hdr = None
            for ln in fh:
                if ln.startswith("#") or not ln.strip():
                    continue
                p = ln.rstrip("\n").split("\t")
                if hdr is None:
                    hdr = p
                    continue
                r = dict(zip(hdr, p))
                m = r.get("molar_mass_g_per_mol", "").strip()
                if m:
                    try:
                        self.mass_table[r["bigg_id"]] = float(m)
                        self.mass_source[r["bigg_id"]] = r.get("mass_source") or "mass_table"
                    except ValueError:
                        pass
                elif r.get("formula"):
                    mm, why = molar_mass_from_formula(r["formula"])
                    if mm:
                        self.mass_table[r["bigg_id"]] = mm
                        self.mass_source[r["bigg_id"]] = "mass_table_formula"

    def molar_mass(self, comp):
        """Resolve a molar mass for THIS component's own species, with provenance."""
        bid = comp.get("bigg_metabolite")
        if bid in self.mass_table:
            return self.mass_table[bid], self.mass_source.get(bid, "mass_table")
        fo = (comp.get("xref") or {}).get("formula")
        mm, why = molar_mass_from_formula(fo)
        if mm:
            return mm, "component_xref_formula"
        fo2 = self.dict_formula.get(bid)
        if fo2 and fo2 != fo:
            mm, why = molar_mass_from_formula(fo2)
            if mm:
                return mm, "bigg_metabolite_dict_formula"
        return None, why or "no_formula"

    # ---- the per-component transform -------------------------------------
    def transform_component(self, rec_id, c):
        method = c.get("mapping_method")
        invented = method in INVENTED_METHODS
        c["derived_not_sourced"] = bool(invented)

        stated = c.get("concentration_mM")
        # An existing 0.0 is a rounding artifact of a real measurement, never an
        # absence. Clear it and say so rather than shipping a confident zero.
        if stated == 0.0:
            c["concentration_mM"] = None
            c["concentration_status"] = "not_derivable"
            c["concentration_source"] = None
            c["concentration_block_reason"] = "below_representable_precision"
            self.block["below_representable_precision"] += 1
            self.stats["cleared_zero_concentration"] += 1
            stated = None

        # 1. locate a verbatim source amount, if any
        q = None
        if c.get("recipe_g_l") is not None:
            q = {"value": c["recipe_g_l"], "unit": "g/L", "basis": "per_litre_medium",
                 "source_field": "recipe_g_l"}
        elif c.get("usda_amount") is not None:
            q = {"value": c["usda_amount"], "unit": c.get("usda_unit"),
                 "basis": "per_100g_food", "source_field": "usda_amount"}
        elif c.get("foodb_content") is not None:
            q = {"value": c["foodb_content"], "unit": c.get("foodb_unit"),
                 "basis": "per_100g_food", "source_field": "foodb_content"}
        elif c.get("mg_per_g_source") is not None:
            q = {"value": c["mg_per_g_source"], "unit": "mg/g",
                 "basis": "per_g_source_ingredient", "source_field": "mg_per_g_source"}
        elif c.get("paper_amount") is not None:
            q = {"value": c["paper_amount"], "unit": None,
                 "basis": None, "source_field": "paper_amount"}
        elif c.get("amount") is not None:
            q = {"value": c["amount"], "unit": None, "basis": None,
                 "source_field": "amount"}

        if q is not None:
            q["verbatim"] = q["value"]
            c["quantity"] = q
            c["quantity_basis"] = q["basis"]
            self.stats["components_with_source_amount"] += 1
        else:
            c["quantity"] = None
            c["quantity_basis"] = None

        # 2. an already-stated concentration keeps its provenance and is not
        #    re-derived -- but it IS plausibility-checked. Nulling it would hide
        #    a live upstream bug (PROV-13 risk 1), so instead the number carries
        #    its own warning: 69 components exceed 1 M and 18 exceed the molarity
        #    of the pure substance, because a neat-reagent density (ethanol 950
        #    g/L, methanol 792, glycerol 1250) or an undiluted trace stock was
        #    read as grams per litre of finished medium (PROV-09).
        if stated is not None:
            c["concentration_mM"] = sigfig(stated)
            c["concentration_status"] = "source_stated"
            c.setdefault("concentration_source",
                         c.get("mapping_method") or "source_stated")
            c["concentration_block_reason"] = None
            ceiling = PURE_SUBSTANCE_MM.get(c.get("bigg_metabolite"))
            if ceiling and c["concentration_mM"] > ceiling:
                c["concentration_plausibility"] = "implausible_exceeds_pure_substance"
                c["concentration_plausibility_ceiling_mM"] = ceiling
                self.stats["source_stated_implausible"] += 1
            elif c["concentration_mM"] > 1000.0:
                c["concentration_plausibility"] = "above_1M_review"
                self.stats["source_stated_above_1M"] += 1
            self.stats["concentration_source_stated"] += 1
            return c

        # 3. decide whether anything can honestly be derived
        reason = None
        if invented:
            reason = "invented_component"
        elif q is None:
            reason = "no_source_amount"
        elif method in SALT_METHODS_PARENT_LOST:
            reason = "parent_salt_identity_lost"
        elif q["basis"] == "per_100g_food":
            reason = "food_amount_no_volume_basis"
        elif q["basis"] == "per_g_source_ingredient":
            reason = "per_gram_of_source_ingredient"
        elif q["basis"] is None:
            reason = "unrecognised_unit"

        if reason is None:
            # per_litre_medium with a real chemical identity: derive
            mm, msrc = self.molar_mass(c)
            if mm is None:
                reason = "no_molar_mass"
            else:
                mM = sigfig(float(q["value"]) / mm * 1000.0)
                ceiling = PURE_SUBSTANCE_MM.get(c.get("bigg_metabolite"))
                if mM == 0.0:
                    reason = "below_representable_precision"
                elif ceiling and mM > ceiling:
                    reason = "implausible_exceeds_pure_substance"
                else:
                    c["concentration_mM"] = mM
                    c["concentration_status"] = "derived"
                    c["concentration_source"] = q["source_field"] + "+" + msrc
                    c["concentration_block_reason"] = None
                    self.stats["concentration_derived"] += 1
                    self._row(rec_id, c, q, mM, None)
                    return c

        c["concentration_mM"] = None
        c["concentration_status"] = "not_derivable"
        c["concentration_source"] = None
        c["concentration_block_reason"] = reason
        self.block[reason] += 1

        # USDA foods: publish the molar amount on its OWN honest basis
        if reason == "food_amount_no_volume_basis" and not invented:
            mm, msrc = self.molar_mass(c)
            unit = (q.get("unit") or "").strip().lower()
            if mm and unit in MASS_UNITS_TO_G:
                grams = float(q["value"]) * MASS_UNITS_TO_G[unit]
                v = sigfig(grams / mm * 1000.0)
                if v and v > 0:
                    c["amount_mmol_per_100g"] = v
                    c["amount_basis"] = "per_100g_food"
                    c["amount_source"] = q["source_field"] + "+" + msrc
                    self.stats["amount_mmol_per_100g_derived"] += 1
            elif unit in NON_MASS_UNITS:
                c["amount_block_reason"] = "nutritional_equivalence_or_non_mass_unit"
                self.stats["non_mass_unit"] += 1

        if q is not None:
            self._row(rec_id, c, q, None, reason)
        return c

    def _row(self, rec_id, c, q, mM, reason):
        self.rows.append([
            rec_id, c.get("exchange"), c.get("bigg_metabolite"),
            c.get("mapping_method"), str(c.get("derived_not_sourced")),
            str(q.get("value")), str(q.get("unit")), str(q.get("basis")),
            "" if mM is None else str(mM),
            "" if c.get("amount_mmol_per_100g") is None else str(c.get("amount_mmol_per_100g")),
            reason or "",
        ])

    # ---- record level -----------------------------------------------------
    def transform_record(self, d):
        before = [(c.get("lower_bound"), c.get("upper_bound")) for c in d.get("components") or []]
        n_before = len(d.get("components") or [])
        for c in d.get("components") or []:
            self.transform_component(d.get("id"), c)
        comps = d.get("components") or []
        # A1 / A2
        if len(comps) != n_before:
            self.failures.append(("A1", d.get("id"), "component count changed"))
        after = [(c.get("lower_bound"), c.get("upper_bound")) for c in comps]
        if after != before:
            self.failures.append(("A2", d.get("id"), "a bound changed"))

        n_inv = sum(1 for c in comps if c.get("derived_not_sourced"))
        n_conc = sum(1 for c in comps if c.get("concentration_mM") is not None)
        n_amt = sum(1 for c in comps if c.get("quantity"))
        d["quantitation"] = {
            "n_components": len(comps),
            "n_components_sourced": len(comps) - n_inv,
            "n_components_pipeline_derived": n_inv,
            "n_with_source_amount": n_amt,
            "n_with_concentration_mM": n_conc,
            "pct_with_concentration_mM": round(100.0 * n_conc / len(comps), 2) if comps else None,
            "quantitative_signature": self.quant_signature(comps),
            "stage": STAGE_ID,
            "stage_version": STAGE_VERSION,
        }
        return d

    @staticmethod
    def quant_signature(comps):
        """A composition fingerprint that INCLUDES the verbatim amounts.

        The exchange-set-only fingerprint collapses 13,515 records onto 7,923
        distinct compositions and makes 5,592 records look like duplicates of one
        another (NM-15). Most of that collapse is an artifact of throwing the
        measured amounts away at projection time, not of the media being the same.
        """
        import hashlib
        key = sorted(
            (c.get("exchange"),
             c.get("lower_bound"), c.get("upper_bound"),
             c.get("concentration_mM"),
             (c.get("quantity") or {}).get("value"),
             (c.get("quantity") or {}).get("unit"),
             (c.get("quantity") or {}).get("basis"))
            for c in comps)
        return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # ---- assertions -------------------------------------------------------
    def assert_all(self, records):
        f = self.failures
        for d in records:
            for c in d.get("components") or []:
                cm = c.get("concentration_mM")
                st = c.get("concentration_status")
                if cm == 0.0:
                    f.append(("A3", d["id"], c.get("exchange") + " concentration_mM == 0.0"))
                if st == "derived":
                    if c.get("mapping_method") in SALT_METHODS_PARENT_LOST:
                        f.append(("A4", d["id"], c.get("exchange") + " derived from a parent-salt-lost component"))
                    if (c.get("quantity") or {}).get("basis") == "per_100g_food":
                        f.append(("A5", d["id"], c.get("exchange") + " per-100g food amount written into concentration_mM"))
                    if c.get("derived_not_sourced"):
                        f.append(("A6", d["id"], c.get("exchange") + " quantity derived for an invented component"))
                    ceil = PURE_SUBSTANCE_MM.get(c.get("bigg_metabolite"))
                    if ceil and cm and cm > ceil:
                        f.append(("A7", d["id"], c.get("exchange") + " exceeds pure-substance molarity"))
                if cm is not None and (not st or (st == "derived" and not c.get("concentration_source"))):
                    f.append(("A8", d["id"], c.get("exchange") + " concentration without status/source"))
        return f
