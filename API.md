# Media Data API (v1)

The **Media** dataset is served as a **read-only static API** over GitHub Pages.
Every file below is a plain HTTPS `GET`, returned with permissive CORS
(`Access-Control-Allow-Origin: *`) — so you can consume it from Python, R, JavaScript,
`curl`, or a browser, with **no key, no auth, and no rate limit**.

- **Base URL:** `https://omidard.github.io/Media`
- **Format:** JSON (records/catalog), Parquet + gzipped SQLite/JSONL (bulk)
- **Namespace:** components are keyed by BiGG exchange reactions (`EX_<met>_e`)
- **Bounds convention:** `lower_bound < 0` means **uptake** (mmol · gDW⁻¹ · h⁻¹)

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

Each `media[]` summary: `id`, `name`, `category`, `organism_scope`, `aerobic`,
`n_components`, `n_mapped`, `n_in_biggr`, `namespace`, `source_type`, `source_db`,
`defined`, `citation`, `food_group`.

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

Records also carry an `unmapped[]` list — components that could not be mapped are
**never silently dropped**.

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
GET /data/api/media.jsonl.gz        # one full medium record per line, gzipped (streamable)
```

Parquet is queryable **in place over HTTP** — no download step.

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
