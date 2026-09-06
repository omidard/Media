# Media Data API (v1)

The **Media** dataset is served as a **read-only static API** over GitHub Pages.
Every file below is a plain HTTPS `GET`, returned with permissive CORS
(`Access-Control-Allow-Origin: *`) — so you can consume it from Python, R, JavaScript,
`curl`, or a browser, with **no key, no auth, and no rate limit**.

- **Base URL:** `https://omidard.github.io/Media`
- **Format:** JSON (records/catalog), Parquet + gzipped SQLite/JSONL (bulk)
- **Namespace:** components are keyed by BiGG exchange reactions (`EX_<met>_e`) —
  664,000 of 665,582 component records (99.8%) reach one. 1,364 carry a
  ModelSEED/MetaNetX/KEGG **fallback id no BiGG model will accept**, and 218 carry no
  exchange at all. Per record: `n_mapped`, `n_nonbigg_fallback`, `n_unmappable`.
- **Bounds convention:** `lower_bound < 0` means **uptake** (mmol · gDW⁻¹ · h⁻¹)
- **Licence:** the code is MIT; the **data is not under a single licence**. It is per
  upstream source, and 1,189 of 13,515 records (8.8%) may not be used commercially.
  Every record carries `provenance.license` / `commercial_use_ok`; the schedule is
  [`LICENSE`](./LICENSE) and [`tools/licenses.tsv`](./tools/licenses.tsv).

A machine-readable description lives in [`openapi.yaml`](./openapi.yaml).
For a ready-made client see [`client/`](./client) (`pip install ".../#subdirectory=client"`).

---

## Endpoints

### Catalog

```
GET /data/index.json
```

The full catalog. Object with:

| field | type | notes |
|---|---|---|
| `count` | int | total number of media |
| `by_category` | object | counts per category (`food`, `laboratory`, `biospecimen`) |
| `by_source_db` | object | counts per source database |
| `media` | array | one **summary** object per medium (see below) |

Each `media[]` summary: `id`, `name`, `category`, `organism_scope`, `aerobic`, `oxygen`,
`n_components`, `n_mapped`, `n_in_biggr`, `n_nonbigg_fallback`, `n_no_exchange`,
`namespace`, `source_type`, `source_db`, `license`, `commercial_use_ok`,
`verification_status`, `n_sourced`, `n_derived`, `n_unmappable`,
`pct_covered_source`, `pct_sourced_components_with_bigg_id`,
`model_input_signature`, `n_media_with_identical_model_input`,
`defined`, `citation`, `food_group`.

The catalog also carries four library-wide blocks, each with its denominator and its
definition inline: `exchange_resolution`, `cross_references`,
`model_input_degeneracy`, and `field_renames`.

#### Two media can be the same thing to a solver

A model reads the set of `(exchange, lower_bound, upper_bound)` triples and nothing
else — not the name, not the source, not the citation. By that measure **6,827 of
13,515 media (50.5%)** are indistinguishable from at least one other record (1,623
groups; the largest holds 93). Adding each component's source-stated concentration, a
stricter test than any solver applies, still leaves 6,328 (46.8%).

```
GET /data/web/twins.json          # the complete groups, by medium id
```

Per record the catalog carries `model_input_signature` (a hash of that triple set) and
`n_media_with_identical_model_input` (0 = unique). Nothing was merged or deleted: two
identical constraint sets can still have two different provenances, and which paper a
formulation came from is a real difference.

#### One field was renamed

`pct_covered_observed` → **`pct_sourced_components_with_bigg_id`** (2026-09-06). The old
name read as coverage of the medium, but its denominator is the components the record
already carries rather than the ingredients the source published, so the value was
`100.0` on 12,861 of 13,515 records. It answers one question: of the components the
source states, the share that reached a BiGG id. For coverage of the source's ingredient
list use `pct_covered_source`. The catalog ships a `field_renames` block, with the
measurement, so a consumer of the old key finds out what happened rather than finding
the key missing.

### A single medium (full record)

```
GET /data/media/{id}.json
```

Full record for one medium: metadata, `provenance` (`source_type`, `citation`, `doi`,
`url`, `notes`), and a `components[]` array. Each component:

