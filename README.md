# Media

**A semi-curated, citation-backed library of growth & simulation media for genome-scale
metabolic models — every component mapped to a standard BiGG exchange reaction.**

Reusing a published medium in a genome-scale metabolic model (GEM) usually means
re-reading the paper and re-mapping every compound into your model's namespace by hand.
`Media` does that once, transparently: each medium is a machine-readable record where
every component is mapped to a BiGG exchange (`EX_<met>_e`), carries cross-references
(InChIKey / ChEBI / KEGG / HMDB / MetaNetX / SEED), and the whole medium carries a
**citation**.

> **13,515 media** and counting — laboratory culture media, food-derived media, host
> biofluids, and formulations mined from the primary literature — assembled from **DSMZ
> MediaDive, FooDB, USDA FoodData Central, HMDB, BMDB**, and **571 GEM papers**, all in one
> consistent, cited, BiGG-mapped format.

## Explore it online

An interactive browser — search and filter every medium, inspect each component's cross-references and mapping confidence, and **copy any medium straight into COBRApy**. Runs entirely in your browser.

<table>
<tr>
<td width="50%"><a href="https://omidard.github.io/Media/"><img src="shot_media_1.png" alt="Media landing page: a searchable library of thousands of GEM-ready growth media" width="100%"></a></td>
<td width="50%"><a href="https://omidard.github.io/Media/patterns.html"><img src="shot_media_2.png" alt="Patterns page: hierarchically clustered heatmap of compound presence across media groups, with row and column dendrograms" width="100%"></a></td>
</tr>
<tr>
<td width="50%"><a href="https://omidard.github.io/Media/compare.html"><img src="shot_media_3.png" alt="Compare page: Jaccard similarity matrix and UpSet intersection plot for selected media" width="100%"></a></td>
<td width="50%"><a href="https://omidard.github.io/Media/"><img src="shot_media_4.png" alt="A medium's full detail view: components mapped to BiGG exchanges with cross-references, citation, and one-click copy as a COBRApy medium" width="100%"></a></td>
</tr>
</table>

<p align="center">
  <em>Explore the library &middot; clustered composition patterns &middot; side-by-side comparison &middot; and every medium copyable straight into COBRApy</em><br><br>
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
`inferred` via name). Compounds that can't be mapped are listed in `uncovered`,
never dropped silently. Note that `exact` currently marks a name-table lookup as well as
a cross-referenced match; separating those tiers is in progress.

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

Rebuild the derived artifacts after new media land: `make derived`. See
[How this is built](#how-this-is-built) — the build has one entrypoint, and the
workflow calls the same targets, so the docs and CI cannot drift apart.

## Current contents — 13,515 media

Counted from `data/media/*.json`, which is the authority: every other total in the
repository is generated from it (`make derived`) and checked against it
(`python3 tools/verify_counts.py`). Grouping below is now by the source identity
**read from each record** (`provenance.source_name`, resolved by the
`20_stamp_provenance` stage), not by what the id prefix implies — the prefix filed
1,248 JCM and CCAP formulations under DSMZ. The table is `by_source_db` in
`data/index.json`, so it cannot drift from the catalogue.

| Source | Media | Licence | What it contributes |
|---|---:|---|---|
| **USDA FoodData Central** | 7,424 | CC0-1.0 | food media from analytically-measured composition (Foundation + SR Legacy) |
| **DSMZ MediaDive** | 3,148 | CC BY 4.0 | culture-media recipes (Koblitz *et al.*, NAR 2023). MediaDive redistributes other collections: 1,900 are DSMZ's own, 1,143 are JCM (RIKEN) and 105 are CCAP, recorded per record in `provenance.collection` |
| **Primary literature via GrowthDB** | 1,369 | CC BY 4.0 | formulations mined from growth-rate papers (defined and complex) |
| **FooDB** | 701 | CC BY-NC 4.0 | one medium per food (measured food composition) — **non-commercial** |
| **MediaDB (ISB defined media)** | 471 | all rights reserved | defined media from the ISB MediaDB — **non-commercial, redistributed by permission** |
| **Classic and standard formulations (project-curated)** | 297 | CC BY 4.0 | LB, TSB, BHI, blood agar, M9 / MOPS / M63 / Davis and the canonical reference set |
| **Primary literature (GEM papers)** | 88 | CC BY 4.0 | formulations mined from primary GEM papers |
| **Human Metabolome Database (HMDB 5.0)** | 9 | CC BY-NC 4.0 | host biofluids — **non-commercial** |
| **Bovine Metabolome Database (BMDB)** | 5 | permission required | bovine biofluids |
| **HMDB tables republished in an open-access paper** | 3 | CC BY-NC 4.0 | host biofluids — **non-commercial** |
| **total** | **13,515** | | |

1,189 of these records (8.8%) may not be used commercially; every record states its own
licence in `provenance.license` and the catalogue carries `commercial_use_ok`, so a
commercially usable subset is one filter away. See `LICENSE` and `NOTICE` for the
per-source schedule.

Categories: **laboratory** 5,373, **food** 8,125, **biospecimen** 17. (`growth_medium`,
a second-generation label carried by 443 laboratory records, is merged into
`laboratory` by the schema stage.)

Defined media map every compound to a BiGG exchange (salts dissociated to their ion
exchanges); complex media map their defined portion and render undefined hydrolysates
(peptone, extracts) as a clearly-labelled in-silico approximation, with the real ingredients
listed in `uncovered`.

## How this is built

The raw inputs this catalogue was built from are **gone**: nineteen generator scripts
pointed at a session scratchpad that was deleted, and none of the upstream payloads was
ever committed. `data/media/*.json` is the only surviving copy of the corpus, and 1,456
literature-derived records (`lit_`, `growthlit_`, `complexlit_`) came from LLM extractions
whose batch files no longer exist — re-running that miner would file *different*
compositions under the *same* citations, so it must not be run.

That has two consequences, and they shape everything:

1. **`data/media/` is a frozen snapshot.** It is not regenerable from its sources.
   `data/MANIFEST.json` records that explicitly, with the measured split between what is
   recoverable in principle (~87%, public upstreams) and what is not (1,456 records).
2. **Corrections are transform stages, never edits.** A correction is a program under
   `tools/stages/` that reads a corpus directory and writes a corrected corpus directory;
   `tools/stages/run_stages.py` composes them in a fixed, registered order and enforces the
   universal invariants after every stage. See
   [tools/stages/README.md](tools/stages/README.md) for the contract.

```bash
make check          # the stage registry and tools/stages/ agree
make sample         # deterministic 165-record sample corpus
make stages-sample  # run the chain over the sample (fast; checks idempotence)
make stages         # run the chain over all 13,515 media -> data/_rebuild/media
make test           # schema, invariants, defect ledger, harness, build tools
make derived        # rebuild index/stats/coverage/api/cluster/presence + MANIFEST
make verify         # rebuild the catalogue into a temp dir and compare totals
make promote        # back up data/media, then promote the corrected corpus over it
```

`make promote` is the only command that writes `data/media/`, and it backs the corpus up
first, refuses a corpus the runner did not produce, and never deletes a record.

### Re-acquiring the sources

```bash
python3 tools/fetch_sources.py --list      # what each source is, and its licence
python3 tools/fetch_sources.py --all       # re-fetch everything that is public
```

Downloads land in `data/_sources/` (gitignored). What *is* committed is
`data/_sources/MANIFEST.json`: per source, the URL, the HTTP status actually observed, the
retrieval date, the sha256 and the licence — and, for the sources that cannot be
re-acquired, an explicit `"status": "lost"` with the reason. Absence is recorded, not
implied.

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
