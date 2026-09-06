# Evidence-tier verification, 2026-09-06

Hand adjudication of a deterministic stratified sample of the remapped corpus.
Reproduce the sample with:

    python3 tools/stages/remap_components.py --out build/remapped
    python3 tools/stages/verify_tiers.py build/remapped/media

which writes `tools/curation/tier_verification_sample.tsv` (seed 20260906, the 20
highest-volume decisions per tier plus 25 drawn uniformly from the tail).

**465 distinct (source_name -> BiGG id) decisions were adjudicated, covering
457,104 of 665,582 component rows (68.7%).** Distinct decisions are the unit of
adjudication because one verdict on `MUFA 18:1 -> ocdcea` settles 6,703 rows;
both counts are reported so the coverage is not overstated.

Three error classes are counted separately, because conflating them is how a
resource ends up claiming more than it knows:

* **wrong identity** — the component is not the compound the id names.
* **incomplete** — the identity is right but something the source stated is lost
  (a counter-ion, a specific isomer the source named).
* **tier over-claim** — the identity may be fine but the tier claims stronger
  evidence than was actually used. This is the class the whole pass exists to
  eliminate, so it is counted even when the mapping is correct.

## Result

| tier | decisions | rows covered | wrong identity | incomplete | tier over-claim |
|---|---:|---:|---:|---:|---:|
| structural_xref | 45 | 331 | 0 | 1 | 0 |
| curated_mapping | 38 | 623 | 0 | 4 | 0 |
| author_asserted | 45 | 6,585 | 0 | 0 | 0 |
| source_bigg_id | 45 | 1,664 | 0 | 0 | 0 |
| exact_name | 45 | 5,897 | 0 | 2 | 0 |
| name_table | 45 | 130,014 | 0 | 0 | 0 |
| fuzzy_name | 45 | 34,293 | 0 | 1 | 0 |
| class_proxy | 45 | 91,978 | 0 | 0 | 0 |
| derived_component | 45 | 185,032 | 0 | 0 | 0 |
| non_bigg_fallback | 45 | 469 | 0 | 1 | 0 |
| unmappable_mixture | 20 | 20 | 0 | 0 | 0 |
| unmapped | 2 | 198 | 0 | 0 | 0 |
| **total** | **465** | **457,104** | **0** | **9** | **0** |

Measured wrong-identity rate: **0 of 465 decisions (0.0%)**, upper 95% bound
0.8% by the rule of three. Measured incomplete rate: **9 of 465 (1.9%)**.

That is the rate AFTER this pass. It is not a claim that the corpus was ever
this good: the same adjudication method run against the shipped data would have
returned every defect the audit lists, and five further errors were found by
this exercise and fixed before the numbers above were taken (see below).

## What the adjudication actually found, and what was done about it

Five defects surfaced during verification. All five were fixed in the mapper or
the correction table and are now covered by regression tests; none was left in
the data with a note.

1. **`PUFA 18:3 n-6 c,c,c` was mapped to `lnlnca`** (alpha-linolenic acid, C18:3
   **n-3**). n-6 C18:3 is gamma-linolenic acid, `lnlncg` — same chain length and
   degree of unsaturation, different double-bond positions, different InChIKey.
   The n-3/n-6 split is the entire reason these are reported separately. Fixed in
   the mapper alias table and by correction `CHEM-GLA-01`. 30 rows.
2. **`gamma-linolenic acid` was aliased to `dlnlcg`**, which is *dihomo*-gamma-
   linolenic acid, C20:3 — two carbons longer. Fixed in the alias table. 60 rows.
3. **527 components named `L-cystine` sat on `cystine__L`**, a dictionary entry
   with no formula, no InChIKey and no place in the BiGGr reactome, i.e. an
   unusable exchange. Retargeted to `cysi__L` (C6H12N2O4S2,
   LEVWYRKDKASIDU-IMJSIDKUSA-N) by `CHEM-CYS-02`.
4. **My own mixture rule was over-broad.** `MIX-SOLN-01` originally matched the
   stock-solution phrase anywhere in a name, so `Copper (trace element solution)`
   and `Biotin (Wolfe's vitamins)` — correctly decomposed single constituents —
   were being stripped of their exchange. About 50 correct mappings would have
   been deleted. The pattern is now anchored to the head of the name and the
   false-positive cases are asserted in the rule's own justification text.
5. **A later correction was overriding an earlier mixture verdict.** A
   multi-compound vitamin-solution string that happens to contain "cob(i)alamin"
   was being handed EX_cbl1_e by the B12 rule after the mixture rule had already
   established it has no single target. Mixture and unmap verdicts are now
   terminal in the stage.

## The nine "incomplete" cases, itemised

None is a wrong compound; each loses something the source stated.

* `Tetrahexosylceramide (d18:1/26:0) -> gbside_cho` (structural_xref) — resolved
  by the source's own identifier, but BiGG's globoside id does not carry the acyl
  chain the source specified.
* Four `curated_mapping` rows of the form `Carbonate/CO2`, `Carbonate / CO3^2-
  (CO2)` — mapped to `co2`, which is right for the inorganic-carbon intent and a
  large improvement on the cobalt they carried before, but `hco3`/`co3` would be
  more faithful where the source names carbonate first.
* `Ammonium acetate (CH3COONH4) -> ac` and `Ca(NO3)2·4H2O (calcium nitrate) ->
  no3` (exact_name) — the principal nutrient is right, the counter-ion is not
  emitted from this row.
* `N2/CO2 headspace gas (80:20 v/v) -> n2` (fuzzy_name) — a two-gas string
  reduced to one gas.
* `Sodium L-lactate -> ModelSEED fallback` (non_bigg_fallback) — falls back to a
  non-BiGG exchange although `lac__L` exists and is in BiGGr.

These are recorded rather than fixed because each needs a decision this
workstream should not take alone: the first four are stoichiometry and
counter-ion questions that belong with the bounds/dissociation work, and the
last is a fallback-ordering question in `enrich_coverage.py`.

## What this verification does NOT establish

* It measures whether the recorded identity is chemically right. It does not
  measure whether the component belongs in the medium at all — 229,486 components
  are pipeline-generated and were never stated by any source, which is a
  provenance defect the tier labels but does not repair.
* It says nothing about bounds, concentrations or stoichiometry. Salt
  dissociation assigns both ions of a 2:1 salt the same concentration corpus-wide
  (audit MAP-14 verification), and that is untouched here.
* The tail draw is uniform over distinct decisions, so rare decisions are
  over-represented relative to rows. The row-coverage column is the honest
  denominator for "how much of the corpus did a human actually look at".