| field | meaning |
|---|---|
| `name` | human-readable component name |
| `bigg_metabolite` | BiGG metabolite id (e.g. `glc__D`) — `null` if unmapped |
| `exchange` | BiGG exchange reaction (e.g. `EX_glc__D_e`) |
| `lower_bound` / `upper_bound` | flux bounds; `lower_bound < 0` = uptake |
| `concentration_mM` | measured/known concentration where available |
| `xref` | cross-references (`inchikey`, `kegg`, `chebi`, `hmdb`, `mnx`, `seed`, `biocyc`, …) |
| `in_biggr` | whether the metabolite exists in the local BiGGr universal model |
| `mapping_method` / `mapping_confidence` | how the name was mapped, and how confident |
| `evidence_tier` | how the identity was ACTUALLY decided — one of twelve tiers (`structural_xref`, `source_bigg_id`, `curated_mapping`, `exact_name`, `name_table`, `fuzzy_name`, `class_proxy`, `author_asserted`, `non_bigg_fallback`, `derived_component`, `unmapped`, `unmappable_mixture`). Read this, not `mapping_confidence` |
| `mapping_note` | why, in prose, where the mapping needs a warning — e.g. "this exchange id is NOT a BiGG identifier and no BiGG model will accept it" |
| `source_observed` | `false` when the cited source does not state this component at all |

Records also carry an `uncovered[]` list — components that could not be given an
exchange are **never silently dropped**. (The field was documented as `unmapped[]`
until 2026-09; that name exists in 0 of the 13,515 shipped records — `enrich_coverage.py`
consumes it and writes `uncovered[]` instead.)

### Aggregate helpers

```
GET /data/media_stats.json        # component-frequency statistics
GET /data/presence_matrix.json    # medium × component presence matrix
```

### Bulk / analytics

Built by [`tools/build_api_exports.py`](./tools/build_api_exports.py); inventory and
schemas in the manifest.

```
GET /data/api/manifest.json        # version, totals, file inventory, column schemas
GET /data/api/media.parquet        # one row per medium (summary + provenance)
GET /data/api/components.parquet    # one row per (medium, component), tidy/long form
GET /data/api/media.sqlite.gz       # SQLite: media + components tables, indexed (gunzip first)
GET /data/api/media.jsonl.part01.gz # one full medium record per line, gzipped (streamable)
GET /data/api/media.jsonl.part02.gz # ... sharded: see the note below
```

Parquet is queryable **in place over HTTP** — no download step.

The JSON Lines export is **sharded**. The single file is 141 MB against the
corrected corpus, past GitHub's 100 MiB per-file hard limit, so it ships as
`media.jsonl.partNN.gz`. Concatenating the parts in name order reproduces the
original stream byte for byte, so `cat media.jsonl.part*.gz | gunzip` is a drop-in
replacement for the old endpoint. The parts and their row counts are listed in
`data/api/manifest.json`; `tools/build_api_exports.py` asserts that no artifact
exceeds the budget, so this cannot silently regress into an unpushable file again.

---

## Recipes

### curl

```bash
curl -s https://omidard.github.io/Media/data/index.json | jq '.count, .by_category'
curl -s https://omidard.github.io/Media/data/media/m9_glucose_aerobic.json | jq '.components[].exchange'
```

### Python (stdlib only)

```python
import urllib.request, json
BASE = "https://omidard.github.io/Media/data"
def get(p): return json.load(urllib.request.urlopen(f"{BASE}/{p}"))

cat = get("index.json")
m   = get("media/m9_glucose_aerobic.json")
medium = {c["exchange"]: abs(c["lower_bound"])
          for c in m["components"]
          if c["exchange"] and c["lower_bound"] < 0}
# model.medium = medium   # COBRApy
```

### Python (pandas + DuckDB, remote SQL — no full download)

```python
import duckdb
con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
B = "https://omidard.github.io/Media/data/api"
con.execute(f"CREATE VIEW media AS SELECT * FROM read_parquet('{B}/media.parquet')")
con.execute(f"CREATE VIEW components AS SELECT * FROM read_parquet('{B}/components.parquet')")

con.sql("SELECT category, count(*) FROM media GROUP BY 1 ORDER BY 2 DESC")
con.sql("""
  SELECT m.id, m.name FROM media m
  JOIN components c ON c.medium_id = m.id
  WHERE c.exchange = 'EX_glc__D_e' AND m.defined LIMIT 20
""")
```

### R

```r
library(jsonlite)
cat  <- fromJSON("https://omidard.github.io/Media/data/index.json")
m    <- fromJSON("https://omidard.github.io/Media/data/media/m9_glucose_aerobic.json")
# arrow::read_parquet("https://omidard.github.io/Media/data/api/media.parquet")
```

### JavaScript (browser / Node)

```js
const BASE = "https://omidard.github.io/Media/data";
const cat = await (await fetch(`${BASE}/index.json`)).json();
const m   = await (await fetch(`${BASE}/media/m9_glucose_aerobic.json`)).json();
```

---

## Stability & versioning

- The paths above are the **v1** surface and are intended to remain stable.
- The dataset grows over time; treat `count` and the bulk files as point-in-time.
  Rebuild the bulk artifacts after new media land: `python3 tools/build_api_exports.py`.
- Every medium is citation-backed. When using a medium, cite both this resource and the
  `provenance.citation` / `doi` recorded on the medium.
