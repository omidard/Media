#!/usr/bin/env python3
"""STAGE: remap_components -- honest evidence tiers and chemistry corrections.

CONTRACT
========
READS
  data/media/*.json                            the current corpus (the SOLE surviving
                                               copy -- the raw builder inputs are gone,
                                               see audit PIPE-01)
  tools/bigg_metabolite_dict.json              BiGG universal metabolites + chemistry
  tools/bigg_reverse_index.json                name / xref reverse indices
  tools/curation/metabolite_corrections.tsv    reviewed corrections (required)

WRITES (never into data/media/ unless --out says so explicitly)
  <out>/media/*.json                           corrected corpus
  <out>/component_remap_ledger.tsv.gz          one row per CHANGED component
  <out>/tier_distribution.json                 tier counts, before and after
  <out>/review_queue.tsv                       corrections the mapper proposes but
                                               that fall outside the auto-apply guard
  <out>/refusals.tsv                           every mapping the mapper refused, with
                                               the reason -- the ambiguity list

WHAT IT DOES, in order, per component
  1. TIER  -- assign evidence_tier from the recorded mapping_method
              (tools/evidence_tiers.METHOD_TIERS). No identity changes.
  2. PROVENANCE -- split the single `xref` block into `target_xref` (what the chosen
              BiGG id is) and `source_xref` (what the SOURCE supplied, or null), add
              `match_key` (null unless the mapping was actually decided by an
              identifier), and add `source_name` where the source string is still
              recoverable. `xref` is retained as a deprecated alias for one release.
  3. CURATED -- apply tools/curation/metabolite_corrections.tsv
              (retarget | retier | unmap | mark_mixture).
  4. STEREO -- re-derive name-routed components with the corrected mapper and apply
              the result ONLY when it stays inside the same stereo family
              (ser__D -> ser__L). Anything else is written to review_queue.tsv and
              NOT applied.
  5. COUNTS -- recompute n_mapped / n_in_biggr honestly and add
              n_observed / n_derived / pct_covered_observed, so coverage arithmetic
              stops counting pipeline-invented rows as covered.

WHAT IT DELIBERATELY DOES NOT DO
  * It does not blanket re-run the mapper over every component. 87.6% of components
    carry the TARGET's BiGG name rather than the source string, so re-mapping them
    would re-read the pipeline's own answer, and re-running over the ~18k rows whose
    names do resolve would demote InChIKey-derived facts to name guesses to fix ~282
    rows (audit MAP-03, risk 3).
  * It does not re-map salt-dissociation products. One source name ("Sodium
    chloride") legitimately produces two components (na1, cl); re-mapping either
    row's name yields one ion and would silently destroy the dissociation. Identity-
    level dissociation was measured sound at 3 incomplete of 5,529 (audit MAP-14).
  * It does not delete pipeline-derived components. Operator decision: segregate and
    label. They are tiered `derived_component` and excluded from coverage.
  * It does not touch bounds, concentrations, names of media, licences or citations.
    Flux-consequential findings are flagged in the ledger for those workstreams.

ASSERTIONS (the stage aborts rather than writing a corrupt corpus)
  A1 every correction row carries a non-empty chemical justification
  A2 every emitted bigg_metabolite is a key of tools/bigg_metabolite_dict.json
  A3 every emitted exchange equals EX_<bigg_metabolite>_e, or bigg_metabolite is null
  A4 evidence_tier is drawn from tools/evidence_tiers.TIER_ORDER
  A5 match_key is null for every name-based tier -- a name is not an identifier
  A6 in_biggr is read from the dictionary, never carried from the input record
  A7 no component's tier is RAISED relative to the tier its method supports,
     except by an explicit curated correction row
  A8 the component count per medium is unchanged (this stage relabels and
     retargets; it never adds or drops rows)
  A9 a pipeline-generated component is never relabelled out of `derived_component`,
     whatever a correction says about its identity

USAGE
  python3 tools/stages/remap_components.py --sample 200 --out /tmp/stage_sample
  python3 tools/stages/remap_components.py --report-only          # tiers, no writing
  python3 tools/stages/remap_components.py --out build/remapped   # full corpus
"""
import argparse, csv, gzip, json, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import chem_identity as CHEM                                    # noqa: E402
from evidence_tiers import (METHOD_TIERS, TIER_ORDER, TIER_RANK,  # noqa: E402
                            NON_OBSERVED_TIERS, tier_for_method)
