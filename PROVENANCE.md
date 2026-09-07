# How to read a medium's provenance

Every record in `data/media/` answers four questions in its own fields: **where did this come
from, may you reuse it, who said each component was in it, and how much of the recipe did we
actually capture.** This page is how to read those answers. `LICENSE` carries the data licence and
`NOTICE` carries the upstream attributions.

---

## 1. Where it came from — `provenance.source_id`

```json
"source_id": "dsmz_mediadive",
"source_name": "DSMZ MediaDive",
"source_identity_evidence": "provenance.doi == '10.1093/nar/gkac803' (MediaDive database paper) and citation contains 'MediaDive'",
"source_identity_confidence": "verified"
```

`source_identity_evidence` is the point. The source is resolved from evidence inside the
record — its URL host, its DOI, verbatim substrings of its citation — by
`tools/source_identity.py`, and the field records which of those matched.

It is deliberately **not** taken from the record id. `build_index.py:source_db()` decides the
source with `idv.startswith('mediadive_')`, and that inference is already wrong on ten
records we can name: five classic formulations that cite DSMZ without the prefix, and five
bovine BMDB records filed under "Published (HMDB-derived)" — so bovine rumen and colostrum
shipped labelled as human-metabolome-derived. A provenance claim built on a filename is a
string match wearing a fact's clothes.

A record that cannot be resolved from its own evidence is a hard failure in the pipeline. It
is never assigned to a bucket by default.

| `source_id` | media | what it contributed |
|---|---:|---|
| `usda_fdc` | 7,424 | USDA FoodData Central food composition records |
| `dsmz_mediadive` | 3,148 | cultivation media aggregated from DSMZ, JCM and CCAP |
| `growthdb_literature` | 1,369 | formulations from primary papers, curated through GrowthDB |
| `foodb` | 701 | FooDB food composition records |
| `mediadb_isb` | 471 | chemically defined media with quantitative concentrations |
| `standard_classic` | 297 | canonical laboratory media (LB, M9, MOPS, BHI, …) |
| `primary_literature` | 88 | formulations mined from genome-scale-model papers |
| `hmdb` | 9 | normal human biofluid metabolite concentrations |
| `bmdb` | 5 | normal bovine biofluid metabolite concentrations |
| `hmdb_via_publication` | 3 | HMDB tables republished in an open-access paper |

### The collection behind the aggregator

MediaDive aggregates three culture collections, and this resource used to erase that: all
3,148 records asserted "DSMZ Medium *n*", including 1,248 that belong to JCM or CCAP.

```json
"collection": "JCM",
"collection_evidence": "provenance.url host 'www.jcm.riken.jp'",
"collection_medium_id": "557",
"citation":          "MediaDive (Koblitz J et al., Nucleic Acids Res 2023), aggregating JCM medium 557: ALKALINE LB AGAR.",
"citation_original": "DSMZ MediaDive (Koblitz J et al., Nucleic Acids Res 2023); DSMZ Medium J557: ALKALINE LB AGAR."
```

`collection_medium_id` appears only where it is verifiable — as MediaDive states it for DSMZ,
and for JCM only when confirmed against the RIKEN `GRMD=` number in the URL. CCAP publishes
filename-based recipe PDFs with no visible numeric id, so for its 105 media the field is
`null`. **An absent value is null, never a guess.**

The *display name* of these 1,248 media still reads "(DSMZ …)". That is deliberate: renaming
them belongs to the naming workstream, so the conflict is handed over instead of resolved
twice —

```json
"attribution_conflict": {
  "asserts": "DSMZ", "true_collection": "JCM",
  "suggested_name": "Alkaline LB Agar (JCM 557, via MediaDive)"
}
```

---

## 2. Whether you may reuse it — one licence, not a per-record field

The data is licensed **CC BY-NC 4.0** as a whole. A record carries no licence field: a
compilation cannot grant more than its most restrictive input allows, so the single licence
is set there and stated once, in `LICENSE` and as `license` in every payload.

