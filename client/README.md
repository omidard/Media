# pymediadb

A tiny Python client for the [**Media** data API](https://github.com/omidard/Media) —
a curated, citation-backed library of growth / simulation media where every component
is mapped to a standard BiGG exchange reaction (`EX_<met>_e`), so any genome-scale
model can adopt a medium.

The dataset is served as static JSON + Parquet over GitHub Pages with permissive CORS,
so this client is just a thin, dependency-free wrapper over HTTP GETs (the analytics
helpers optionally use pandas / pyarrow / duckdb).

## Install

```bash
# core client (no third-party deps)
pip install "git+https://github.com/omidard/Media.git#subdirectory=client"

# with bulk/analytics helpers (pandas + pyarrow) and remote SQL (duckdb)
pip install "pymediadb[all] @ git+https://github.com/omidard/Media.git#subdirectory=client"
```

## Use

```python
from pymediadb import MediaDB

db = MediaDB()

# Catalog (counts + per-medium summaries)
cat = db.catalog()
print(cat["count"], "media")            # 12366

# Filter the catalog client-side
foods = db.list_media(category="food", defined=True)
minimal = db.list_media(contains="m9 glucose")

# One full medium: components, bounds, xrefs, provenance/citation
m = db.get_medium("m9_glucose_aerobic")

# Drop straight into a COBRApy model
import cobra
model = cobra.io.load_json_model("my_model.json")
model.medium = db.to_cobra_medium(m)    # {"EX_glc__D_e": 10.0, ...}
```

### Bulk / analytics

```python
media_df = db.load_media()              # one row per medium  (media.parquet)
comp_df  = db.load_components()          # one row per component (components.parquet)

# Remote SQL with DuckDB — no full download, reads the parquet over HTTP
db.query("SELECT category, count(*) n FROM media GROUP BY 1 ORDER BY n DESC")
db.query('''
  SELECT m.id, m.name
  FROM media m JOIN components c ON c.medium_id = m.id
  WHERE c.exchange = 'EX_glc__D_e' AND m.defined
  LIMIT 20
''')

# Stream every full record without fetching the 5 MB index
for rec in db.iter_full_records():
    ...
```

Responses are cached under `~/.cache/pymediadb` (24 h TTL by default; configurable via
`MediaDB(cache_dir=..., cache_ttl=...)`).

See the full endpoint reference in [`API.md`](https://github.com/omidard/Media/blob/main/API.md).