from map_metabolite import Mapper, TIER_CONFIDENCE               # noqa: E402

MEDIA_DIR = os.path.join(REPO, "data", "media")
CORRECTIONS = os.path.join(TOOLS, "curation", "metabolite_corrections.tsv")

# Methods whose stored `name` is a SALT that legitimately produced several ion
# components. Never re-derived: one name maps to one ion, which would delete the rest.
SALT_METHODS = {"mediadive_salt", "mediadb_salt_dissociation", "salt_dissociation_remap",
                "paper_salt_dissociation", "remap_salt_dissociation", "salt_parse_remap"}

# Reverse of the hand-typed USDA tables at tools/build_usda_media_v2.py:19-34, used to
# recover the source nutrient name the builder overwrote with the BiGG display name.
# Where two nutrients share a target the source is genuinely UNRECOVERABLE and both
# candidates are recorded rather than one being picked.
USDA_NMAP = {
    "Tryptophan": "trp__L", "Threonine": "thr__L", "Isoleucine": "ile__L", "Leucine": "leu__L",
    "Lysine": "lys__L", "Methionine": "met__L", "Cystine": "cys__L", "Cysteine": "cys__L",
    "Phenylalanine": "phe__L", "Tyrosine": "tyr__L", "Valine": "val__L", "Arginine": "arg__L",
    "Histidine": "his__L", "Alanine": "ala__L", "Aspartic acid": "asp__L",
    "Glutamic acid": "glu__L", "Glycine": "gly", "Proline": "pro__L", "Serine": "ser__L",
    "Asparagine": "asn__L", "Glutamine": "gln__L", "Glucose": "glc__D", "Fructose": "fru",
    "Sucrose": "sucr", "Galactose": "gal", "Maltose": "malt", "Lactose": "lcts",
    "SFA 16:0": "hdca", "SFA 18:0": "ocdca", "SFA 14:0": "ttdca", "SFA 12:0": "ddca",
    "SFA 10:0": "dca", "SFA 8:0": "octa", "SFA 6:0": "hxa",
    "MUFA 18:1 c": "ocdcea", "MUFA 18:1": "ocdcea", "PUFA 18:2 n-6 c,c": "lnlc",
    "PUFA 18:2 c": "lnlc", "PUFA 18:3 n-3 c,c,c (ALA)": "lnlnca", "PUFA 18:3 c": "lnlnca",
    "PUFA 20:4": "arachd", "PUFA 20:4c": "arachd",
    "Thiamin": "thm", "Riboflavin": "ribflv", "Niacin": "nac", "Pantothenic acid": "pnto__R",
    "Vitamin B-6": "pydxn", "Folate, total": "fol", "Vitamin B-12": "cbl1",
    "Vitamin C, total ascorbic acid": "ascb__L", "Biotin": "btn",
    "Vitamin E (alpha-tocopherol)": "avite1", "Choline, total": "chol", "Retinol": "retinol",
}
USDA_MINMAP = {
    "Potassium, K": "k", "Zinc, Zn": "zn2", "Magnesium, Mg": "mg2", "Phosphorus, P": "pi",
    "Calcium, Ca": "ca2", "Copper, Cu": "cu2", "Iron, Fe": "fe2", "Manganese, Mn": "mn2",
    "Sodium, Na": "na1", "Molybdenum, Mo": "mobd", "Selenium, Se": "slnt",
}


def _reverse(table):
    out = collections.defaultdict(list)
    for k, v in table.items():
        out[v].append(k)
    return dict(out)


USDA_REV = {"usda_nutrient": _reverse(USDA_NMAP), "usda_mineral": _reverse(USDA_MINMAP)}

# Identifier fields a source could legitimately have supplied.
XREF_FIELDS = ("inchikey", "chebi", "kegg", "hmdb", "mnx", "seed")
# mapping_method -> the identifier field that actually decided the mapping.
XREF_METHOD_FIELD = {"inchikey": "inchikey", "inchikey_remap": "inchikey",
                     "chebi": "chebi", "chebi_remap": "chebi",
                     "kegg": "kegg", "kegg_remap": "kegg",
                     "hmdb": "hmdb", "hmdb_remap": "hmdb"}


