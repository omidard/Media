# Media

**A curated, citation-backed library of growth & simulation media for genome-scale
metabolic models — every component mapped to a standard BiGG exchange reaction.**

Reusing a published medium in a genome-scale metabolic model (GEM) usually means
re-reading the paper and re-mapping every compound into your model's namespace by hand.
`Media` does that once, transparently: each medium is a machine-readable record where
every component is mapped to a BiGG exchange (`EX_<met>_e`), carries cross-references
(InChIKey / ChEBI / KEGG / HMDB / MetaNetX / SEED), and the whole medium carries a
**citation**.

> **11,367 media** and counting — laboratory culture media, food-derived media, host
> biofluids, and formulations mined from the primary literature — assembled from **DSMZ
> MediaDive, FooDB, USDA FoodData Central, HMDB, BMDB**, and **571 GEM papers**, all in one
> consistent, cited, BiGG-mapped format.

## Explore it online

An interactive browser — search and filter every medium, inspect each component's cross-references and mapping confidence, and **copy any medium straight into COBRApy**. Runs entirely in your browser.

<table>
<tr>
<td width="50%"><a href="https://omidard.github.io/Media/"><img src="shot_media_1.png" alt="Media browser: searchable table + dashboard over thousands of GEM-ready media" width="100%"></a></td>
<td width="50%"><a href="https://omidard.github.io/Media/"><img src="shot_media_2.png" alt="A defined DSMZ culture medium mapped to BiGG exchanges, ready to copy as a COBRApy medium" width="100%"></a></td>
</tr>
<tr>
<td width="50%"><a href="https://omidard.github.io/Media/"><img src="shot_media_3.png" alt="HMDB blood metabolome as a biospecimen medium with concentrations and citations" width="100%"></a></td>
<td width="50%"><a href="https://omidard.github.io/Media/"><img src="shot_media_4.png" alt="A food-derived medium from FooDB with measured concentrations" width="100%"></a></td>
</tr>
</table>

<p align="center">
  <em>Laboratory / defined media (DSMZ) &middot; biospecimen media (HMDB) &middot; food-derived media (FooDB) &middot; every component cited &amp; mapped to BiGG</em><br><br>
  <a href="https://omidard.github.io/Media/"><img src="https://img.shields.io/badge/%E2%96%B6%20Open%20the%20Media%20browser-1F8A70?style=for-the-badge&logo=googlechrome&logoColor=white" height="42" alt="Open the Media browser"></a>
  &nbsp;&nbsp;<a href="https://omidard.github.io/Media/"><code>omidard.github.io/Media</code></a>
</p>

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
├── index.html            # interactive browser (GitHub Pages, served from root)
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

## Programmatic access (data API)

Everything here is a **read-only static API** over GitHub Pages — plain HTTPS `GET`s
with permissive CORS, so you can fetch from Python, R, JS, or `curl` with no key and no
rate limit. Full reference in **[`API.md`](./API.md)** (+ machine-readable
[`openapi.yaml`](./openapi.yaml)).

```
GET  data/index.json              # catalog: counts + one summary per medium
GET  data/media/{id}.json          # full record for one medium
GET  data/api/media.parquet        # bulk: one row per medium
GET  data/api/components.parquet    # bulk: one row per (medium, component)
GET  data/api/media.sqlite.gz       # SQLite (media + components, indexed)
GET  data/api/media.jsonl.gz        # all full records, one JSON per line
GET  data/api/manifest.json         # version, totals, file inventory, schemas
```

Query the bulk Parquet in place, without downloading, via DuckDB:

```python
import duckdb
con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
B = "https://omidard.github.io/Media/data/api"
con.sql(f"SELECT category, count(*) FROM read_parquet('{B}/media.parquet') GROUP BY 1")
```

Or use the ready-made client (filters, `to_cobra_medium`, cached fetch):

```bash
pip install "git+https://github.com/omidard/Media.git#subdirectory=client"
```
```python
from pymediadb import MediaDB
db = MediaDB()
db.list_media(category="laboratory", defined=True)
db.to_cobra_medium(db.get_medium("m9_glucose_aerobic"))
```

Rebuild the bulk artifacts after new media land: `python3 tools/build_api_exports.py`.

## Current contents — 11,367 media

Each medium is cited and mapped through the same pipeline. By source database:

| Source | Media | What it contributes |
|---|---:|---|
| **USDA FoodData Central** | 7,479 | food media from analytically-measured composition (Foundation + SR Legacy) |
| **DSMZ MediaDive** | 3,148 | real culture-media recipes (Koblitz *et al.*, NAR 2023) — defined exact, complex as labelled approximations |
| **FooDB** | 616 | one medium per food (measured food composition) |
| **Literature (GEM papers)** | 93 | formulations mined from 571 primary papers, each snippet-verified & cited |
| **HMDB 5.0** | 9 | host biofluids (blood, urine, feces, saliva, CSF, sweat, milk, bile, amniotic) |
| **BMDB** | 5 | bovine biofluids incl. **rumen fluid** |
| **Classic + published** | 22 | LB, TSB, BHI, blood agar, M9 / MOPS / M63 / Davis + serum/urine/faeces (PLOS Pathog 2025) |

Grouped into three **categories** — **laboratory** (3,255), **food** (8,095), **biospecimen** (17).
Defined media map every compound to a BiGG exchange with concentrations (salts dissociated to
their ion exchanges); complex media map their defined portion and render undefined hydrolysates
(peptone, extracts) as a clearly-labelled in-silico approximation, with the real ingredients
listed in `unmapped`.

## Contributing a medium

Open an issue or PR with: the formulation (compounds + concentrations or uptake bounds),
the **citation**, and the organism scope. The mapper + a review pass will map it to BiGG
and record provenance. See [DESIGN.md](DESIGN.md).

## Mapping backbone & attribution

Cross-references are built from the [BiGG Models](http://bigg.ucsd.edu) namespace and
resolved against the local BiGGr prokaryote universal reactome. Please cite the original
source of any medium you use (given in each record's `provenance`).

## License

Data: **CC-BY-4.0** (cite each medium's original source, given in its `provenance`).
Code (`tools/`, `index.html`): **MIT**. See [LICENSE](LICENSE).