What a record does carry is where it came from — `provenance.source_id` and
`provenance.source_name` — which is what `NOTICE` credits and what you need in order to ask
a rights-holder for terms beyond CC BY-NC. Of the sources, MediaDB (Institute for Systems
Biology, 471 media) grants no reuse right upstream at all and holds 8,397 of the resource's
14,055 concentration values; FooDB, HMDB and BMDB permit no commercial use.

---

## 3. What the citation actually identifies — `provenance.citation_type`

Every one of the 13,515 media has a non-empty citation string. That is a string test, not a
provenance claim. What the citation *identifies* varies:

| `citation_type` | media | what the cited thing is |
|---|---:|---|
| `database_record` | 8,610 | a record in an aggregating database, not a paper |
| `collection_catalog` | 3,148 | a culture-collection recipe page, via an aggregator |
| `primary_paper` | 1,460 | a publication that states this medium's formulation |
| `classic_reference` | 297 | a canonical published formulation |

`has_primary_citation` is true only for the first category. It is deliberately not derived
from the `doi` field: **1,371 of 13,515 records** leave `doi` empty and carry their PMC id in
the URL, which is why a naive DOI census reports 236 distinct works where the union of DOIs
and recovered PMC ids over the primary-literature media alone is 907. `primary_identifier`
recovers that id deterministically:

```json
"primary_identifier": {"type": "pmcid", "value": "PMC4594890"},
"citation_resolved": true
```

`citation_resolved` is false for 11,865 records — mostly database records that cite a
database, plus 459 author-year stubs like `"Lovley dr et al, 1993"` with no DOI and no PMID.
Those stay unresolved on purpose. Matching "Park et al, 2004" against Crossref would turn a
visible gap into an invisible fabrication, and a wrong DOI in someone's methods section is
worse than no DOI.

---

## 4. Whether the paper really contains the recipe — `provenance.verification_status`

```json
"verification_status": "reconstructed-from-cited-references",
"verification_original": "paper-verified (recipe recovered from primary literature)",
"verification_downgrade_reason": "Downgraded from 'paper-verified …': the project's verification pass recorded verdict 'unavailable'; and the record's own provenance.verification_note contradicts the label. …"
```

Nine media claimed "paper-verified" while carrying a note saying the cited paper does not
print the formulation, and the project's own verification pass had already rejected them. A
build-time alarm now fires whenever a record holds both at once, so the contradiction cannot
return silently.

They were relabelled, **not quarantined**. The recuration rounds that followed those verdicts
did real source-chasing — the V4 mineral base traced to Dunfield 2007, SMM recovered from a
dissertation — so the recipes are largely right. What was false was the label.

| `verification_status` | media |
|---|---:|
| `unverified` | 11,604 |
| `paper-verified` | 974 |
| `reference-database` | 471 |
| `expert-curated` | 455 |
| `reconstructed-from-cited-references` | 9 |
| `rejected-by-verification-pass` | 1 |

---

## 5. Which components are real — `components[].evidence_class`

**229,486 of 665,582 components (34.5%) were never stated by the source the record cites.**
They are this pipeline's output: injected mineral panels, an oxygen exchange written from an
aerobicity call, a base medium expanded from its name, and blanket "hydrolysate
approximations" that replace one undefined ingredient with the same fixed 35 metabolites.

They are all still there. Every one is labelled:

```json
{"name": "L-Alanine", "mapping_method": "hydrolysate_approximation",
 "evidence_class": "derived", "derived_class": "inferred_from_listed_ingredient"}
```

| `derived_class` | components | what it means |
|---|---:|---|
| — (`evidence_class: sourced`) | 436,096 | the cited source states this component |
| `inferred_from_listed_ingredient` | 127,303 | the ingredient *is* in the recipe; its breakdown is inferred |
| `injected_convention` | 101,796 | nothing in the recipe corresponds to it |
| `canonical_base_expansion` | 387 | a named base medium expanded to its published composition |

Three classes, not one bucket, because they carry different warrant. Decomposing the beef
extract that a recipe really lists, using a cited Handbook of Microbiological Media entry, is
not the same act as adding ammonium to a hamburger.