# ---------------------------------------------------------------------------
# corrections table
# ---------------------------------------------------------------------------

def load_corrections(path=CORRECTIONS):
    rows = []
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    for r in csv.DictReader(lines, delimiter="\t"):
        if not (r.get("correction_id") or "").strip():
            continue
        # A1: a correction without a written chemical justification is not a
        # correction, it is another undocumented decision.
        if not (r.get("chemistry") or "").strip():
            raise SystemExit(f"A1 FAILED: correction {r['correction_id']} has no chemistry "
                             "justification")
        if r["action"] not in ("retarget", "retier", "unmap", "mark_mixture"):
            raise SystemExit(f"A1 FAILED: correction {r['correction_id']} has unknown action "
                             f"{r['action']!r}")
        if (r.get("evidence_tier") or "").strip() and r["evidence_tier"] not in TIER_ORDER:
            raise SystemExit(f"A4 FAILED: correction {r['correction_id']} names unknown tier "
                             f"{r['evidence_tier']!r}")
        r["_method_rx"] = None if r["applies_to_method"].strip() == "*" else \
            re.compile(r["applies_to_method"].strip())
        # CASE-SENSITIVE by design: 'CO2' and 'Co2+' differ only in case.
        r["_value_rx"] = re.compile(r["match_value"]) if r["match_field"] == "component_name_regex" else None
        r["_proxy"] = [p for p in (r.get("proxy_for") or "").split("|") if p]
        rows.append(r)
    return rows


def correction_matches(rule, comp):
    if rule["_method_rx"] and not rule["_method_rx"].fullmatch(comp.get("mapping_method") or ""):
        return False
    cur = (rule.get("current_bigg") or "").strip()
    if cur and (comp.get("bigg_metabolite") or "") != cur:
        return False
    f = rule["match_field"]
    if f == "component_name_regex":
        return bool(rule["_value_rx"].search(comp.get("name") or ""))
    if f == "component_name_exact":
        return (comp.get("name") or "") == rule["match_value"]
    if f == "bigg_id":
        return (comp.get("bigg_metabolite") or "") == rule["match_value"]
    raise SystemExit(f"unknown match_field {f!r} in correction {rule['correction_id']}")


# ---------------------------------------------------------------------------
# per-component transform
# ---------------------------------------------------------------------------

