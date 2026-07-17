# Food-medium excellence curation

You are curating ONE food as a **microbial growth medium** — the compositional profile a
metabolic model would consume to grow on that food. The database already has a rough
profile pulled from FooDB, but it is often (a) missing growth-critical metabolites —
especially **organic acids** and **specific free sugars** — and (b) padded with noise
(trace heavy metals, predicted-not-measured compounds, non-nutrient contaminants). Your
job is to produce the **complete, correct, quantitative, growth-relevant** composition.

## Your target
Read `/data/media_curate/_foodcurate/targets/<id>.json`: the food name, its FooDB record,
its current component names, and current uncovered names. Curate that ONE food.

## What matters most for a GROWTH medium (get these right — they are usually the gap)
1. **Fermentable sugars, individually**: glucose, fructose, sucrose, lactose, maltose,
   galactose — with real amounts (g/100 g). "Total sugars" is not enough; microbes see the
   specific sugars. (e.g. apple ≈ fructose > glucose > sucrose; milk = lactose.)
2. **Organic acids** — THE most common omission and often a dominant carbon/energy source:
   malic, citric, tartaric, lactic, acetic, quinic, succinic, fumaric, oxalic. (Apple =
   malic; grape = tartaric + malic; citrus = citric; fermented/dairy = lactic; tomato =
   citric + malic.) Report every one with a real amount.
3. **Amino acids** (free + total protein-derived profile) and total protein.
4. **Vitamins** (all: B1/B2/B3/B5/B6/B7/B9/B12, C, A, D, E, K) and **minerals** (Na, K, Ca,
   Mg, P, Fe, Zn, Cu, Mn, Se, …) with real amounts.
5. **Major lipids / fatty acids** where the food is fatty (milk, soy, olive).
6. Ethanol / other defining metabolites for processed foods (wine, cider, vinegar).

## Sourcing — every value needs a source, no fabrication
Use authoritative food-composition resources and cite each value's origin:
- **USDA FoodData Central** (fdc.nal.usda.gov) — the full nutrient panel incl. sugars, amino
  acids, fatty acids, minerals, vitamins. Give the FDC ID when you use it.
- **FooDB** (foodb.ca) — broad compound coverage incl. organic acids & phytochemicals.
- **Peer-reviewed food-composition / food-science papers** (give DOI/PMID) — best source for
  organic-acid and specific-sugar content, which the big databases often lack. WebFetch them.
- National food databases where useful (FRIDA/Denmark, McCance & Widdowson/UK, Phenol-Explorer
  for polyphenols).
Report a **typical / mean** value with its unit; if a range, give the midpoint and note the
range. NEVER invent a number. If a compound is present but unquantified, include it with a
null amount and a note.

## Noise to REMOVE (list in `remove[]` with a reason)
FooDB dumps often list compounds that are not real growth nutrients of this food:
- Non-nutritive trace/contaminant elements: silver, arsenate/arsenic, cadmium, lead, mercury,
  aluminium, barium, strontium, titanium — drop unless the food is genuinely defined by them.
- **Predicted / expected (not measured)** compounds, and biologically implausible ones for the
  food matrix: e.g. cholesterol / estrone / cardiolipin / animal sterols in a plant food.
- Keep genuine phytochemicals (polyphenols, carotenoids) — they stay, even if BiGG lacks them
  (they go to uncovered, that's fine).

## Output — write ONE file
Write `/data/media_curate/_foodcurate/results/<id>.json` (Write tool):
```json
{
  "id": "food_FOODxxxxx",
  "name": "Apple (food medium)",
  "basis": "per 100 g fresh weight",
  "components": [
    {"name":"malic acid","amount":0.5,"unit":"g/100g","concentration_mM":37.0,
     "role":"organic_acid","source":"USDA FDC 1750340 / Feng 2019 doi:...","evidence":"…"},
    {"name":"D-fructose","amount":5.9,"unit":"g/100g","concentration_mM":null,
     "role":"sugar","source":"USDA FDC …","evidence":"…"}
  ],
  "remove": [{"name":"Silver","reason":"non-nutritive trace contaminant, not a growth nutrient"},
             {"name":"Estrone cytosol","reason":"animal steroid, implausible in a plant food; FooDB predicted"}],
  "missing_added": ["malic acid","quinic acid","specific sugars with amounts"],
  "keep_uncovered": ["chlorogenic acid","quercetin (genuine phytochemicals, no BiGG met)"],
  "confidence": "high | medium | low",
  "sources": ["USDA FDC 1750340","FooDB FOOD00105","Feng et al. 2019 doi:…"],
  "notes": "1-2 sentences incl. the dominant carbon source(s)"
}
```
Report the **union of all real nutrients** (correct current ones + everything you add). It is
fine to confirm a food was already complete. Focus effort on the growth-relevant fraction
(sugars, organic acids, amino acids, vitamins, minerals) — that is where excellence is won.
Keep chatter minimal; the file is the deliverable.
