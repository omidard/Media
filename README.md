# Media

**A curated, citation-backed library of growth & simulation media for genome-scale
metabolic models — every component mapped to a standard BiGG exchange reaction.**

Reusing a published medium in a genome-scale metabolic model (GEM) usually means
re-reading the paper and re-mapping every compound into your model's namespace by hand.
`Media` does that once, transparently: each medium is a machine-readable record where
every component is mapped to a BiGG exchange (`EX_<met>_e`), carries cross-references
(InChIKey / ChEBI / KEGG / HMDB / MetaNetX / SEED), and the whole medium carries a
**citation**.

> `Media` is the first repo in a suite of GEM **validation-data** resources — a long-standing
> gap in the field. Planned siblings: growth / uptake / production rates, ¹³C-MFA flux data,
> transcriptomics for reaction constraints, biomass compositions, and Biolog phenotyping,
> for as many prokaryotes as possible.

---

## What's here

```
Media/
├── data/
│   ├── media/            # one cited JSON record per medium
│   └── index.json        # aggregate index (browser + programmatic use)
├── tools/
│   ├── map_metabolite.py         # name / xref → BiGG exchange mapper (auditable)
│   ├── bigg_metabolite_dict.json # 9,403 BiGG metabolites + xrefs (3,773 in BiGGr)
│   └── bigg_reverse_index.json   # reverse indexes (by name and each xref)
├── docs/                 # interactive browser (GitHub Pages) — in progress
├── DESIGN.md             # schema, conventions, provenance & mapping rules
└── README.md
```

Each record: see **[DESIGN.md](DESIGN.md)**. Every component records **how** it was mapped
(`mapping_method`) and **how confident** that mapping is (`exact` via cross-reference,
`inferred` via name, or `manual`). Compounds that can't be mapped are listed in `unmapped`,
never dropped silently.

## Use a medium (COBRApy)

```python
import json, cobra
med = json.load(open("data/media/m9_glucose_aerobic.json"))
model = cobra.io.load_json_model("my_strain.json")
model.medium = {c["exchange"]: -c["lower_bound"] for c in med["components"]
                if c["exchange"] in model.reactions}
print(model.slim_optimize())
```

## Current contents (seed)

| Medium | Category | Components | In BiGGr | Source |
|---|---|---:|---:|---|
| M9 + glucose (aerobic) | minimal | 25 | 25 | Sambrook & Russell 2001; iML1515 |
| M9 + glucose (anaerobic) | minimal | 24 | 24 | Sambrook & Russell 2001; iML1515 |
| Simulated serum | biospecimen | 246 | 238 | Ardalani *et al.*, PLOS Pathog 2025 |
| Simulated urine | biospecimen | 135 | 134 | Ardalani *et al.*, PLOS Pathog 2025 |
| Simulated faeces | biospecimen | 281 | 272 | Ardalani *et al.*, PLOS Pathog 2025 |

More media are being added from standard recipes, HMDB biospecimens, AGORA/diet
definitions, food databases (USDA FoodData Central, FooDB), and large-scale mining of
the GEM literature — each cited and mapped through the same pipeline.

## Contributing a medium

Open an issue or PR with: the formulation (compounds + concentrations or uptake bounds),
the **citation**, and the organism scope. The mapper + a review pass will map it to BiGG
and record provenance. See [DESIGN.md](DESIGN.md).

## Mapping backbone & attribution

Cross-references are built from the [BiGG Models](http://bigg.ucsd.edu) namespace and
resolved against the local BiGGr prokaryote universal reactome. Please cite the original
source of any medium you use (given in each record's `provenance`).

## License

Data: **CC-BY-4.0**. Code (`tools/`, `docs/`): **MIT**. See [LICENSE](LICENSE).
