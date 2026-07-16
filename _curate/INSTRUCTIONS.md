# Deep medium re-curation — complete-recipe recovery

You are recovering the **complete** growth-medium recipe(s) for ONE paper, so that a
metabolic-model media database lists **absolutely every compound** in each medium —
not just what the main text happens to spell out.

## Your target
You are given ONE target file: `/data/media_curate/_curate/targets/<PMC>.json`. Read it.
It lists the PMC id, whether the paper is in the local corpus, and one or more `media`
records (each with its current components + current provenance/evidence + any
`base_medium_reference`). Your job is to produce the **complete, correct** recipe for
each listed medium.

## How to read sources (in order of cost)
1. **The paper itself.** If `in_corpus` is true, Read `corpus_path` (a JATS/PMC XML full
   text — read it directly). Otherwise WebFetch `pmc_url`.
2. **Cited base-medium references.** THIS IS THE CORE OF THE TASK. Papers routinely say
   "cells were grown in medium X as described in [ref]" or "a modified M9 (ref 23)" and
   give only the *modifications* in the main text. You MUST obtain that cited recipe:
   find the reference in the paper's reference list, then WebFetch it (try
   `https://pmc.ncbi.nlm.nih.gov/articles/PMC<id>/`, the DOI `https://doi.org/<doi>`, or a
   web search for the title). Extract the FULL base composition (all salts, trace metals,
   vitamins, buffer) and merge it with the paper's modifications.
3. **Supplementary material.** If the recipe (or any table) lives in a supplement
   ("Table S1", "Supplementary Methods", "Additional file"), obtain it: WebFetch the PMC
   article's supplementary links, or `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC<id>/fullTextXML`,
   or the journal's supplementary URL. Extract the full table.
4. **Named stock solutions / trace-element mixes.** If the recipe cites a named trace/
   vitamin solution (e.g. "SL-10", "Wolfe's mineral elixir", "Widdel trace elements",
   "Balch vitamins", "DSM 141"), expand it to its known constituent salts/vitamins and
   cite where that composition comes from. If you cannot find it, list the solution by
   name and mark it unexpanded (do NOT invent constituents).

## What a COMPLETE recipe must include (check each is present or truly absent)
- Carbon source(s) and their concentration
- Nitrogen source (NH4+, NO3-, amino acids, N2 for diazotrophs…)
- Phosphate / buffer (phosphate, HEPES, MOPS, bicarbonate/CO2…)
- All bulk salts (Na, K, Mg, Ca, Cl, SO4…)
- **All trace elements** (Fe, Zn, Mn, Cu, Co, Ni, Mo, B, Se, W…) — most often the thing
  that is MISSING because it hides in a cited stock solution
- **All vitamins** (biotin, thiamine, B12, riboflavin, pantothenate, folate, PABA…)
- Reductant + gas phase for anaerobes (cysteine, sulfide, Na2S, N2/CO2, H2…)
- Undefined complex ingredients (yeast extract, peptone, serum) — list by name; do not
  fabricate their molecular composition (the DB decomposes those separately)

## HARD rules
- **No fabrication.** Every compound you report must have textual support from the paper,
  a cited reference, or a supplement. Give a short **verbatim quote** and say which source
  it came from (`main_text` / `supplementary` / `cited:<short ref>` / `stock:<name>`).
- Concentrations: report the value + unit exactly as stated; give `concentration_mM` only
  when you can convert confidently, else null. Never invent a number.
- If the true recipe genuinely lives in a source you cannot obtain, say so
  (`status: "incomplete_source"`) and record what you *were* able to confirm.
- If the paper never actually defines a medium (uses a natural sample, in-vivo, a
  commercial product with no stated composition), `status: "rejected"` with the reason.
- Preserve the medium's identity — do not swap it for a different medium.

## Output — write ONE file
Write your result to `/data/media_curate/_curate/results/<PMC>.json` (use the Write tool).
Schema:
```json
{
  "pmc": "PMC…",
  "media": [
    {
      "id": "<the medium id from the target>",
      "status": "corrected | confirmed | incomplete_source | rejected | not_found",
      "oxygen": "aerobic | anaerobic | facultative",
      "components": [
        {"name": "monopotassium phosphate", "concentration": "3 g/L",
         "concentration_mM": 22.0, "role": "phosphate",
         "source": "cited:Widdel 1983", "evidence": "…verbatim…"}
      ],
      "base_medium": "…",
      "sources_chased": [
        {"what": "base recipe cited as ref 23 (Widdel 1983)", "obtained": true,
         "how": "WebFetch doi.org/…", "added": ["FeCl2","trace SL-10 metals","7 vitamins"]}
      ],
      "confidence": "high | medium | low",
      "missing_before": ["list of compounds that were absent from current_components but are really in the medium"],
      "notes": "one or two sentences"
    }
  ]
}
```
Report the **union of all real components** (current ones that are correct + everything
you recovered). It is fine to confirm a medium was already complete
(`status: "confirmed"`, empty `missing_before`). Return only the file; keep chatter minimal.
