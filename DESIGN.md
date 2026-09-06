# Media — design & data model

A curated, citation-backed library of growth and simulation **media** whose components
carry a standard **BiGG exchange reaction**, so a genome-scale metabolic model (GEM) can
adopt a medium without re-deriving it. Measured over the shipped corpus: **664,000 of
665,582 component records (99.8%) reach a BiGG exchange**; 1,364 carry a
ModelSEED/MetaNetX/KEGG fallback id that no BiGG model will accept, and 218 carry no
exchange at all. This document defines the schema, the mapping and provenance rules, and
the quality bar.

> **Why this exists.** Media formulations are scattered across thousands of papers,
> supplementary tables, and databases, in inconsistent namespaces. Reusing a published
> medium in a GEM today means re-reading the paper and re-mapping every compound by hand.
> `Media` does that work once, transparently, and with a citation for every medium.

---

## The record — `data/media/<id>.json`

```jsonc
{
  "id": "m9_glucose_aerobic",
  "name": "M9 minimal + glucose (aerobic)",
  "category": "laboratory",         // SHIPPED vocabulary: laboratory (4,930) | food (8,125)
                                    // | growth_medium (443, a second-generation label for
                                    // laboratory, merged by tools/stages/10_normalize_schema.py)
                                    // | biospecimen (17). The seven values documented here
                                    // before 2026-09 (minimal|defined|rich|dietary|niche|…)
                                    // appear in 0 records (SCHEMA-02/SCHEMA-06).
  "organism_scope": "prokaryote-generic",
  "aerobic": true,
  "description": "…",
  "namespace": "bigg",              // canonical exchange namespace
  "provenance": {
    "source_type": "standard",      // standard | literature | database. `formulated` is
                                    // never used, and 472 records currently carry a source
                                    // DATABASE NAME in this slot ("MediaDB (ISB defined
                                    // media)" 471, "Published (GEM paper)" 1) — a defect
                                    // being resolved by the provenance stage, not a
                                    // vocabulary (SCHEMA-02).
    "citation": "Author et al., Journal (year). …",
    "doi": "10.…",
    "url": "…",
    "notes": "how concentrations were turned into uptake bounds, approximations, etc."
  },
  "components": [
    {
      "name": "D-Glucose",
      "bigg_metabolite": "glc__D",
      "exchange": "EX_glc__D_e",
      "lower_bound": -20.0,          // < 0 = max uptake (mmol·gDW⁻¹·h⁻¹)
      "upper_bound": 1000.0,         // secretion allowed
      "concentration_mM": null,      // physical concentration when reported
      "xref_id": "glc__D",           // -> data/refs.json .xrefs["glc__D"] =
                                     // { "inchikey": "WQZ…", "chebi": "CHEBI:12965",
                                     //   "kegg": "C00031", "hmdb": "HMDB00122",
                                     //   "mnx": "MNXM41", "seed": "cpd00027" }
                                     // 2,287 distinct blocks stood in for 665,582
                                     // copies; absent = no cross-references at all.
      "in_biggr": true,              // present in the local BiGGr prokaryote reactome
      "mapping_method": "inchikey",  // 55 values in the shipped data, not 9: the xref
                                     // routes (inchikey|chebi|kegg|hmdb|mnx|seed), the
                                     // name routes (name*, *_remap), salt dissociation,
                                     // the pipeline-derived routes (mineral_base,
                                     // hydrolysate_approximation, complex_decomposition,
                                     // base_medium_expansion) and the fallbacks.
                                     // `python3 -c` over data/media enumerates them.
      "mapping_confidence": "exact"  // shipped values: exact | inferred | convention |
                                     // approximation | curated | standard_formulation |
                                     // high.  'manual' is documented but never used, and
                                     // 'exact' is NOT proof of a verified cross-reference
                                     // (finding MAP-02/COV-01) -- see the confidence note
                                     // under Conventions.
    }
  ],
  "uncovered": [ { "name": "…", "concentration_mM": 1.2, "reason": "no BiGG match" } ],
  // NB the field is `uncovered`, not `unmapped`: tools/enrich_coverage.py consumes the
  // legacy `unmapped[]` and replaces it, and `unmapped` is present in 0 of 13,515
  // shipped records. The docs said otherwise until this was corrected (SCHEMA-02).
  "n_components": 25,   // len(components)
  "n_mapped": 24,       // components carrying a BiGG metabolite id -- NOT a synonym for
                        // n_components (it used to be set equal to it in every record)
  "n_nonbigg_fallback": 1,  // components with a ModelSEED/MetaNetX/KEGG exchange instead
  "n_in_biggr": 24,     // components present in the local BiGGr reactome
  "version": "1.0"
}
```