class Stage:
    def __init__(self, corrections=None, mapper=None):
        self.mapper = mapper or Mapper()
        self.dict = self.mapper.dict
        self.corrections = corrections if corrections is not None else load_corrections()
        self.ledger = []       # changed components
        self.review = []       # proposed but not auto-applied
        self.refusals = []
        self.tier_before = collections.Counter()
        self.tier_after = collections.Counter()
        self.actions = collections.Counter()
        self._remap_cache = {}

    # -- helpers ------------------------------------------------------------
    def _remap(self, name):
        if name not in self._remap_cache:
            self._remap_cache[name] = self.mapper.map(name=name, strict=True)
        return self._remap_cache[name]

    def _source_name(self, comp):
        """The SOURCE's own string for this component, or None when destroyed.

        Returns (source_name, ambiguous_candidates). The USDA builders overwrote the
        source nutrient name with the BiGG display name, so it is reconstructed from
        the reverse of the hand-typed table -- and where two nutrients share one
        target, BOTH are recorded rather than one being chosen.
        """
        meth = comp.get("mapping_method") or ""
        rev = USDA_REV.get(meth)
        if rev:
            cands = rev.get(comp.get("bigg_metabolite") or "", [])
            if len(cands) == 1:
                return cands[0], None
            if len(cands) > 1:
                return None, cands
            return None, None
        # Everywhere else the stored name is the source string unless it is byte-equal
        # to the chosen id's BiGG display name, in which case the source string is gone.
        nm = comp.get("name")
        tgt = (self.dict.get(comp.get("bigg_metabolite") or "", {}) or {}).get("name")
        if nm and tgt and nm.strip().lower() == str(tgt).strip().lower():
            return None, None
        return nm, None

    # -- the transform ------------------------------------------------------
    def transform(self, comp, medium_id, idx):
        out = dict(comp)
        meth = comp.get("mapping_method") or ""
        old_bigg = comp.get("bigg_metabolite")
        base_tier, remappable, method_note = tier_for_method(meth)
        self.tier_before[base_tier] += 1
        tier = base_tier
        notes = []
        action = "tier_only"

        # ---- 2. provenance split ------------------------------------------
        xr = comp.get("xref") or {}
        out["target_xref"] = xr
        out["xref"] = xr                      # deprecated alias, one release
        field = XREF_METHOD_FIELD.get(meth)
        if field and xr.get(field):
            # The source supplied this identifier and it is what resolved the mapping;
            # the stored value is faithful because the reverse index matched on it.
            out["source_xref"] = {field: xr[field]}
            out["match_key"] = xr[field]
            out["match_field"] = field
        else:
            # A6-adjacent honesty rule: the xref block was copied from the mapping
            # TARGET after the id was picked by name. It is not evidence and must not
            # be presented as any.
            out["source_xref"] = None
            out["match_key"] = None
            out["match_field"] = None
            if xr:
                out["target_xref_note"] = ("these cross-references describe the BiGG id "
                                           "that was chosen; they were not used to choose "
                                           "it and cannot contradict it")
        src_name, src_ambig = self._source_name(comp)
        out["source_name"] = src_name
        if src_ambig:
            out["source_name_candidates"] = src_ambig
            notes.append("source name destroyed at build time; it was one of "
                         + " / ".join(src_ambig) + " and the two collide on this exchange")
        if method_note:
            notes.append(method_note)

        # ---- 3. curated corrections ---------------------------------------
        applied = []
        for rule in self.corrections:
            if not correction_matches(rule, comp):
                continue
            act = rule["action"]
            # A mixture verdict is TERMINAL. Once a component has been established as
            # an undefined mixture or as having no defensible target, a later rule must
            # not quietly give it an exchange again: a multi-compound vitamin-solution
            # string that happens to name cobalamin is still a mixture, not cobalamin.
            if action in ("curated_mixture", "curated_unmap") and act in ("retarget", "retier"):
                notes.append(f"[{rule['correction_id']}] not applied: this component is already "
                             "recorded as having no defensible single target")
                continue
            applied.append(rule["correction_id"])
            if act == "retarget":
                new = rule["target_bigg"]
                if new not in self.dict:
                    raise SystemExit(f"A2 FAILED: correction {rule['correction_id']} targets "
                                     f"{new!r}, absent from bigg_metabolite_dict.json")
                out["bigg_metabolite"] = new
                out["exchange"] = f"EX_{new}_e"
                out["target_xref"] = self.dict[new].get("xrefs", {})
                out["xref"] = out["target_xref"]
                # `name` stays the source's own string. Overwriting it with the BiGG
                # display name is the defect that destroyed the source label on 87.6%
                # of components and made every mapping un-contradictable.
                out["target_name"] = self.dict[new].get("name", new)
                action = "curated_retarget"
            elif act in ("unmap", "mark_mixture"):
                out["bigg_metabolite"] = None
                out["exchange"] = None
                out["target_xref"] = {}
                out["xref"] = {}
                action = "curated_unmap" if act == "unmap" else "curated_mixture"
            else:
                action = "curated_retier"
            proposed = rule["evidence_tier"] or tier
            # A9 -- a correction may LOWER a tier freely (that is the honest direction),
            # but it may only RAISE one when it actually changed the identity, and it can
            # never lift a component out of `derived_component`: being pipeline-generated
            # is a fact about provenance, not a mapping-quality claim, so a fabricated row
            # must stay labelled fabricated even after its id is corrected.
            if base_tier == "derived_component":
                proposed = "derived_component"
                notes.append("identity corrected, but this component was generated by the "
                             "pipeline and was never stated by the cited source, so it stays "
                             "labelled derived")
            elif act == "retarget" and out.get("bigg_metabolite") == old_bigg:
                # The correction confirmed the id that was already there. A no-op on
                # identity must be a no-op on the tier too: this row's evidence is
                # whatever originally resolved it, and a confirmation is not new
                # evidence. Without this, a guard rule silently restamps a component
                # that a source InChIKey had already resolved.
                proposed = tier
                notes.append(f"[{rule['correction_id']}] confirmed the existing "
                             f"identity; evidence tier unchanged")
            elif TIER_RANK[proposed] < TIER_RANK[tier] and act != "retarget":
                proposed = tier
            tier = proposed
            if rule["_proxy"]:
                out["proxy_for"] = rule["_proxy"]
            if rule.get("source_name") and not out.get("source_name"):
                out["source_name"] = rule["source_name"]
            notes.append(f"[{rule['correction_id']}] {rule['chemistry']}")
            out.setdefault("curation_refs", []).append(rule["correction_id"])
            if rule.get("flux_consequential") == "yes":
                out["flux_consequential"] = True
            if rule.get("breaking_id_change") == "yes":
                out["breaking_id_change"] = True

        # ---- 4. targeted stereo / chemistry re-derivation ------------------
        if not applied and remappable and meth not in SALT_METHODS and comp.get("name"):
            r = self._remap(comp["name"])
            new = r.get("bigg_metabolite") if r else None
            if r and r.get("evidence_tier") == "unmapped":
                self.refusals.append((medium_id, idx, comp.get("name"), old_bigg,
                                      r.get("refusal_kind"), r.get("mapping_note")))
            if new and old_bigg and new == old_bigg:
                # The re-derivation lands on the same id, so the stored name really is
                # the evidence and the mapper's own tier is the honest one for this row.
                if r["evidence_tier"] != tier:
                    notes.append(f"tier re-derived from the source name by the corrected "
                                 f"mapper ({base_tier} -> {r['evidence_tier']})")
                    action = "tier_rederived"
                tier = r["evidence_tier"]
                out["matched_name"] = r.get("matched_name")
                out["match_field"] = r.get("match_field")
            if new and old_bigg and new != old_bigg:
                same_family = (CHEM.id_stereo_base(new) == CHEM.id_stereo_base(old_bigg))
                if same_family:
                    # A stereo correction inside one compound family: L-serine was
                    # delivering D-serine. Safe to apply -- it cannot change WHICH
                    # compound the row is, only which enantiomer.
                    out["bigg_metabolite"] = new
                    out["exchange"] = f"EX_{new}_e"
                    out["target_xref"] = self.dict[new].get("xrefs", {})
                    out["xref"] = out["target_xref"]
                    out["target_name"] = self.dict[new].get("name", new)
                    tier = r["evidence_tier"]
                    action = "stereo_correction"
                    declared = CHEM.stereo_of_name(comp["name"])
                    if declared:
                        notes.append(f"stereochemistry corrected {old_bigg} -> {new}: the source "
                                     f"name declares {declared}- and the shipped id was the "
                                     f"opposite enantiomer")
                    else:
                        notes.append(f"stereochemistry corrected {old_bigg} -> {new}: the source "
                                     f"name declares no enantiomer, and the shipped id was chosen "
                                     f"by index insertion order. {new} is the curated default for "
                                     f"this compound (tools/map_metabolite.py alias table) and is "
                                     f"recorded as a convention, not as a determination")
                    out["flux_consequential"] = True
                else:
                    # A different compound entirely. Never applied silently.
                    self.review.append((medium_id, idx, comp.get("name"), old_bigg, new,
                                        r.get("evidence_tier"), r.get("mapping_note") or "",
                                        "re-derivation proposes a different compound, not a "
                                        "different enantiomer; needs a curator decision"))

        # ---- 4b. BiGG namespace generation -----------------------------------
        # cdm_lactobacillaceae ships 20 pre-2018 single-underscore ids (glc_D,
        # pnto_R, ascb_L ...) flagged in_biggr:true although none exists in the
        # dictionary, and asserts pct_covered 100. Migrate ONLY when the modern id
        # exists AND the legacy id does not, so the legitimate BiGG ids that also
        # contain a single underscore -- ala_B, acon_C, acon_T, fru_B, fdp_B, g1p_B,
        # glc_D_B -- are provably untouched. The published id is preserved, because
        # the record's own provenance says it was chosen to match LactoPanGEM.
        bid = out.get("bigg_metabolite")
        if bid and bid not in self.dict:
            modern = re.sub(r"_([DLR])$", r"__\1", bid)
            if modern != bid and modern in self.dict:
                out["legacy_bigg_metabolite"] = bid
                out["legacy_exchange"] = out.get("exchange")
                out["bigg_namespace_generation"] = 2
                out["bigg_metabolite"] = modern
                out["exchange"] = f"EX_{modern}_e"
                out["target_xref"] = self.dict[modern].get("xrefs", {})
                out["xref"] = out["target_xref"]
                out["target_name"] = self.dict[modern].get("name", modern)
                action = "bigg_generation_migration"
                notes.append(f"BiGG namespace generation 1 id {bid} migrated to {modern}; "
                             f"the published id is retained in legacy_exchange because the "
                             f"record's provenance states it was chosen to match LactoPanGEM")
                self.ledger_note_migration = True

        # ---- finalise ------------------------------------------------------
        bid = out.get("bigg_metabolite")
        if bid:
            if bid not in self.dict:
                raise SystemExit(f"A2 FAILED: {medium_id}[{idx}] emits bigg_metabolite {bid!r}, "
                                 "absent from tools/bigg_metabolite_dict.json")
            if out.get("exchange") != f"EX_{bid}_e":
                raise SystemExit(f"A3 FAILED: {medium_id}[{idx}] exchange {out.get('exchange')!r} "
                                 f"does not match EX_{bid}_e")
            out["in_biggr"] = bool(self.dict[bid].get("in_biggr"))     # A6
        else:
            out["in_biggr"] = False
            if tier not in ("unmapped", "unmappable_mixture", "non_bigg_fallback"):
                tier = "unmapped"
        if meth in ("modelseed_fallback", "kegg_fallback", "metanetx_fallback"):
            out["exchange"] = comp.get("exchange")     # keep the namespaced id
            out["namespace"] = comp.get("namespace") or ("modelseed" if "seed" in meth else
                                                         "kegg" if "kegg" in meth else "metanetx")
            notes.append("this exchange id is NOT a BiGG identifier and no BiGG model "
                         "will accept it")
        if tier not in TIER_ORDER:
            raise SystemExit(f"A4 FAILED: {medium_id}[{idx}] tier {tier!r}")
        if tier in ("exact_name", "name_table", "fuzzy_name", "class_proxy") and out.get("match_key"):
            raise SystemExit(f"A5 FAILED: {medium_id}[{idx}] tier {tier} carries a match_key; "
                             "a name is not an identifier")
        if TIER_RANK[tier] < TIER_RANK[base_tier] and not applied and \
                action not in ("stereo_correction", "tier_rederived", "bigg_generation_migration"):
            raise SystemExit(f"A7 FAILED: {medium_id}[{idx}] tier raised {base_tier} -> {tier} "
                             "without a curated correction or a re-derivation")
        if base_tier == "derived_component" and tier != "derived_component":
            raise SystemExit(f"A9 FAILED: {medium_id}[{idx}] a pipeline-generated component "
                             f"was relabelled {tier}")

        if bid:
            out["target_name"] = self.dict[bid].get("name", bid)
        out["evidence_tier"] = tier
        out["mapping_confidence"] = TIER_CONFIDENCE.get(tier, "inferred")
        out["source_observed"] = tier not in NON_OBSERVED_TIERS
        if notes:
            out["mapping_note"] = "; ".join(notes)
        self.tier_after[tier] += 1
        self.actions[action] += 1
        if action != "tier_only" or tier != base_tier or \
                comp.get("mapping_confidence") != out["mapping_confidence"]:
            self.ledger.append({
                "medium_id": medium_id, "component_index": idx,
                "component_name": comp.get("name"), "source_name": out.get("source_name"),
                "mapping_method": meth,
                "old_bigg": old_bigg or "", "new_bigg": out.get("bigg_metabolite") or "",
                "old_exchange": comp.get("exchange") or "",
                "new_exchange": out.get("exchange") or "",
                "old_confidence": comp.get("mapping_confidence") or "",
                "new_confidence": out["mapping_confidence"],
                "old_tier_implied": base_tier, "new_tier": tier,
                "action": action,
                "corrections": ",".join(applied),
                "flux_consequential": "yes" if out.get("flux_consequential") else "no",
                "note": out.get("mapping_note", ""),
            })
        return out

    # -- medium level -------------------------------------------------------
    def transform_medium(self, med):
        comps = med.get("components") or []
        n_in = len(comps)
        new = [self.transform(c, med.get("id"), i) for i, c in enumerate(comps)]
        if len(new) != n_in:
            raise SystemExit("A8 FAILED: component count changed")   # A8
        med = dict(med)
        med["components"] = new
        med["n_components"] = len(new)
        # honest counters
        med["n_mapped"] = sum(1 for c in new if c.get("bigg_metabolite"))
        med["n_in_biggr"] = sum(1 for c in new if c.get("in_biggr"))
        med["n_observed"] = sum(1 for c in new if c.get("source_observed"))
        med["n_derived"] = sum(1 for c in new if c.get("evidence_tier") == "derived_component")
        med["n_unmappable"] = sum(1 for c in new
                                  if c.get("evidence_tier") in ("unmappable_mixture", "unmapped"))
        obs = med["n_observed"]
        med["pct_covered_observed"] = (
            round(100.0 * sum(1 for c in new
                              if c.get("source_observed") and c.get("bigg_metabolite")) / obs, 2)
            if obs else None)
        med["tier_counts"] = dict(collections.Counter(c["evidence_tier"] for c in new))
        med["mapping_schema_version"] = "2.0-evidence-tiers"
        return med


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run(files, out_dir, stage, write=True):
    if write:
        os.makedirs(os.path.join(out_dir, "media"), exist_ok=True)
    for f in files:
        with open(f, encoding="utf-8") as fh:
            med = json.load(fh)
        med = stage.transform_medium(med)
        if write:
            with open(os.path.join(out_dir, "media", os.path.basename(f)), "w",
                      encoding="utf-8") as fh:
                json.dump(med, fh, ensure_ascii=False)
    return stage