The classification lives in `tools/component_evidence_classes.tsv`, which covers all 55
`mapping_method` values in the corpus. An unlisted method is a hard failure — a new source
cannot slip an unclassified component in behind a default.

164 media have **no** sourced component at all. Their composition is entirely ours.

---

## 6. How much of the recipe we captured — `coverage_source`

The shipped `coverage.pct_covered` counts invented components as covered, and its numerator
and denominator are different units: components over (components + unresolved *ingredients*).
Decomposing one unmappable ingredient into 35 metabolites therefore removes a failure from
the denominator and adds 35 successes to the numerator at once. The metric rises fastest
where the source data is weakest. "Nutrient Agar (DSMZ 1)" ships 49 components of which zero
come from the recipe, and reads "Coverage 98%".

Both numbers are now published, each with its denominator:

```json
"coverage_source": {
  "n_components": 49, "n_sourced": 0, "n_derived": 49,
  "n_uncovered_ingredients": 1,
  "n_source_ingredients_replaced_by_derived_components": 2,
  "pct_covered_all": 98.0,     "pct_covered_all_denominator": 50,
  "pct_covered_source": 0.0,   "pct_covered_source_denominator": 3,
  "pct_covered_source_is_upper_bound": true,
  "replaced_ingredient_names_unavailable": true,
  "pct_sourced_of_components": 0.0
}
```

* `pct_covered_all` is the legacy formula, recomputed. It reproduces the shipped value for
  all 13,515 records, so the change is auditable and nothing downstream breaks.
* `pct_covered_source` counts only source-stated components, and restores to the denominator
  the ingredients the pipeline replaced instead of leaving unresolved.
* `pct_sourced_of_components` is the simplest reading of all: how much of what you are
  looking at came from the source.

Across the library:

| | legacy | honest |
|---|---:|---:|
| media at ≥90% coverage | 12,353 (91.4%) | 8,710 (64.4%) |
| media below 60% | 45 | 868 |
| media at 0% | 0 | 164 |

The site's "91% high-confidence" headline is **64.4%** once derived composition is excluded.
762 media leave the green band.

The honest number does not replace the legacy one, and coverage is not a fidelity score. A
complex medium whose beef extract is decomposed from a cited reference is not worthless, and
ranking the library by source coverage alone would bury the media people actually use. Read
both.

### Where the honest number is a ceiling

3,627 media carry `pct_covered_source_is_upper_bound: true`. Restoring a replaced ingredient
to the denominator requires knowing *which* ingredient was replaced, and the corpus cannot
always say: `hydrolysate_approximation` records no `derived_from` at all (0 of 100,619), and
`complex_decomposition` collapses several recipe lines onto one name — all 40 invented BHI
components say "beef extract" although the recipe also lists brain infusion, heart infusion
and peptone. The replaced count is a floor, so the ratio is a ceiling, and the record says so
rather than rounding to the flattering end.

---

## 7. One catalogue, one total

Four totals ship at once today: 13,515 on disk and in `index.json`, 13,073 in the orphaned
`stats.json`, 12,387 in `media_stats.json` and `presence_matrix.json`, 11,367 in the README.
The landing page renders a 13,515 headline above a category chart summing to 12,387.

The corpus on disk is the authority — it is the only total that is computed rather than
typed. `tools/verify_counts.py` checks every shipped artifact against it, including
key-for-key equality of the category breakdown, because a total-only check would not have
caught the missing `growth_medium` slice that hides 443 media from the site's chart.

```
python3 tools/verify_counts.py
```

It **fails today**, naming each divergent number, and passes once the derived artifacts are
rebuilt.

---

## Reproducing all of this

None of these fields were hand-edited into the data. They are produced by two transform
stages — `tools/stages/20_stamp_provenance.py` and `tools/stages/39_recompute_coverage.py` —
which read a corpus and write a corrected corpus, assert their own post-conditions, and are
idempotent. See `tools/stages/README.md` for the contract they obey and how to run the chain.

The tables they read are checked in and human-readable: `tools/licenses.tsv`,
`tools/component_evidence_classes.tsv`, `tools/verification_verdicts.tsv`.
