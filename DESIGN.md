# Media — design & data model

A curated, citation-backed library of growth and simulation **media**, every component
mapped to a standard **BiGG exchange reaction**, so any genome-scale metabolic model
(GEM) can adopt a medium without re-deriving it. This document defines the schema, the
mapping and provenance rules, and the quality bar.

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
  "category": "minimal",            // minimal | defined | rich | dietary | biospecimen | niche | food
  "organism_scope": "prokaryote-generic",
  "aerobic": true,
  "description": "…",
  "namespace": "bigg",              // canonical exchange namespace
  "provenance": {
    "source_type": "standard",      // standard | literature | database | formulated
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
      "xref": { "inchikey": "WQZ…", "chebi": "CHEBI:12965", "kegg": "C00031",
                "hmdb": "HMDB00122", "mnx": "MNXM41", "seed": "cpd00027" },
      "in_biggr": true,              // present in the local BiGGr prokaryote reactome
      "mapping_method": "inchikey",  // inchikey | chebi | kegg | hmdb | mnx | seed | name | bigg_native | manual
      "mapping_confidence": "exact"  // exact (xref) | inferred (name) | manual
    }
  ],
  "unmapped": [ { "name": "…", "concentration_mM": 1.2, "reason": "no BiGG match" } ],
  "n_components": 25, "n_mapped": 25, "n_in_biggr": 25,
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

**Mapping & confidence — everything is auditable.** Components are mapped by the
`tools/` mapper: cross-reference first (InChIKey → ChEBI → KEGG → HMDB → MetaNetX → SEED,
`confidence = exact`), then normalized name (`confidence = inferred`), then manual
curation (`confidence = manual`). A compound that cannot be mapped is **listed in
`unmapped` — never dropped silently**. `mapping_method` + `mapping_confidence` are stored
on every component so a reader can trust, or re-check, each one.

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