def write_reports(stage, out_dir, n_files):
    os.makedirs(out_dir, exist_ok=True)
    cols = ["medium_id", "component_index", "component_name", "source_name", "mapping_method",
            "old_bigg", "new_bigg", "old_exchange", "new_exchange", "old_confidence",
            "new_confidence", "old_tier_implied", "new_tier", "action", "corrections",
            "flux_consequential", "note"]
    with gzip.open(os.path.join(out_dir, "component_remap_ledger.tsv.gz"), "wt",
                   encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in stage.ledger:
            w.writerow({k: str(v).replace("\t", " ").replace("\n", " ") for k, v in r.items()})
    with open(os.path.join(out_dir, "review_queue.tsv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["medium_id", "component_index", "component_name", "current_bigg",
                    "proposed_bigg", "proposed_tier", "mapper_note", "why_not_applied"])
        for r in stage.review:
            w.writerow(r)
    seen = collections.Counter()
    for _, _, nm, ob, kind, why in stage.refusals:
        seen[(nm, ob, kind, (why or "")[:180])] += 1
    with open(os.path.join(out_dir, "refusals.tsv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["component_name", "current_bigg", "refusal_kind", "reason", "n_components"])
        for (nm, ob, kind, why), c in seen.most_common():
            w.writerow([nm, ob, kind, why, c])
    total = sum(stage.tier_after.values())
    dist = {
        "n_media": n_files,
        "n_components": total,
        "tier_before": dict(stage.tier_before),
        "tier_after": dict(stage.tier_after),
        "actions": dict(stage.actions),
        "n_changed": len(stage.ledger),
        "n_review_queue": len(stage.review),
        "n_refusals": len(stage.refusals),
        "observed_components": total - sum(stage.tier_after[t] for t in NON_OBSERVED_TIERS),
    }
    with open(os.path.join(out_dir, "tier_distribution.json"), "w", encoding="utf-8") as fh:
        json.dump(dist, fh, indent=2)
    return dist


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--media-dir", default=MEDIA_DIR)
    ap.add_argument("--out", default=None, help="output directory (required unless --report-only)")
    ap.add_argument("--sample", type=int, default=0, help="process only the first N media")
    ap.add_argument("--report-only", action="store_true",
                    help="compute tiers and reports without writing a corrected corpus")
    args = ap.parse_args()
    if not args.out and not args.report_only:
        ap.error("--out is required unless --report-only is given")
    files = sorted(f for f in
                   (os.path.join(args.media_dir, x) for x in os.listdir(args.media_dir))
                   if f.endswith(".json"))
    if args.sample:
        files = files[:args.sample]
    out_dir = args.out or os.path.join(REPO, "build", "remap_report")
    stage = Stage()
    run(files, out_dir, stage, write=not args.report_only)
    dist = write_reports(stage, out_dir, len(files))
    print(json.dumps(dist, indent=2))
    print(f"\nreports in {out_dir}")


if __name__ == "__main__":
    main()
