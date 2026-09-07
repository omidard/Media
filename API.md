# Media Data API (v1)

The **Media** dataset is served as a **read-only static API** over GitHub Pages.
Every file below is a plain HTTPS `GET`, returned with permissive CORS
(`Access-Control-Allow-Origin: *`) — so you can consume it from Python, R, JavaScript,
`curl`, or a browser, with **no key, no auth, and no rate limit**.

- **Base URL:** `https://omidard.github.io/Media`
- **Format:** JSON (records/catalog), Parquet + gzipped SQLite/JSONL (bulk)
- **Namespace:** components are keyed by BiGG exchange reactions (`EX_<met>_e`) —
  **652,620 of 665,582 component records (98.1%)** reach one that EXISTS. 11,380 carry
  an id of the same shape naming **no BiGG reaction** (`EX_choles_e` is the largest: BiGG
  has `choles_c` only, and cholesterol's exchange is `EX_chsterol_e`), 1,364 carry a
  ModelSEED/MetaNetX/KEGG **fallback id no BiGG model will accept**, and 218 carry no
  exchange at all. `model.medium = {...}` drops all three without a word. Per record:
  `n_mapped`, `n_nonbigg_fallback`, `n_bigg_shaped_no_such_exchange`, `n_unmappable`.
- **Bounds convention:** `lower_bound < 0` means **uptake** (mmol · gDW⁻¹ · h⁻¹)
- **Licence:** the data is **CC BY-NC 4.0**, one licence for the whole compilation; the
  code is MIT. Every payload carries it as `license`. Attribution owed upstream is in
  [`NOTICE.txt`](./NOTICE.txt); see [`LICENSE.txt`](./LICENSE.txt).

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

`oxygen` is the regime a source or a curator actually **stated**, and it is `null` on
12,365 of 13,515 records. Most of the library has no stated regime: the curation script
ends in two catch-all branches that return `facultative` when the source says nothing,
recording that in `oxygen_note`, and 11,926 records are in that state. Those records
still export `EX_o2_e` open, which is a convention and not a finding;
`oxygen_default_for_simulation` carries it, and the O2 component is marked derived on
every record. `null` means unknown. It never means anaerobic. (The per-record files under
`/data/media/` still carry the `facultative` default in `oxygen`; correcting the corpus
is a transform stage, tracked in `tests/test_defects.py`.)

Each `media[]` summary: `id`, `name`, `category`, `organism_scope`, `aerobic`, `oxygen`,
`oxygen_default_for_simulation`,
`n_components`, `n_mapped`, `n_in_biggr`, `n_nonbigg_fallback`, `n_no_exchange`,
`namespace`, `source_type`, `source_db`, `verification_status`, `n_sourced`, `n_derived`, `n_unmappable`,
`pct_covered_source`, `pct_sourced_components_with_bigg_id`,
`model_input_signature`, `n_media_with_identical_model_input`,
`defined`, `citation`, `food_group`.

The catalog also carries four library-wide blocks, each with its denominator and its
definition inline: `exchange_resolution`, `cross_references`,
`model_input_degeneracy`, and `field_renames`.

#### Two media can be the same thing to a solver

A model reads the set of `(exchange, lower_bound, upper_bound)` triples and nothing
else — not the name, not the source, not the citation. By that measure **7,012 of
13,515 media (51.9%)** are indistinguishable from at least one other record (1,663
groups; the largest holds 93). Adding each component's source-stated concentration, a
stricter test than any solver applies, still leaves 6,508 (48.2%).

```
GET /data/web/twins.json          # the complete groups, by medium id
```

Per record the catalog carries `model_input_signature` (a hash of that triple set) and
`n_media_with_identical_model_input` (0 = unique). Records are not deduplicated by model
input: two identical constraint sets can still have two different provenances, and which
paper a formulation came from is a real difference.

#### Renamed field

`pct_covered_observed` → **`pct_sourced_components_with_bigg_id`** (2026-09-06). The
field's denominator is the components the record already carries, not the ingredients the
source published, so its value is `100.0` on 12,861 of 13,515 records and it is not a
coverage measure. It answers one question: of the components the source states, the share
that reached a BiGG id. For coverage of the source's ingredient list use
`pct_covered_source`. The catalog ships a `field_renames` block carrying both names and
that measurement, so a client holding the old key can resolve it.

The rename is applied by the transform chain (`tools/stages/remap_components.py`), so it
reaches the per-medium records as well as the catalog and the exports: all 13,515
published records carry `pct_sourced_components_with_bigg_id` and none carries the old
key.

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
| `xref_id` | key into [`/data/refs.json`](https://omidard.github.io/Media/data/refs.json) → `xrefs`: the cross-reference block (`inchikey`, `kegg`, `chebi`, `hmdb`, `mnx`, `seed`, `biocyc`, `formula`, …). **Absent means the component has no cross-references** — 8,957 of 665,582 — never "look elsewhere". The parquet/SQLite columns `xref_inchikey`, `xref_kegg`, … are joined for you |
| `in_biggr` | whether the metabolite exists in the local BiGGr universal model |
| `mapping_method` / `mapping_confidence` | how the name was mapped, and how confident |
| `evidence_tier` | how the identity was ACTUALLY decided — one of twelve tiers (`structural_xref`, `source_bigg_id`, `curated_mapping`, `exact_name`, `name_table`, `fuzzy_name`, `class_proxy`, `author_asserted`, `non_bigg_fallback`, `derived_component`, `unmapped`, `unmappable_mixture`). Read this, not `mapping_confidence` |
| `mapping_note_id` | key into `/data/refs.json` → `notes`: why, in prose, where the mapping needs a warning — e.g. "this exchange id is NOT a BiGG identifier and no BiGG model will accept it". 113 distinct notes over 621,274 components |
| `xref_note_id` | key into `/data/refs.json` → `notes`. On 654,067 of 665,582 components, carrying "these cross-references describe the BiGG id that was chosen; they were not used to choose it and cannot contradict it" |
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

### The payloads the browser reads

The five browser pages are served from these. They are documented here because the
pages link to this file rather than printing repository paths in their prose, and
two of them were previously named nowhere else.

```
GET /data/web/catalog.json        # the browse table: 13,515 rows, dictionary-encoded
GET /data/web/summary.json        # the same library-wide blocks with no rows
GET /data/web/families.json       # base-medium families and their members
GET /data/web/compounds.json      # compound -> media postings, for the compound filter
GET /data/web/tombstones.json     # withdrawn identifiers and their reason codes
GET /data/cluster/clustergram.json    # precomputed Ward linkage over the library
GET /data/cluster/cooccurrence.json   # pairwise compound co-occurrence
```

`catalog.json` and `index.json` are the same catalogue in two shapes.
`catalog.json` encodes rows as arrays with a shared `columns` list and dictionary
columns, to keep the page small; `index.json` is the readable one and is the
documented endpoint for a consumer. Zip `columns` against a row to get objects.
`summary.json` carries every library-wide block from `catalog.json` and none of the
rows, for pages that render no per-medium table.

### Bulk / analytics

Built by [`tools/build_api_exports.py`](./tools/build_api_exports.py); inventory and
schemas in the manifest.

```
GET /data/api/manifest.json        # version, totals, file inventory, column schemas
GET /data/api/media.parquet        # one row per medium (summary + provenance)
GET /data/api/components.parquet    # one row per (medium, component), tidy/long form
GET /data/refs.json                # cross-reference and note tables; join on xref_id
```

Parquet is queryable **in place over HTTP** — no download step.

**The SQLite database and the JSON Lines shards are not served from this host, and
are not published anywhere else yet.**
GitHub Pages publishes the repository root and refuses a published site over 1 GiB,
and those two files are a re-encoding of `data/media`, which stays published because
the browser fetches `data/media/{id}.json` at runtime. They are meant to become
assets on a `data-v1` GitHub Release; that release **has not been created**, so
until it is, build them from a clone:

```bash
git clone https://github.com/omidard/Media && cd Media
make release-assets
# -> dist/api/media.sqlite.gz, dist/api/media.jsonl.part01.gz,
#    dist/api/manifest.json, dist/api/RELEASE_NOTES.md
```

`data/api/manifest.json` -> `bulk_download` states this in machine-readable form:

```json
"bulk_download": {
  "status": "published",
  "url_prefix": "https://github.com/omidard/Media/releases/download/data-v1",
  "url_prefix_is": "the prefix each asset is served from",
  "how_to_get_them_now": { "build_from_a_clone": ["...", "make release-assets"] }
}
```

A client reads `status` rather than assuming the release exists.
`pymediadb.iter_full_records()` uses the release while it is `published`, skips it while
it is `planned`, and falls back to the per-medium endpoint if an advertised asset is
unreachable; it yields all 13,515 records on every one of those paths. Every full record
is also fetchable one at a time at `/data/media/{id}.json`, and the parquet pair is
queryable over HTTP.

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