`data/index.json` is the aggregate (one row per medium) that powers the browser and
programmatic queries.

---

## Conventions

**Namespace.** The canonical namespace is **BiGG** universal metabolite IDs and their
extracellular exchanges `EX_<id>_e`. Every component *also* carries cross-references
(InChIKey, ChEBI, KEGG, HMDB, MetaNetX, SEED, BioCyc) so the medium is portable to any
model — BiGGr, ModelSEED, KEGG-based, etc. `in_biggr` flags whether the metabolite exists
in the local BiGGr prokaryote reactome that our own models use.

**Bounds.** `lower_bound < 0` is the maximum uptake rate (mmol·gDW⁻¹·h⁻¹); `upper_bound`
allows secretion. Water, protons and mineral ions default to open (−1000) unless a source
specifies otherwise; carbon sources and O₂ are capped. When a physical concentration is
reported it is kept in `concentration_mM`, and `provenance.notes` records exactly how it
was turned into a bound (never silently invented).

**Mapping & evidence — everything is auditable.** Each component carries an
`evidence_tier` recording how its identity was ACTUALLY decided: one of twelve tiers,
grouped into six classes ordered by the strength of the evidence
(`tools/web_payload.py:EVIDENCE_CLASSES` is the single definition). Measured over the
shipped corpus: structure-verified 2,756, identifier-verified 3,610, name-matched
327,218, class-or-assertion 102,294, pipeline-derived 229,486, unresolved 218 — of
665,582. `mapping_confidence` is retained but is a coarse summary of the tier, and its
`exact` value has been withdrawn: it used to mark a hard-coded English-name lookup as
well as a cross-referenced match. A compound that cannot be mapped is **listed in
`uncovered` — never dropped silently**.

**Record-level honesty counters.** `n_mapped` + `n_nonbigg_fallback` + `n_unmappable`
= `n_components`, and `pct_sourced_components_with_bigg_id` (renamed from
`pct_covered_observed` on 2026-09-06 — the old name read as coverage while its
denominator was the components the record already carries) is the share of
source-stated components that reached a BiGG id. Coverage of the source's own ingredient
list is `coverage_source.pct_covered_source`, and only that.

**A record is not unique as a model input.** 6,827 of 13,515 records (50.5%) hand a model
the identical set of `(exchange, lower_bound, upper_bound)` triples as at least one other
record. The catalog carries `model_input_signature` and
`n_media_with_identical_model_input` per record, and `data/web/twins.json` publishes the
complete groups. Nothing is merged: the provenance of two identical constraint sets is
still two different facts.

**Citations are mandatory.** Every medium has a `provenance.citation` (+ DOI/URL where
one exists). Standard recipes cite the canonical reference; literature media cite the
paper; database-derived media cite the database and version; formulated media document
the recipe and reasoning.

**No silent mistakes.** Where a formulation is an approximation (e.g. undefined rich-media
components such as yeast extract rendered as a defined amino-acid/nucleotide set), it is
labelled as such in `description`/`notes`, and the reasoning is recorded.

---

## Sourcing roadmap (each phase fully cited)

1. **Standard media** — M9 (± O₂, carbon variants), LB, TSB, BHI, MOPS, and other
   textbook recipes. *(seed: M9 ±O₂ present)*
2. **Biospecimen media** — HMDB-derived serum, urine, faeces, CSF, saliva, sweat.
   *(seed: serum, urine, faeces present, from PLOS Pathogens `ppat.1013775`)*
3. **Dietary / AGORA media** — Western, high-fibre, vegan, infant, etc., mapped from the
   published diet definitions to BiGG exchanges.
4. **Food-derived media** — representative foods & composed diets from USDA FoodData
   Central and FooDB, converted to metabolite exchanges.
5. **Literature-mined media at scale** — media formulations extracted from the GEM
   literature (methods + supplementary tables), each mapped and cited.

Every phase runs through the same schema, mapper, and a **reviewer pass (author ≠
reviewer)** that re-checks mappings against BiGG before a medium is accepted.

---

## Consuming a medium (COBRApy)

```python
import json, cobra
med = json.load(open("data/media/m9_glucose_aerobic.json"))
model = cobra.io.load_json_model("my_strain.json")
medium = {c["exchange"]: -c["lower_bound"] for c in med["components"]
          if c["exchange"] in model.reactions}   # cobra medium = max uptake (positive)
model.medium = medium
print(model.slim_optimize())
```
